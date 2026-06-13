# Spec 02 — Gesture Pipeline
 
**Status:** Draft
**Owner:** Pratham
**Target chat scope:** Pipelines & Tools (Gary: Senses & Hands)
**Depends on:** Spec 01 (voice pipeline), existing `bus/`, `events/`, `agent/`, `tools/home_assistant.py`
 
---
 
## 1. Feature summary
 
A two-camera gesture system that lets the user control a smart device by **looking at it and pinching**. The POV (forward) camera identifies what device the user is looking at. The hand (downward) camera detects when the user pinches. When the two align in time, a `gesture_command` event is published to the bus and the agent toggles the device.
 
Both cameras are webcams during development on the Mac. On the Pi, both will be live MJPEG/WebRTC streams from the XIAO ESP32-S3 boards on the glasses, with detection offloaded to the Hailo-8.
 
---
 
## 2. Goals / Non-goals
 
### Goals
- Pinch while looking at a known device → device toggles, end-to-end, **target latency 300ms** from pinch release to HA API call.
- Pipeline runs on Mac (dev) and Pi+Hailo (prod) with **the same code**; only the camera source and YOLO backend change.
- One device registry shared between gesture pipeline and HA tool. No drift.
- Gesture detection is **independent** of pointing geometry. The two cameras don't need to be calibrated against each other.
### Non-goals (v1)
- Pointing at a device with a finger ray. (Looking at it is enough.)
- Multi-step gestures (swipe, drag, multi-finger). Pinch only.
- Gesture-only commands without a device target (e.g., "pinch in empty space to dismiss notification").
- Gesture commands more complex than toggle (no brightness/volume scrubbing yet).
- Custom-trained YOLO. Start with a stock model + the COCO classes that exist (`tv`, `laptop`, etc.). For non-COCO devices like a smart bulb, **fall back to an ArUco marker** stuck on the device until a fine-tuned model is ready.
---
 
## 3. User scenario (concrete walkthrough)
 
> User is sitting at their desk. The bedroom lamp is visible across the room. User glances at the lamp. POV pipeline detects the lamp is centered in frame, publishes `device_entered_view { device_id: light.bedroom_lamp }`. The user pinches their thumb and index finger together. Hand pipeline detects the pinch, publishes `pinch_detected`. The correlator sees both conditions are true, looks up the largest-bbox device currently in view (the lamp), publishes `gesture_command { device_id: light.bedroom_lamp, gesture: pinch }`. Agent receives the event, infers intent = toggle, calls `control_device(entity_id=light.bedroom_lamp, action=toggle)`. Lamp toggles. Agent publishes a brief `speak` event ("got it") for confirmation.
 
---
 
## 4. Architecture
 
```
┌─────────────────────┐         ┌─────────────────────┐
│  POV webcam         │         │  Hand webcam        │
│  (forward-facing)   │         │  (downward-facing)  │
└──────────┬──────────┘         └──────────┬──────────┘
           │ frames                        │ frames
           ▼                               ▼
┌─────────────────────┐         ┌─────────────────────┐
│  pov_pipeline.py    │         │  hand_pipeline.py   │
│  - YOLO detection   │         │  - MediaPipe        │
│  - centered+stable  │         │  - pinch detector   │
│    state machine    │         │  - debounce N=5     │
└──────────┬──────────┘         └──────────┬──────────┘
           │                               │
           │ device_entered_view           │ pinch_detected
           │ device_left_view              │
           ▼                               ▼
           ─────────── Redis "events" ─────────────
                            │
                            ▼
           ┌────────────────────────────────────┐
           │  gesture_correlator.py             │
           │  - holds currently-in-view set     │
           │  - on pinch: pick largest bbox     │
           │  - cooldown 1500ms                 │
           └─────────────────┬──────────────────┘
                             │
                             │ gesture_command
                             ▼
           ─────────── Redis "events" ─────────────
                            │
                            ▼
                   ┌─────────────────┐
                   │  agent          │
                   │  main_loop.py   │
                   └────────┬────────┘
                            │
                            ▼
                   tools/home_assistant.py
                            │
                            ▼
                       HA REST API
```
 
