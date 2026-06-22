# XIAO ESP32-S3 Sense — Camera Integration Plan

## Goal
Replace the Mac webcam (`mac:0`) with the XIAO ESP32-S3 Sense mounted on glasses,
streaming live video over WiFi as the input to Gary's pipelines.

## Hardware
- **Board:** Seeed Studio XIAO ESP32-S3 Sense
- **Camera:** OV3660 (3MP)
- **Mic:** Built-in PDM (ICS-43434)
- **Audio out:** MAX98357A I2S amplifier + bone conduction transducer (to add later)
- **Connectivity:** 2.4GHz WiFi + BLE 5.0

## Status
- [ ] Hardware purchased
- [ ] Hardware arrived
- [ ] Firmware flashed
- [ ] Stream verified in browser
- [ ] `XiaoStream` implemented
- [ ] Pipelines running on XIAO stream
- [ ] Mic audio routed (future)
- [ ] Bone conduction audio (future)

---

## Phase 1 — Firmware (Arduino IDE, ~15 min)

### 1.1 Setup Arduino IDE
1. Install Arduino IDE 2.x
2. Add ESP32 board package: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. Board Manager → install **esp32 by Espressif** (2.x or later)

### 1.2 Flash CameraWebServer sketch
1. Open: **File → Examples → ESP32 → Camera → CameraWebServer**
2. At the top of the sketch, uncomment exactly this line and comment all others:
   ```cpp
   #define CAMERA_MODEL_XIAO_ESP32S3
   ```
3. Set WiFi credentials:
   ```cpp
   const char* ssid     = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```
4. Select board: **Tools → Board → esp32 → XIAO_ESP32S3**
5. Select port: the USB-C port that appears when plugged in
6. Upload. Open Serial Monitor at 115200 baud.
7. Note the IP address printed: e.g. `Camera Ready! Use 'http://192.168.1.42' to connect`

### 1.3 Verify stream in browser
- Open `http://<ip>/stream` — should show live MJPEG video
- If OV3660 is detected wrongly, change camera model in sketch to check

---

## Phase 2 — XiaoStream client (Python)

File to edit: `pipelines/camera_source.py` — the `XiaoStream` class at line 79.

### 2.1 Approach
The ESP32 CameraWebServer serves a standard MJPEG stream:
- URL: `http://<host>/stream`
- Content-Type: `multipart/x-mixed-replace; boundary=frame`
- Each part: JPEG bytes preceded by `--frame\r\nContent-Type: image/jpeg\r\n\r\n`

Use `requests` (already available via OpenCV's deps) with `stream=True` to read
the multipart response and decode each JPEG chunk into a numpy frame with
`cv2.imdecode`.

### 2.2 Implementation sketch
```python
class XiaoStream:
    def __init__(self, host: str) -> None:
        self._host = host
        self._url = f"http://{host}/stream"

    async def open(self) -> None:
        pass  # connection happens lazily in frames()

    async def frames(self) -> AsyncIterator[np.ndarray]:
        import requests
        response = await asyncio.to_thread(
            lambda: requests.get(self._url, stream=True, timeout=10)
        )
        buffer = bytes()
        for chunk in response.iter_content(chunk_size=4096):
            buffer += chunk
            # Find JPEG start/end markers
            start = buffer.find(b'\xff\xd8')
            end = buffer.find(b'\xff\xd9')
            if start != -1 and end != -1:
                jpg = buffer[start:end+2]
                buffer = buffer[end+2:]
                frame = cv2.imdecode(
                    np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if frame is not None:
                    yield frame

    async def close(self) -> None:
        pass
```

Note: the real implementation will wrap `iter_content` in `asyncio.to_thread`
properly so it doesn't block the event loop. Sketch above shows the logic only.

### 2.3 Config change to activate
In `.env` (or `config/settings.py`), change:
```
HAND_CAMERA_SOURCE=xiao:192.168.1.42
POV_CAMERA_SOURCE=xiao:192.168.1.42
```
Both pipelines share one physical camera (the glasses), so use `combined_pipeline`
rather than running `pov_pipeline` and `hand_pipeline` separately.

---

## Phase 3 — Mic audio (future)

The XIAO's PDM mic can stream audio over WiFi, but this requires custom firmware
(e.g. ESP-IDF I2S + WebSocket audio sender). Skip until camera streaming is stable.

Short-term: Mac mic continues to handle voice input (already works via Gary's
voice trigger). The glasses mic becomes useful when Gary is untethered from the Mac.

---

## Phase 4 — Bone conduction audio (future)

Hardware to add to the glasses frame:
- **MAX98357A** I2S amplifier breakout (~$3)
- **Bone conduction transducer** (~$5-10, AliExpress)
- Wired to XIAO I2S pins: BCLK, LRCLK, DIN

Firmware: receive audio over WiFi (WebSocket or UDP) and play via I2S DAC.
This lets Gary speak through the glasses without routing audio through the Mac speakers.

---

## Architecture summary (end state)

```
[XIAO on glasses]
  OV3660 camera ──WiFi MJPEG──→ XiaoStream → combined_pipeline
  PDM mic ────────WiFi audio──→ (future) voice pipeline
  Bone conduction ←WiFi audio── (future) speak tool

[Mac]
  combined_pipeline → Redis bus → AI agent → tools
  laptop_app (pywebview) shows cards, plays audio via AirPods/speakers
```

---

## Notes
- The XIAO and Mac must be on the same WiFi network
- MJPEG over WiFi adds ~30-80ms latency — acceptable for gesture detection
- OV3660 vs OV2640: verify which camera chip is on the board when it arrives,
  update the `#define` in the Arduino sketch if needed
- Audio to AirPods routes through Mac (already paired), not through XIAO —
  this is by design; the Mac is the brain
