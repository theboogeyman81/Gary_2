# Gary Pi Migration Plan

## Context

All of Gary's code currently runs on the Mac. The vision pipeline (YOLO + MediaPipe + ArUco)
is CPU-bound and needs to move to a Raspberry Pi 5 + Hailo-8 AI HAT (26 TOPS) for real-time
inference. Cameras will be two XIAO ESP32-S3 Sense modules streaming MJPEG over WiFi.
The Mac laptop app keeps all its current capabilities (overlay UI, voice agent, HA tools,
Fire TV, teaching mode, YouTube notes) and stays untouched. Redis pub/sub is the clean
boundary between Mac and Pi.

**Golden rule: nothing in `laptop_app/` or any Mac-facing tool changes.**

---

## Target Architecture

```
XIAO ESP32-S3 (POV)  ──MJPEG/WiFi──┐
XIAO ESP32-S3 (hand) ──MJPEG/WiFi──┤
                                    ▼
                        Raspberry Pi 5 + Hailo-8 AI HAT
                        ┌──────────────────────────────┐
                        │  dual_pipeline.py             │
                        │  XiaoStream (MJPEG parser)    │
                        │  Hailo inference (YOLOv8n)    │
                        │  MediaPipe hand tracking      │
                        │  ArUco detection              │
                        └──────────────┬───────────────┘
                                       │ Redis events over LAN/hotspot
                                       ▼
                        Mac (Redis @ localhost)
                        ┌──────────────────────────────┐
                        │  gesture_correlator.py        │
                        │  agent/main_loop.py           │
                        │  laptop_app/ (overlay + voice)│
                        └──────────────────────────────┘
```

Redis runs on Mac. Pi connects remotely via `REDIS_HOST=raspberrypi.local` (mDNS — works
on any network, no IP reconfiguration needed between home and exhibition).

---

## Phase 1 — Make Redis Network-Aware (zero breakage)

**Why first:** Everything else depends on Mac↔Pi communication over Redis.
Mac stays on `localhost`. Pi uses mDNS hostname. No callers need to change.

### Files to change:

**`config/settings.py`** — add two lines:
```python
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
```

**`bus/redis_bus.py`** — change `Bus.__init__` defaults to read from settings:
```python
from config.settings import REDIS_HOST, REDIS_PORT

class Bus:
    def __init__(self, host: str = REDIS_HOST, port: int = REDIS_PORT):
```

All 14 `Bus()` call sites stay unchanged. Mac `.env` needs no new entries (localhost is default).

**Mac Redis — bind to all interfaces:** Redis by default only binds to `127.0.0.1`.
Edit `/opt/homebrew/etc/redis.conf`:
```
bind 0.0.0.0
protected-mode no
```
Then `brew services restart redis`. Only do on trusted networks (home + known exhibition venue).

**Pi `.env`:**
```
REDIS_HOST=<Mac's mDNS hostname>.local   # e.g. pratham-macbook.local
REDIS_PORT=6379
```

Find Mac's mDNS hostname: `scutil --get LocalHostName` on Mac, then append `.local`.
This hostname works on home WiFi, mobile hotspot, or any LAN — no changes ever needed.

**Verification:** `uv run python -m scripts.monitor_bus` from Pi — events should appear on Mac terminal.

---

## Phase 2 — Implement XiaoStream (activates camera swap)

**File:** `pipelines/camera_source.py` — the `XiaoStream` stub.

Full MJPEG approach documented in `.claude/plans/xiao-esp32s3-camera.md`. Key points:
- URL: `http://<host>/stream` (ESP32 CameraWebServer default)
- Scan byte stream for `\xff\xd8` (JPEG start) and `\xff\xd9` (JPEG end)
- Decode with `cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)`
- Wrap `iter_content` in `asyncio.to_thread` to stay non-blocking
- Add reconnect loop: if connection drops, sleep 2s and retry

**Use mDNS hostnames for XIAO cameras** — set the ESP32 hostname in the Arduino sketch:
```cpp
WiFi.setHostname("xiao-pov");   // accessible as xiao-pov.local
WiFi.setHostname("xiao-hand");  // accessible as xiao-hand.local
```