### Why a correlator pipeline (not the agent)
Correlation is a millisecond-level signal-processing job. The agent reasons about intent, not timing windows. Keeping correlation in a pipeline makes it testable in isolation and keeps agent latency budget free for actual reasoning.
 
---
 
## 5. Event contracts (new event types)
 
All flow through the existing single `"events"` channel. Schema is the existing `Event(type, timestamp, source, payload)`.
 
### `device_entered_view`
Published by `pov_pipeline` when a device has been centered and above confidence threshold for `STABILITY_FRAMES_ENTER` consecutive frames.
```python
{
  "type": "device_entered_view",
  "source": "pov_pipeline",
  "payload": {
    "device_id": "light.bedroom_lamp",   # HA entity_id, looked up from registry
    "friendly_name": "bedroom lamp",
    "bbox": [x, y, w, h],
    "confidence": 0.87,
    "detected_via": "yolo" | "aruco"
  }
}
```
 
### `device_left_view`
Published when a previously-in-view device drops below threshold for `STABILITY_FRAMES_LEAVE` consecutive frames.
```python
{
  "type": "device_left_view",
  "source": "pov_pipeline",
  "payload": { "device_id": "light.bedroom_lamp" }
}
```
 
### `pinch_detected`
Published by `hand_pipeline` when a pinch fires (open → closed → held for `PINCH_HOLD_FRAMES`).
```python
{
  "type": "pinch_detected",
  "source": "hand_pipeline",
  "payload": {
    "confidence": 0.94,
    "hand": "right" | "left"
  }
}
```
 
### `gesture_command`
Published by `gesture_correlator` when a pinch fires while at least one device is in view. **This is the only gesture event the agent reads.**
```python
{
  "type": "gesture_command",
  "source": "gesture_correlator",
  "payload": {
    "device_id": "light.bedroom_lamp",
    "friendly_name": "bedroom lamp",
    "gesture": "pinch",
    "implied_intent": "toggle"
  }
}
```
 
The other three events are internal to the gesture subsystem but still go on the bus so `scripts/monitor_bus.py` can observe them during dev.
 
---
 
## 6. File-level plan
 
### New files
```
pipelines/
├── __init__.py
├── camera_source.py         # CameraSource abstract base + MacWebcam, (later) XiaoStream
├── pov_pipeline.py          # YOLO detection loop, state machine, publishes device_entered/left_view
├── hand_pipeline.py         # MediaPipe pinch detection, publishes pinch_detected
└── gesture_correlator.py    # subscribes both, publishes gesture_command
 
config/
└── devices.yaml             # device registry — see §7
 
scripts/
└── list_cameras.py          # dev util — enumerate USB webcams + preview to identify indices
```
 
### Modified files
```
agent/main_loop.py           # add handler for gesture_command event type
tools/home_assistant.py      # confirm it already accepts arbitrary entity_id (should from earlier work)
config/settings.py           # add gesture-related env vars (see §9)
pyproject.toml               # add dependencies (see §10)
```
 
### Untouched
```
bus/, events/, agent/gary_agent.py, laptop_app/, memory/, tests/
```
 
---
 
## 7. Device registry (`config/devices.yaml`)
 
Single source of truth. The HA tool reads `ha_entity_id` + `friendly_name`. The POV pipeline reads `vision` block to know what to look for.
 
```yaml
devices:
  - ha_entity_id: light.bedroom_lamp
    friendly_name: bedroom lamp
    area: bedroom
    vision:
      method: aruco          # aruco | yolo
      aruco_id: 3            # used if method == aruco
      yolo_class: null       # used if method == yolo (e.g. "tv")
 
  - ha_entity_id: media_player.living_room_tv
    friendly_name: living room TV
    area: living_room
    vision:
      method: yolo
      yolo_class: tv         # COCO class
      aruco_id: null
```
 
