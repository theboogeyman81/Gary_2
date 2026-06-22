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
                                       │ Redis events over LAN
                                       ▼
                        Mac (Redis @ localhost)
                        ┌──────────────────────────────┐
                        │  gesture_correlator.py        │
                        │  agent/main_loop.py           │
                        │  laptop_app/ (overlay + voice)│
                        └──────────────────────────────┘
```

Redis runs on Mac. Pi connects remotely via `REDIS_HOST=<mac-lan-ip>`.
Pi only runs the vision pipelines. All reasoning, tools, and UI stay on Mac.

---

## Phase 1 — Make Redis Network-Aware (zero breakage)

**Why first:** Everything else depends on Mac↔Pi communication over Redis.
Mac stays on `localhost`. Pi sets `REDIS_HOST=<mac-ip>`. No callers need to change.

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

All 14 `Bus()` call sites stay unchanged. Mac `.env` needs no new entries (localhost is the default).

**Mac Redis firewall:** Redis by default only binds to `127.0.0.1`. Edit `/opt/homebrew/etc/redis.conf`:
```
bind 0.0.0.0
protected-mode no
```
Then `brew services restart redis`. Only do this on a trusted home network.

**Verification:** `REDIS_HOST=<mac-ip> uv run python -m scripts.monitor_bus` from Pi — events should appear.

---

## Phase 2 — Implement XiaoStream (activates camera swap)

**File:** `pipelines/camera_source.py` — the `XiaoStream` class stub at the bottom.

The plan at `.claude/plans/xiao-esp32s3-camera.md` has the full MJPEG approach.
Key implementation notes:
- URL: `http://<host>/stream` (ESP32 CameraWebServer default)
- Read response body continuously, scan for `\xff\xd8` (JPEG start) and `\xff\xd9` (JPEG end)
- Decode with `cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)`
- Wrap `iter_content` in `asyncio.to_thread` to stay non-blocking
- Add reconnect logic: if connection drops, sleep 2s and retry

`MacWebcam` is untouched. Mac `.env` keeps `POV_CAMERA_SOURCE=mac:0`.

**Pi `.env` entries to set:**
```
POV_CAMERA_SOURCE=xiao:192.168.1.X
HAND_CAMERA_SOURCE=xiao:192.168.1.Y
```

**Verification:** Temporarily run `dual_pipeline.py` on Mac pointing at XIAO IPs (while XIAO is powered) to confirm MJPEG parsing works before moving to Pi.

---

## Phase 3 — Hailo Detector Abstraction

**Goal:** Swap YOLO backend at runtime via env var. Mac keeps ultralytics (unchanged). Pi uses Hailo.

### New file: `pipelines/hailo_detector.py`

A `HailoDetector` class that wraps `hailo_platform` (HailoRT Python SDK) and presents the same
interface as `ultralytics.YOLO`. Key shape:

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

The output must match what `_detect_yolo()` in `pov_pipeline.py` consumes:
`results[0].boxes` where each box has `.cls`, `.conf`, `.xyxy`.

### Factory function: `pipelines/detector_factory.py`

```python
def load_detector(model_path: str):
    if model_path.endswith(".hef"):
        from pipelines.hailo_detector import HailoDetector
        return HailoDetector(model_path, COCO_NAMES)
    else:
        from ultralytics import YOLO
        return YOLO(model_path)
```

### Change in `pov_pipeline.py` (and `dual_pipeline.py`, `combined_pipeline.py`)

Replace `YOLO(YOLO_MODEL)` with `load_detector(YOLO_MODEL)`. That's it — `_detect_yolo()` is unchanged.

**`config/settings.py`** — no new setting needed; detection is inferred from `YOLO_MODEL` extension:
- Mac `.env`: `YOLO_MODEL=yolov8n.pt` → ultralytics
- Pi `.env`: `YOLO_MODEL=yolov8n.hef` → Hailo

### Hailo model prep

