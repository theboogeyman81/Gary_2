"""
Combined pipeline — runs POV (YOLO/ArUco) and hand (MediaPipe) detection
on a single camera. Use this when both POV_CAMERA_SOURCE and
HAND_CAMERA_SOURCE point to the same physical camera (single-webcam dev setup).

When you have two cameras, run pov_pipeline and hand_pipeline separately instead.

Run:
    uv run python -m pipelines.combined_pipeline

Set SHOW_CAMERA=true in .env to see a live annotated feed.
"""

import asyncio
import math
import time
import urllib.request
from enum import Enum, auto
from pathlib import Path

import cv2
import mediapipe as mp
import yaml
from ultralytics import YOLO

from bus.redis_bus import Bus
from config.settings import (
    CENTERED_REGION_FRACTION,
    HAND_CAMERA_SOURCE,
    PINCH_HOLD_FRAMES,
    PINCH_THRESHOLD,
    SHOW_CAMERA,
    STABILITY_FRAMES_ENTER,
    STABILITY_FRAMES_LEAVE,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL,
)
from events.schema import Event
from pipelines.camera_source import make_camera_source
from pipelines.pov_pipeline import (
    _ARUCO_DICT,
    _ARUCO_PARAMS,
    _DEVICES_YAML,
    _detect_aruco,
    _detect_yolo,
    _is_centered,
    _load_registry,
)

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)
_MODEL_PATH = Path(__file__).parent.parent / "hand_landmarker.task"

_THUMB_TIP = 4
_INDEX_TIP = 8


def _ensure_model() -> None:
    if _MODEL_PATH.exists():
        return
    print("[combined] Downloading hand_landmarker.task (~6 MB) ...")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"[combined] Model saved to {_MODEL_PATH}")


class _PinchState(Enum):
    OPEN = auto()
    HOLDING = auto()
    FIRED = auto()