---
 
## 8. Camera source abstraction
 
`pipelines/camera_source.py` defines:
 
```python
class CameraSource(Protocol):
    async def frames() -> AsyncIterator[np.ndarray]: ...
    async def close() -> None: ...
```
 
Implementations:
- `MacWebcam(device_index: int)` — `cv2.VideoCapture` wrapped with `asyncio.to_thread`. For Mac dev. Both POV and hand cameras use this (two USB webcams on the Mac mini).
- `XiaoStream(host: str)` — placeholder, implement when XIAO firmware is ready. Same `CameraSource` interface, swap in via config.
Pipelines depend on `CameraSource`, not concrete classes. Source choice is config-driven.
 
**Dev note on USB webcam indices:** macOS does not guarantee that `device_index=0` is the camera you expect. When both webcams are plugged in, indices can shuffle on reboot or replug. Include a small diagnostic script (`scripts/list_cameras.py`) that opens indices 0–4, grabs one frame from each, and shows them so the user can identify which is which. The two correct indices then go into `.env`.
 
---
 
## 9. Configuration (added to `config/settings.py`)
 
```python
# camera sources
POV_CAMERA_SOURCE: str       # "mac:0" on dev (Mac mini USB webcam), "xiao:..." on Pi
HAND_CAMERA_SOURCE: str      # "mac:1" on dev, "xiao:..." on Pi
# (run `scripts/list_cameras.py` to identify which USB cam is which)
 
# detection
YOLO_MODEL: str = "yolov8n.pt"     # mac dev; on Pi, replace with Hailo-compiled equivalent
YOLO_CONFIDENCE_THRESHOLD: float = 0.5
CENTERED_REGION_FRACTION: float = 0.4   # device must be in middle 40% to count as "looking at"
 
# state machine timing (frames at ~30fps)
STABILITY_FRAMES_ENTER: int = 5
STABILITY_FRAMES_LEAVE: int = 10
PINCH_HOLD_FRAMES: int = 5
 
# correlator
GESTURE_COOLDOWN_MS: int = 1500
```
 
---
 
## 10. Dependencies (to add to `pyproject.toml`)
 
```
ultralytics            # YOLO. Pi build will swap to Hailo runtime later.
opencv-python          # camera + ArUco
mediapipe              # hand landmarks
pyyaml                 # device registry parsing
numpy                  # already likely present
```
 
---
 
## 11. Tuning knobs (defaults; all in settings)
 
| Knob | Default | Purpose |
|---|---|---|
| `STABILITY_FRAMES_ENTER` | 5 | Anti-jitter on device entering view |
| `STABILITY_FRAMES_LEAVE` | 10 | Hysteresis — slower to leave than enter, avoids flicker |
| `PINCH_HOLD_FRAMES` | 5 | Avoid false pinches from incidental finger contact |
| `CENTERED_REGION_FRACTION` | 0.4 | What counts as "looking at" — middle 40% of frame |
| `YOLO_CONFIDENCE_THRESHOLD` | 0.5 | Below this, detections discarded |
| `GESTURE_COOLDOWN_MS` | 1500 | After a successful command, ignore further pinches for this long |
 
---
 
## 12. Failure modes & handling
 