YOLOv8n is in Hailo's pre-compiled model zoo. Download the `.hef` directly from
[github.com/hailo-ai/hailo_model_zoo](https://github.com/hailo-ai/hailo_model_zoo) → no
DataFlow Compiler needed. Transfer `yolov8n.hef` to Pi project root.

Install HailoRT on Pi via Hailo's official `.deb` package:
```bash
# On Pi (after downloading hailo-rt from developer.hailo.ai)
sudo dpkg -i hailort_*.deb
pip install hailo_platform  # matches installed runtime version
```

---

## Phase 4 — Pi Dependency Isolation

Pi doesn't need `pywebview`, `mss`, `livekit-agents`, `AppKit/pyobjc`, or `pynput`.
Mac shouldn't need `hailo_platform`.

**`pyproject.toml`** — add optional dependency groups:

```toml
[project.optional-dependencies]
mac = ["pywebview", "mss", "livekit-agents[...]", "pynput"]
pi  = []  # hailo_platform installed via .deb, not pip; mediapipe/opencv already in core
```

Pi install: `uv sync` (core deps only) — no `--extra mac` flag.
Mac install: `uv sync --extra mac` (already done; this just makes it explicit).

For now, `hailo_platform` is NOT in pyproject.toml (installed system-wide via .deb on Pi).
Guard the import in `hailo_detector.py` with a try/except so importing on Mac without
hailo_platform raises a clear `ImportError` at load time, not at detection time.

---

## Phase 5 — Pi Deployment

### Pi `.env` (project root on Pi)
```
REDIS_HOST=192.168.1.X      # Mac's LAN IP
REDIS_PORT=6379
POV_CAMERA_SOURCE=xiao:192.168.1.A
HAND_CAMERA_SOURCE=xiao:192.168.1.B
YOLO_MODEL=yolov8n.hef
SHOW_CAMERA=false
HA_URL=http://192.168.1.6:8123
HA_TOKEN=<same token>
```
No LiveKit/Deepgram/Cartesia/Gemini keys needed on Pi — those stay Mac-only.

### Process split

| Process | Runs on | Command |
|---|---|---|
| `dual_pipeline.py` | Pi | `uv run python -m pipelines.dual_pipeline` |
| `gesture_correlator.py` | Mac | `uv run python -m pipelines.gesture_correlator` |
| `agent/main_loop.py` | Mac | `uv run python -m agent.main_loop` |
| `laptop_app/main_pywebview.py` | Mac | `uv run python -m laptop_app.main_pywebview` |
| `laptop_app/voice_agent.py` | Mac | `uv run python -m laptop_app.voice_agent start` |
| `scripts/monitor_bus.py` | Mac | for dev only |

### Startup script for Pi (future)
Once stable: `scripts/start_pi.sh` with `uv run python -m pipelines.dual_pipeline &`.
Can also set up a systemd unit for auto-start on Pi boot.

---

## What Does NOT Change (guaranteed safe)

- `laptop_app/` — zero edits
- `agent/` — zero edits
- `tools/` — zero edits
- `events/schema.py` — zero edits
- `bus/redis_bus.py` — only the `__init__` default values change (additive)
- Mac's `.env` — no required new keys; existing keys stay as-is
- All `Bus()` call sites — no edits needed (defaults cover them)
- `MacWebcam` class — untouched
- `_detect_yolo()` function signature — untouched
- `gesture_correlator.py` — zero edits (pure Redis subscriber, no hardware)

---

## Verification / End-to-End Test

1. `scripts/monitor_bus.py` running on Mac — confirms Pi events arrive over LAN
2. Flash both XIAO units; open `http://<ip>/stream` in browser — confirm MJPEG streams
3. Run `dual_pipeline.py` on Pi, point ArUco marker at POV cam — `device_entered_view` appears in monitor
4. Pinch in front of hand cam — `pinch_detected` then `gesture_command` appears
5. Confirm HA toggle fires (light turns on/off)
6. Spacebar hold on Mac → voice agent responds → Gary UI arc animates
7. All existing Mac features (Fire TV, teaching, YouTube notes) continue to work unaffected

---

## Implementation Order (safe-by-design)

1. Phase 1 (Redis network) — 5 min, zero risk, test immediately
2. Phase 2 (XiaoStream) — implement + test on Mac first with XIAO on same WiFi
3. Phase 3 (Hailo abstraction) — implement factory; Mac path unchanged since `yolov8n.pt` → ultralytics
4. Phase 4 (Pi deps) — document/annotate pyproject.toml
5. Phase 5 (Pi deploy) — clone repo on Pi, copy `.env`, run pipelines

Each phase is independently testable and mergeable. Mac never breaks between phases.