async def run(bus: Bus, landmarker: mp.tasks.vision.HandLandmarker) -> None:
    # --- POV state ---
    aruco_devices, yolo_devices = _load_registry()
    yolo_model = await asyncio.to_thread(YOLO, YOLO_MODEL)
    print(f"[combined] YOLO model loaded: {YOLO_MODEL}")
    print(f"[combined] Registry: {len(aruco_devices)} ArUco, {len(yolo_devices)} YOLO devices")

    all_device_ids: set[str] = set()
    for d in aruco_devices.values():
        all_device_ids.add(d["ha_entity_id"])
    for d in yolo_devices.values():
        all_device_ids.add(d["ha_entity_id"])

    in_view: dict[str, bool] = {did: False for did in all_device_ids}
    enter_counters: dict[str, int] = {did: 0 for did in all_device_ids}
    leave_counters: dict[str, int] = {did: 0 for did in all_device_ids}

    # --- Hand state ---
    pinch_state = _PinchState.OPEN
    hold_counter = 0
    start_time = time.monotonic()
    backoff = 1.0

    cam = make_camera_source(HAND_CAMERA_SOURCE)
    try:
        async for frame in cam.frames():
            backoff = 1.0
            fh, fw = frame.shape[:2]

            # ── POV detection ──────────────────────────────────────────────
            all_detections = (
                _detect_aruco(frame, aruco_devices)
                + _detect_yolo(yolo_model, frame, yolo_devices)
            )
            centered: dict[str, tuple[dict, list, float, str]] = {}
            for device, bbox, conf, method in all_detections:
                did = device["ha_entity_id"]
                cx = bbox[0] + bbox[2] / 2
                cy = bbox[1] + bbox[3] / 2
                if _is_centered(cx, cy, fw, fh):
                    if did not in centered or conf > centered[did][2]:
                        centered[did] = (device, bbox, conf, method)

            for did in all_device_ids:
                if did in centered:
                    device, bbox, conf, method = centered[did]
                    leave_counters[did] = 0
                    if not in_view[did]:
                        enter_counters[did] += 1
                        if enter_counters[did] >= STABILITY_FRAMES_ENTER:
                            in_view[did] = True
                            enter_counters[did] = 0
                            await bus.publish(Event(
                                type="device_entered_view",
                                source="pov_pipeline",
                                payload={
                                    "device_id": did,
                                    "friendly_name": device["friendly_name"],
                                    "bbox": bbox,
                                    "confidence": round(conf, 3),
                                    "detected_via": method,
                                },
                            ))
                            print(f"[combined] device_entered_view: {device['friendly_name']}")
                else:
                    enter_counters[did] = 0
                    if in_view[did]:
                        leave_counters[did] += 1
                        if leave_counters[did] >= STABILITY_FRAMES_LEAVE:
                            in_view[did] = False
                            leave_counters[did] = 0
                            await bus.publish(Event(
                                type="device_left_view",
                                source="pov_pipeline",
                                payload={"device_id": did},
                            ))
                            print(f"[combined] device_left_view: {did}")

            # ── Hand detection ─────────────────────────────────────────────
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

            if dist is None:
                if pinch_state in (_PinchState.HOLDING, _PinchState.FIRED):
                    pinch_state = _PinchState.OPEN
                    hold_counter = 0
            elif pinch_state == _PinchState.OPEN:
                if dist <= PINCH_THRESHOLD:
                    pinch_state = _PinchState.HOLDING
                    hold_counter = 1
                    print(f"[combined] Pinch started (dist={dist:.3f})")
            elif pinch_state == _PinchState.HOLDING:
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
                        print(f"[combined] pinch_detected ({hand_label}, conf={confidence:.2f})")
                        pinch_state = _PinchState.FIRED
                else:
                    pinch_state = _PinchState.OPEN
                    hold_counter = 0
            elif pinch_state == _PinchState.FIRED:
                if dist > PINCH_THRESHOLD:
                    pinch_state = _PinchState.OPEN
                    hold_counter = 0
                    print("[combined] Pinch released — re-armed")

            # ── Display ────────────────────────────────────────────────────
            if SHOW_CAMERA:
                display = frame.copy()
                # Centered region
                mx = int(fw * (1 - CENTERED_REGION_FRACTION) / 2)
                my = int(fh * (1 - CENTERED_REGION_FRACTION) / 2)
                cv2.rectangle(display, (mx, my), (fw - mx, fh - my), (80, 80, 80), 1)
                # Device bboxes
                for device, bbox, conf, method in all_detections:
                    did = device["ha_entity_id"]
                    x, y, w, h = bbox
                    color = (0, 220, 0) if in_view[did] else (0, 140, 255)
                    cv2.rectangle(display, (x, y), (x + w, y + h), color, 2)
                    frames_label = f"+{enter_counters[did]}" if not in_view[did] else "IN VIEW"
                    label = f"{device['friendly_name']} {conf:.2f} [{method}] {frames_label}"
                    cv2.putText(display, label, (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                # Hand landmarks
                if result.hand_landmarks:
                    lm = result.hand_landmarks[0]
                    tx = int(lm[_THUMB_TIP].x * fw)
                    ty = int(lm[_THUMB_TIP].y * fh)
                    ix = int(lm[_INDEX_TIP].x * fw)
                    iy = int(lm[_INDEX_TIP].y * fh)
                    line_color = (0, 255, 0) if pinch_state == _PinchState.OPEN else (0, 165, 255) if pinch_state == _PinchState.HOLDING else (0, 0, 255)
                    cv2.circle(display, (tx, ty), 10, (0, 255, 0), -1)
                    cv2.circle(display, (ix, iy), 10, (0, 0, 255), -1)
                    cv2.line(display, (tx, ty), (ix, iy), line_color, 2)
                    cv2.putText(display, f"{pinch_state.name} d={dist:.3f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, line_color, 2)
                else:
                    cv2.putText(display, "no hand", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 2)
                cv2.imshow("combined pipeline", display)
                cv2.waitKey(1)

    except Exception as exc:
        print(f"[combined] Camera error: {exc}. Retrying in {backoff:.0f}s ...")
        await bus.publish(Event(
            type="pipeline_error",
            source="combined_pipeline",
            payload={"error": str(exc)},
        ))
        await cam.close()
        if SHOW_CAMERA:
            cv2.destroyWindow("combined pipeline")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


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
    print("[combined] Loading hand landmarker (CPU) ...")
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        print("[combined] Landmarker ready")
        bus = Bus()
        backoff = 1.0
        while True:
            try:
                await bus.connect()
                print(f"[combined] Connected — camera: {HAND_CAMERA_SOURCE}")
                await run(bus, landmarker)
            except Exception as exc:
                print(f"[combined] Bus error: {exc}. Reconnecting in {backoff:.0f}s ...")
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