| Failure | Symptom | Mitigation |
|---|---|---|
| Two devices in view at once | Ambiguous target | Largest bbox wins. Publish only one `gesture_command`. |
| No devices in view at pinch | Pinch fires alone | Correlator drops it. No event published. |
| Held pinch (user doesn't release) | Repeated firing | `GESTURE_COOLDOWN_MS` after every fire. |
| Camera disconnects | Pipeline crashes | Each pipeline supervised: catches `CameraSource` exceptions, retries with backoff, publishes a `pipeline_error` event. |
| YOLO confuses the lamp with something else | Wrong device toggles | v1 mitigation: use ArUco for the lamp until YOLO is fine-tuned. |
| Bus disconnects | Pipelines silently stop working | Each pipeline reconnects to Redis with exponential backoff. |
| Pinch detected on the POV camera (not the hand camera) | False fires | Hand pipeline only reads from `HAND_CAMERA_SOURCE`. POV pipeline does not run MediaPipe. Hard separation. |
 
---
 
## 13. Agent integration (`agent/main_loop.py`)
 
The agent's bus subscriber currently dispatches on `event.type == "speech"`. Add:
 
```python
elif event.type == "gesture_command":
    # Treat as a synthetic instruction. Inject as a user-equivalent prompt.
    synthetic = f"[gesture] user pinched while looking at {event.payload['friendly_name']}. Toggle it."
    await agent.run(synthetic)
```
 
The agent will then call `control_device(entity_id=..., action="toggle")` via the LLM as it would for any other instruction. This preserves the "LLM in the loop" design from the project recap, at the cost of ~500ms of LLM latency. If that breaks the 300ms budget in practice, fallback path is documented in §15.
 
---
 
## 14. Testing approach
 
Each pipeline runnable standalone:
 
```bash
# Terminal 1
uv run python -m scripts.monitor_bus
 
# Terminal 2 — POV pipeline alone, prints what it sees
uv run python -m pipelines.pov_pipeline
 
# Terminal 3 — hand pipeline alone
uv run python -m pipelines.hand_pipeline
 
# Terminal 4 — correlator
uv run python -m pipelines.gesture_correlator
 
# Terminal 5 — agent
uv run python -m agent.main_loop
```
 
Manual test cases:
1. Show a known device to POV camera → see `device_entered_view` on monitor.
2. Move device out of frame → see `device_left_view`.
3. Pinch in front of hand camera → see `pinch_detected`.
4. Both at once → see `gesture_command` followed by HA API call.
5. Pinch without device in view → nothing happens.
6. Two devices in view, pinch → larger device toggles.
7. Hold pinch for 5 seconds → only one fire (cooldown works).
---
 
## 15. Out of scope / future work
 
- **Hailo migration.** Swap `ultralytics` for Hailo runtime + a compiled model. Camera sources swap to `XiaoStream`. Same pipeline code.
- **Fine-tuned YOLO for the smart bulb.** Removes the ArUco-on-bulb hack.
- **Direct-tool fastpath.** If 300ms latency budget is missed because of LLM, add a fastpath in `gesture_correlator` that calls `control_device` directly for known-safe gestures, and fires a `speak` event in parallel. Agent still observes the event for memory/context.
- **More gestures.** Pinch-and-hold for dimming, double-pinch for "off vs on" disambiguation, swipe for next/prev.
- **Gaze instead of frame-center.** Use IMU + eye proxy if/when we have it.
---
 
## 16. Acceptance criteria
 
This spec is satisfied when:
 
1. Pinching at a registered device toggles it via HA, end-to-end, on Mac dev.
2. Pinching with no device in view does nothing.
3. With two devices in view, the larger one toggles.
4. The same code runs on Pi with only `POV_CAMERA_SOURCE` / `HAND_CAMERA_SOURCE` / `YOLO_MODEL` changed in config.
5. `scripts/monitor_bus.py` shows the full event chain: `device_entered_view` → `pinch_detected` → `gesture_command` → `speak`.
6. No changes to `bus/`, `events/schema.py`, or `agent/gary_agent.py`.
---
 
## 17. Open questions
 
1. **MediaPipe pinch threshold** — what thumb-tip-to-index-tip distance (normalized) counts as a pinch? Needs empirical calibration with the actual hand camera placement. Pick a reasonable default (e.g., 0.04) and tune in dev.
2. **What does the agent say after a gesture command?** "Got it" is a placeholder. Could be silent (no speak event) for unobtrusiveness, or a soft confirmation chime instead of speech.
3. **What if the user pinches while looking at a device but the LLM decides not to toggle?** (E.g., device is already on, agent decides not to toggle.) Acceptable for v1 — the LLM's call.