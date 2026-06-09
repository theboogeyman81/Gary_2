"""
Hand pipeline — detects pinch gestures via MediaPipe.

Reads frames from HAND_CAMERA_SOURCE, runs MediaPipe Hands, and publishes
a `pinch_detected` event when the user holds a pinch for PINCH_HOLD_FRAMES
consecutive frames.

State machine:
  OPEN   — no pinch
  HOLDING — pinch distance below threshold, counting frames
  FIRED  — event published, waiting for release before re-arm

Run standalone:
    uv run python -m pipelines.hand_pipeline
"""

import asyncio
import math
import time
from enum import Enum, auto

import mediapipe as mp

from bus.redis_bus import Bus
from config.settings import (
    HAND_CAMERA_SOURCE,
    PINCH_HOLD_FRAMES,
    PINCH_THRESHOLD,
)
from events.schema import Event
from pipelines.camera_source import make_camera_source


# MediaPipe landmark indices for pinch
_THUMB_TIP = 4
_INDEX_TIP = 8


class _State(Enum):
    OPEN = auto()
    HOLDING = auto()
    FIRED = auto()


async def run(bus: Bus) -> None:
    hands = mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    )

    state = _State.OPEN
    hold_counter = 0
    backoff = 1.0

    while True:
        cam = make_camera_source(HAND_CAMERA_SOURCE)
        try:
            async for frame in cam.frames():
                backoff = 1.0  # reset on successful frame
                import cv2
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = hands.process(rgb)

                if not result.multi_hand_landmarks:
                    if state == _State.HOLDING:
                        state = _State.OPEN
                        hold_counter = 0
                    elif state == _State.FIRED:
                        state = _State.OPEN
                    continue

                lm = result.multi_hand_landmarks[0].landmark
                dist = math.hypot(
                    lm[_THUMB_TIP].x - lm[_INDEX_TIP].x,
                    lm[_THUMB_TIP].y - lm[_INDEX_TIP].y,
                )

                # Determine handedness label
                hand_label = "right"
                if result.multi_handedness:
                    hand_label = result.multi_handedness[0].classification[0].label.lower()

                if state == _State.OPEN:
                    if dist <= PINCH_THRESHOLD:
                        state = _State.HOLDING
                        hold_counter = 1
                        print(f"[hand_pipeline] Pinch started (dist={dist:.3f})")

                elif state == _State.HOLDING:
                    if dist <= PINCH_THRESHOLD:
                        hold_counter += 1
                        if hold_counter >= PINCH_HOLD_FRAMES:
                            confidence = result.multi_handedness[0].classification[0].score if result.multi_handedness else 0.0
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
                        # Released before holding long enough
                        state = _State.OPEN
                        hold_counter = 0

                elif state == _State.FIRED:
                    if dist > PINCH_THRESHOLD:
                        state = _State.OPEN
                        hold_counter = 0
                        print("[hand_pipeline] Pinch released — re-armed")

        except Exception as exc:
            print(f"[hand_pipeline] Camera error: {exc}. Retrying in {backoff:.0f}s ...")
            await bus.publish(Event(
                type="pipeline_error",
                source="hand_pipeline",
                payload={"error": str(exc)},
            ))
            await cam.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def main() -> None:
    bus = Bus()

    # Reconnect loop for Redis
    backoff = 1.0
    while True:
        try:
            await bus.connect()
            print(f"[hand_pipeline] Connected — reading from {HAND_CAMERA_SOURCE}")
            await run(bus)
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
        pass
