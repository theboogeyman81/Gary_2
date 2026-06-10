"""
Hand pipeline — detects pinch gestures via MediaPipe Hand Landmarker (Tasks API).

Reads frames from HAND_CAMERA_SOURCE, runs MediaPipe, and publishes a
`pinch_detected` event when the user holds a pinch for PINCH_HOLD_FRAMES
consecutive frames.

On first run, downloads the hand_landmarker.task model (~6 MB) automatically.

State machine:
  OPEN    — no pinch
  HOLDING — pinch distance below threshold, counting frames
  FIRED   — event published, waiting for release before re-arm

Run standalone:
    uv run python -m pipelines.hand_pipeline

Set SHOW_CAMERA=true in .env to see the live camera feed with landmarks.
"""

import asyncio
import math
import time
import urllib.request
from enum import Enum, auto
from pathlib import Path

import cv2
import mediapipe as mp

from bus.redis_bus import Bus
from config.settings import (
    HAND_CAMERA_SOURCE,
    PINCH_HOLD_FRAMES,
    PINCH_THRESHOLD,
    SHOW_CAMERA,
)
from events.schema import Event
from pipelines.camera_source import make_camera_source

_THUMB_TIP = 4
_INDEX_TIP = 8

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)
_MODEL_PATH = Path(__file__).parent.parent / "hand_landmarker.task"


def _ensure_model() -> None:
    if _MODEL_PATH.exists():
        return
    print("[hand_pipeline] Downloading hand_landmarker.task model (~6 MB) ...")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"[hand_pipeline] Model saved to {_MODEL_PATH}")


class _State(Enum):
    OPEN = auto()
    HOLDING = auto()
    FIRED = auto()


async def run(bus: Bus, landmarker: mp.tasks.vision.HandLandmarker) -> None:
    state = _State.OPEN
    hold_counter = 0
    backoff = 1.0
    start_time = time.monotonic()

    cam = make_camera_source(HAND_CAMERA_SOURCE)
    try:
        async for frame in cam.frames():
            backoff = 1.0
            timestamp_ms = int((time.monotonic() - start_time) * 1000)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            dist: float | None = None
            hand_label = "right"
            confidence = 0.0

            if result.hand_landmarks:
                lm = result.hand_landmarks[0]
                dist = math.hypot(
                    lm[_THUMB_TIP].x - lm[_INDEX_TIP].x,
                    lm[_THUMB_TIP].y - lm[_INDEX_TIP].y,
                )
                if result.handedness:
                    hand_label = result.handedness[0][0].display_name.lower()
                    confidence = result.handedness[0][0].score

            # State machine
            if dist is None:
                if state in (_State.HOLDING, _State.FIRED):
                    state = _State.OPEN
                    hold_counter = 0
            elif state == _State.OPEN:
                if dist <= PINCH_THRESHOLD:
                    state = _State.HOLDING
                    hold_counter = 1
                    print(f"[hand_pipeline] Pinch started (dist={dist:.3f})")
            elif state == _State.HOLDING:
                if dist <= PINCH_THRESHOLD:
                    hold_counter += 1
                    if hold_counter >= PINCH_HOLD_FRAMES:
                        await bus.publish(Event(
                            type="pinch_detected",
                            source="hand_pipeline",
                            payload={
                                "confidence": round(float(confidence), 3),
                                "hand": hand_label,
                            },
                        ))
                        print(f"[hand_pipeline] pinch_detected ({hand_label}, conf={confidence:.2f})")
                        state = _State.FIRED
                else:
                    state = _State.OPEN
                    hold_counter = 0
            elif state == _State.FIRED:
                if dist > PINCH_THRESHOLD:
                    state = _State.OPEN
                    hold_counter = 0
                    print("[hand_pipeline] Pinch released — re-armed")

            if SHOW_CAMERA:
                display = frame.copy()
                h, w = display.shape[:2]
                if result.hand_landmarks:
                    lm = result.hand_landmarks[0]
                    tx = int(lm[_THUMB_TIP].x * w)
                    ty = int(lm[_THUMB_TIP].y * h)
                    ix = int(lm[_INDEX_TIP].x * w)
                    iy = int(lm[_INDEX_TIP].y * h)
                    color = (0, 255, 0) if state == _State.OPEN else (0, 165, 255) if state == _State.HOLDING else (0, 0, 255)
                    cv2.circle(display, (tx, ty), 10, (0, 255, 0), -1)
                    cv2.circle(display, (ix, iy), 10, (0, 0, 255), -1)
                    cv2.line(display, (tx, ty), (ix, iy), color, 2)
                    label = f"{state.name}  dist={dist:.3f}  thr={PINCH_THRESHOLD}"
                    cv2.putText(display, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                else:
                    cv2.putText(display, "no hand", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 2)
                cv2.imshow("hand pipeline", display)
                cv2.waitKey(1)

    except Exception as exc:
        print(f"[hand_pipeline] Camera error: {exc}. Retrying in {backoff:.0f}s ...")
        await bus.publish(Event(
            type="pipeline_error",
            source="hand_pipeline",
            payload={"error": str(exc)},
        ))
        await cam.close()
        if SHOW_CAMERA:
            cv2.destroyWindow("hand pipeline")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


async def main() -> None:
    # Ensure model downloaded and landmarker initialized before touching the camera.
    _ensure_model()
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(_MODEL_PATH),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    print("[hand_pipeline] Loading hand landmarker (CPU) ...")
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        print("[hand_pipeline] Landmarker ready")
        bus = Bus()
        backoff = 1.0
        while True:
            try:
                await bus.connect()
                print(f"[hand_pipeline] Connected — reading from {HAND_CAMERA_SOURCE}")
                await run(bus, landmarker)
            except Exception as exc:
                print(f"[hand_pipeline] Bus error: {exc}. Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                await bus.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if SHOW_CAMERA:
            cv2.destroyAllWindows()