**Pi `.env`:**
```
POV_CAMERA_SOURCE=xiao:xiao-pov.local
HAND_CAMERA_SOURCE=xiao:xiao-hand.local
```

These hostnames resolve on any network — no IP changes between home and exhibition.

`MacWebcam` is untouched. Mac `.env` keeps `POV_CAMERA_SOURCE=mac:0`.

**Verification:** Temporarily run `dual_pipeline.py` on Mac pointing at XIAO mDNS names
to confirm MJPEG parsing works before moving everything to Pi.

---

## Phase 3 — Hailo Detector Abstraction

**Goal:** Swap YOLO backend via `YOLO_MODEL` file extension. Mac uses ultralytics unchanged. Pi uses Hailo.

### New file: `pipelines/hailo_detector.py`

`HailoDetector` wraps `hailo_platform` (HailoRT SDK) and matches the ultralytics interface:

```python
class HailoDetector:
    def __init__(self, hef_path: str, class_names: list[str]):
        ...  # load .hef via hailo_platform.VDevice + InferVStreams

    def __call__(self, frame: np.ndarray, verbose=False) -> list:
        ...  # pre-process → infer → parse output tensors → return Results-like list

    @property
    def names(self) -> dict[int, str]:
        return {i: n for i, n in enumerate(self._class_names)}
```

Output must match what `_detect_yolo()` in `pov_pipeline.py` consumes:
`results[0].boxes` where each box has `.cls`, `.conf`, `.xyxy`.

### New file: `pipelines/detector_factory.py`

```python
def load_detector(model_path: str):
    if model_path.endswith(".hef"):
        from pipelines.hailo_detector import HailoDetector
        return HailoDetector(model_path, COCO_NAMES)
    else:
        from ultralytics import YOLO
        return YOLO(model_path)
```

### Change in `pov_pipeline.py`, `dual_pipeline.py`, `combined_pipeline.py`

Replace `YOLO(YOLO_MODEL)` with `load_detector(YOLO_MODEL)`. `_detect_yolo()` is unchanged.

- Mac `.env`: `YOLO_MODEL=yolov8n.pt` → ultralytics path (no change)
- Pi `.env`: `YOLO_MODEL=yolov8n.hef` → Hailo path

### Hailo model prep

YOLOv8n `.hef` is available pre-compiled in Hailo's model zoo — no DataFlow Compiler needed.
Download from `github.com/hailo-ai/hailo_model_zoo` and transfer to Pi project root.

Install HailoRT on Pi:
```bash
sudo dpkg -i hailort_*.deb          # from developer.hailo.ai
pip install hailo_platform           # must match installed runtime version
```

Guard the import in `hailo_detector.py` with a clear error if run on Mac without hailo_platform:
```python
try:
    import hailo_platform
except ImportError:
    raise ImportError("hailo_platform not installed — this detector only runs on Pi with Hailo HAT")
```

---

## Phase 4 — Pi Dependency Isolation

Pi doesn't need `pywebview`, `mss`, `livekit-agents`, `AppKit/pyobjc`, or `pynput`.

**`pyproject.toml`** — add optional dependency groups:

```toml
[project.optional-dependencies]
mac = ["pywebview", "mss", "livekit-agents[cartesia,deepgram,google,silero]", "pynput"]
pi  = []  # hailo_platform installed via .deb; mediapipe/opencv already in core deps
```

Pi install: `uv sync` (core only).
Mac install: `uv sync --extra mac` (current behavior, now explicit).

---

## Phase 5 — Pi Deployment

### Pi `.env`
```
REDIS_HOST=<mac-hostname>.local     # e.g. pratham-macbook.local  ← works on any network
REDIS_PORT=6379
POV_CAMERA_SOURCE=xiao:xiao-pov.local
HAND_CAMERA_SOURCE=xiao:xiao-hand.local
YOLO_MODEL=yolov8n.hef
SHOW_CAMERA=false
```
No HA_URL/HA_TOKEN/LiveKit/Deepgram/Cartesia/Gemini keys on Pi.

### Process split

