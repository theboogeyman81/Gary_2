"""
Hand pipeline — detects pinch gestures via MediaPipe Hand Landmarker (Tasks API).

Reads frames from HAND_CAMERA_SOURCE, runs MediaPipe with all 21 landmarks,
and publishes a `pinch_detected` event when the user holds a pinch for
PINCH_HOLD_DURATION seconds.

On first run, downloads the hand_landmarker.task model (~6 MB) automatically.

State machine:
  OPEN            — no pinch
  HOLDING         — pinch distance below threshold, counting time
  WAITING_RELEASE — event published, waiting for release before re-arm

Run standalone:
    uv run python -m pipelines.hand_pipeline

Set SHOW_CAMERA=true in .env to see the live camera feed with all landmarks.
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
    PINCH_ENTER_THRESHOLD,
    PINCH_EXIT_THRESHOLD,
    PINCH_HOLD_DURATION,
    SHOW_CAMERA,
)
from events.schema import Event
from pipelines.camera_source import make_camera_source

_THUMB_TIP = 4
_INDEX_MCP = 5
_INDEX_TIP = 8
_WRIST = 0
_MIDDLE_MCP = 9
_EMA_ALPHA = 0.3

_SLIDE_PROXIMITY = 0.35    # max perp distance as fraction of finger length
_SLIDE_START_MIN_T = 0.55  # thumb must start in upper half of finger (near tip = t=1)
_SLIDE_MIN_TRAVEL = 0.30   # must slide at least 30% of finger length to fire

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)
_MODEL_PATH = Path(__file__).parent.parent / "hand_landmarker.task"

# All 21-landmark connections for drawing the full hand skeleton
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),           # index
    (0, 9), (9, 10), (10, 11), (11, 12),      # middle
    (0, 13), (13, 14), (14, 15), (15, 16),    # ring
    (0, 17), (17, 18), (18, 19), (19, 20),    # pinky
    (5, 9), (9, 13), (13, 17),                # palm
]


def _ensure_model() -> None:
    if _MODEL_PATH.exists():
        return
    print("[hand_pipeline] Downloading hand_landmarker.task model (~6 MB) ...")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"[hand_pipeline] Model saved to {_MODEL_PATH}")


def _project_thumb_on_index(lm):
    """Project thumb tip onto the MCP→TIP index finger axis.
    Returns (t, perp_norm): t=0 at base, t=1 at tip;
    perp_norm is off-axis distance as a fraction of finger length (scale-invariant).
    """
    mcp = lm[_INDEX_MCP]
    tip = lm[_INDEX_TIP]
    thumb = lm[_THUMB_TIP]
    dx = tip.x - mcp.x
    dy = tip.y - mcp.y
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-6:
        return 0.0, float("inf")
    finger_len = math.sqrt(len_sq)
    t = ((thumb.x - mcp.x) * dx + (thumb.y - mcp.y) * dy) / len_sq
    proj_x = mcp.x + t * dx
    proj_y = mcp.y + t * dy
    perp_abs = math.hypot(thumb.x - proj_x, thumb.y - proj_y)
    return t, perp_abs / finger_len  # normalized by finger length


def _hand_size(lm) -> float:
    return math.hypot(lm[_WRIST].x - lm[_MIDDLE_MCP].x,
                      lm[_WRIST].y - lm[_MIDDLE_MCP].y)


def _pinch_dist_normalized(lm) -> float:
    size = _hand_size(lm)
    raw = math.hypot(lm[_THUMB_TIP].x - lm[_INDEX_TIP].x,
                     lm[_THUMB_TIP].y - lm[_INDEX_TIP].y)
    return raw / size if size > 0 else raw


class _State(Enum):
    OPEN = auto()
    HOLDING = auto()
    WAITING_RELEASE = auto()


class _SlideState(Enum):
    IDLE = auto()
    TRACKING = auto()
    FIRED = auto()


async def run(bus: Bus, landmarker: mp.tasks.vision.HandLandmarker) -> None:
    state = _State.OPEN
    pinch_start: float | None = None
    ema_dist: float | None = None
    loop_start = time.monotonic()
    _window_placed = False
    slide_state = _SlideState.IDLE
    slide_start_t = 0.0
    slide_min_t = 1.0

    cam = make_camera_source(HAND_CAMERA_SOURCE)
    try:
        async for frame in cam.frames():
            now = time.monotonic()
            timestamp_ms = int((now - loop_start) * 1000)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            dist: float | None = None
            hand_label = "right"
            confidence = 0.0

            if result.hand_landmarks:
                lm = result.hand_landmarks[0]
                dist = _pinch_dist_normalized(lm)
                if result.handedness:
                    hand_label = result.handedness[0][0].display_name.lower()
                    confidence = result.handedness[0][0].score

            # EMA smoothing
            if dist is None:
                ema_dist = None
            elif ema_dist is None:
                ema_dist = dist
            else:
                ema_dist = _EMA_ALPHA * dist + (1 - _EMA_ALPHA) * ema_dist

            # State machine — time-based hold, hysteresis thresholds
            if ema_dist is None:
                state = _State.OPEN
                pinch_start = None
            elif state == _State.OPEN:
                if ema_dist <= PINCH_ENTER_THRESHOLD:
                    state = _State.HOLDING
                    pinch_start = now
                    print(f"[hand_pipeline] Pinch started (ema={ema_dist:.3f})")
            elif state == _State.HOLDING:
                if ema_dist > PINCH_EXIT_THRESHOLD:
                    state = _State.OPEN
                    pinch_start = None
                elif now - pinch_start >= PINCH_HOLD_DURATION:
                    await bus.publish(Event(
                        type="pinch_detected",
                        source="hand_pipeline",
                        payload={"confidence": round(float(confidence), 3), "hand": hand_label},
                    ))
                    print(f"[hand_pipeline] pinch_detected ({hand_label}, conf={confidence:.2f})")
                    state = _State.WAITING_RELEASE
            elif state == _State.WAITING_RELEASE:
                if ema_dist > PINCH_EXIT_THRESHOLD:
                    state = _State.OPEN
                    pinch_start = None
                    print("[hand_pipeline] Pinch released — re-armed")

            # --- Slide gesture: thumb down the index finger ---
            if result.hand_landmarks:
                lm = result.hand_landmarks[0]
                t, perp = _project_thumb_on_index(lm)
                print(f"[slide] t={t:.2f} perp={perp:.2f} state={slide_state.name}")
                if perp < _SLIDE_PROXIMITY and -0.1 <= t <= 1.3:
                    if slide_state == _SlideState.IDLE:
                        if t >= _SLIDE_START_MIN_T:
                            slide_state = _SlideState.TRACKING
                            slide_start_t = t
                            slide_min_t = t
                            print(f"[slide] TRACKING started at t={t:.2f}")
                    elif slide_state == _SlideState.TRACKING:
                        slide_min_t = min(slide_min_t, t)
                        travel = slide_start_t - slide_min_t
                        print(f"[slide] travel={travel:.2f} (need {_SLIDE_MIN_TRAVEL})")
                        if travel >= _SLIDE_MIN_TRAVEL:
                            await bus.publish(Event(
                                type="slide_detected",
                                source="hand_pipeline",
                                payload={"confidence": round(float(confidence), 3), "hand": hand_label},
                            ))
                            print(f"[hand_pipeline] slide_detected ({hand_label})")
                            slide_state = _SlideState.FIRED
                else:
                    if slide_state != _SlideState.IDLE:
                        print(f"[slide] reset (perp={perp:.2f} t={t:.2f})")
                    slide_state = _SlideState.IDLE
                    slide_start_t = 0.0
                    slide_min_t = 1.0
            else:
                slide_state = _SlideState.IDLE
                slide_start_t = 0.0
                slide_min_t = 1.0

            if SHOW_CAMERA:
                display = frame.copy()
                h, w = display.shape[:2]
                state_colors = {
                    _State.OPEN: (200, 200, 200),
                    _State.HOLDING: (0, 200, 255),
                    _State.WAITING_RELEASE: (0, 0, 255),
                }
                color = state_colors[state]
                if result.hand_landmarks:
                    lm = result.hand_landmarks[0]
                    # Draw full hand skeleton — all 21 landmarks
                    for start_idx, end_idx in _HAND_CONNECTIONS:
                        sx = int(lm[start_idx].x * w)
                        sy = int(lm[start_idx].y * h)
                        ex = int(lm[end_idx].x * w)
                        ey = int(lm[end_idx].y * h)
                        cv2.line(display, (sx, sy), (ex, ey), (0, 180, 0), 1)
                    for landmark in lm:
                        cx = int(landmark.x * w)
                        cy = int(landmark.y * h)
                        cv2.circle(display, (cx, cy), 4, (0, 255, 0), -1)
                    # Highlight pinch fingers
                    tx, ty = int(lm[_THUMB_TIP].x * w), int(lm[_THUMB_TIP].y * h)
                    ix, iy = int(lm[_INDEX_TIP].x * w), int(lm[_INDEX_TIP].y * h)
                    cv2.circle(display, (tx, ty), 8, (0, 80, 255), -1)
                    cv2.circle(display, (ix, iy), 8, (255, 80, 0), -1)
                    cv2.line(display, (tx, ty), (ix, iy), color, 2)
                    cv2.putText(display, f"{state.name} d={ema_dist:.3f}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    if state == _State.HOLDING and pinch_start is not None:
                        progress = min((now - pinch_start) / PINCH_HOLD_DURATION, 1.0)
                        bar_x, bar_y, bar_w, bar_h = 10, h - 40, 300, 20
                        cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), -1)
                        filled = int(bar_w * progress)
                        bar_color = (0, 255, 0) if progress >= 1.0 else (0, 200, 255)
                        cv2.rectangle(display, (bar_x, bar_y), (bar_x + filled, bar_y + bar_h), bar_color, -1)
                        cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (255, 255, 255), 1)
                        cv2.putText(display, f"{int(progress * 100)}%", (bar_x + bar_w + 8, bar_y + 15),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                else:
                    cv2.putText(display, "no hand", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 2)
                cv2.imshow("hand pipeline", display)
                if not _window_placed:
                    cv2.moveWindow("hand pipeline", 0, 0)
                    _window_placed = True
                cv2.waitKey(1)

    except Exception as exc:
        print(f"[hand_pipeline] Camera error: {exc}")
        await bus.publish(Event(
            type="pipeline_error",
            source="hand_pipeline",
            payload={"error": str(exc)},
        ))
        raise
    finally:
        await cam.close()
        if SHOW_CAMERA:
            cv2.destroyWindow("hand pipeline")


async def main() -> None:
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
                print(f"[hand_pipeline] Error: {exc}. Retrying in {backoff:.0f}s ...")
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