| Process | Runs on | Command |
|---|---|---|
| `dual_pipeline.py` | **Pi** | `uv run python -m pipelines.dual_pipeline` |
| `gesture_correlator.py` | Mac | `uv run python -m pipelines.gesture_correlator` |
| `agent/main_loop.py` | Mac | `uv run python -m agent.main_loop` |
| `laptop_app/main_pywebview.py` | Mac | `uv run python -m laptop_app.main_pywebview` |
| `laptop_app/voice_agent.py` | Mac | `uv run python -m laptop_app.voice_agent start` |

### Startup script for Pi
`scripts/start_pi.sh`:
```bash
#!/bin/bash
cd /home/pi/Gary_2
uv run python -m pipelines.dual_pipeline
```
Set as systemd service for auto-start on Pi boot (optional).

---

## Phase 6 — Exhibition Day Safety (mobile hotspot)

Three things to do before the exhibition. None require code changes at the venue.

### 6a. Match hotspot SSID/password to home WiFi (zero-reflash strategy)

Set your phone's mobile hotspot SSID and password to **exactly the same values as your home
WiFi**. All devices (Mac, Pi, both XIAOs) will auto-connect without any changes. This is
the single most important prep step.

### 6b. mDNS hostnames (already in the plan above)

Because Phases 1 and 2 use `raspberrypi.local`, `xiao-pov.local`, `xiao-hand.local` instead
of hardcoded IPs, DHCP address changes on the hotspot are invisible to the system. No `.env`
edits needed at the venue.

### 6c. HA graceful fallback

Home Assistant lives at `192.168.1.6` — your home server, unreachable at the exhibition.
Add a `try/except` in `tools/home_assistant.py` around the `aiohttp` call:

```python
except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
    await bus.publish(Event(type="show_toast", source="home_assistant",
                            payload={"text": "Smart home not reachable here"}))
    return
```

Gary gracefully says it can't reach the smart home instead of hanging or crashing.
Voice, teaching mode, YouTube notes, gestures, and overlay all continue to work fine.

### What works on hotspot (no changes needed)

| Feature | Status |
|---|---|
| Voice agent (LiveKit/Deepgram/Gemini/Cartesia) | ✓ cloud, internet via hotspot |
| Gary overlay UI | ✓ |
| Teaching mode | ✓ |
| YouTube notes | ✓ |
| Screenshot capture | ✓ |
| Gesture detection (pinch → correlator) | ✓ |
| Redis Mac ↔ Pi | ✓ mDNS, same hotspot |
| XIAO cameras streaming to Pi | ✓ same hotspot |
| HA light / Fire TV control | ✗ gracefully fails with toast |

---

## What Does NOT Change (guaranteed safe)

- `laptop_app/` — zero edits
- `agent/` — zero edits
- `events/schema.py` — zero edits
- `bus/redis_bus.py` — only `__init__` default values change (additive)
- Mac's `.env` — no required new keys
- All 14 `Bus()` call sites — unchanged
- `MacWebcam` class — untouched
- `_detect_yolo()` function signature — untouched
- `gesture_correlator.py` — untouched

---

## Verification / End-to-End Test

1. `scripts/monitor_bus.py` on Mac — confirm Pi events arrive over LAN/hotspot
2. Flash XIAO units with matching WiFi SSID/password and mDNS hostnames; open `http://xiao-pov.local/stream` in browser
3. Run `dual_pipeline.py` on Pi, show ArUco marker to POV cam → `device_entered_view` in monitor
4. Pinch in front of hand cam → `pinch_detected` then `gesture_command` appears
5. Spacebar hold on Mac → voice agent responds → Gary arc animates
6. Simulate no HA (unplug home hub) → Gary shows toast, doesn't crash
7. Repeat steps 3–6 on mobile hotspot with same SSID

---

## Implementation Order

1. **Phase 1** — Redis network-aware (5 min, zero risk)
2. **Phase 2** — XiaoStream with mDNS (test on Mac first while XIAO on WiFi)
3. **Phase 3** — Hailo abstraction (Mac path unchanged throughout)
4. **Phase 6c** — HA graceful fallback (small, safe, important for exhibition)
5. **Phase 4** — Pi dep isolation in pyproject.toml
6. **Phase 5** — Clone + deploy on Pi, configure `.env`, run pipelines

Each phase is independently testable. Mac never breaks between phases.
