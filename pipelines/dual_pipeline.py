"""
Dual-camera pipeline — POV (YOLO/ArUco) on camera 0, hand (MediaPipe) on camera 1,
both running in a single process so macOS does not block concurrent camera access.

macOS AVFoundation refuses to give frames to a second *process* while another
process holds a camera. Running both in one process avoids this entirely.

Run:
    uv run python -m pipelines.dual_pipeline

Use combined_pipeline instead if you only have one physical camera.
"""

import asyncio
import math
import time
import urllib.request
from enum import Enum, auto
from pathlib import Path

import cv2
import mediapipe as mp
from ultralytics import YOLO

from bus.redis_bus import Bus
from config.settings import (
    CENTERED_REGION_FRACTION,
    HAND_CAMERA_SOURCE,
    PINCH_HOLD_FRAMES,
    PINCH_THRESHOLD,
    POV_CAMERA_SOURCE,
    SHOW_CAMERA,
    STABILITY_FRAMES_ENTER,
    STABILITY_FRAMES_LEAVE,
    YOLO_MODEL,
)
from events.schema import Event
from pipelines.camera_source import CameraSource, make_camera_source
from pipelines.pov_pipeline import (
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
    print("[dual] Downloading hand_landmarker.task (~6 MB) ...")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"[dual] Model saved to {_MODEL_PATH}")


class _PinchState(Enum):
    OPEN = auto()
    HOLDING = auto()
    FIRED = auto()


async def _run_pov(bus: Bus, model: YOLO, cam: CameraSource) -> None:
    aruco_devices, yolo_devices = _load_registry()
    print(f"[dual/pov] Registry: {len(aruco_devices)} ArUco, {len(yolo_devices)} YOLO devices")

    all_device_ids = (
        {d["ha_entity_id"] for d in aruco_devices.values()}
        | {d["ha_entity_id"] for d in yolo_devices.values()}
    )
    in_view: dict[str, bool] = {did: False for did in all_device_ids}
    enter_counters: dict[str, int] = {did: 0 for did in all_device_ids}
    leave_counters: dict[str, int] = {did: 0 for did in all_device_ids}

    # Drain camera 0 at full 30 fps in a background task so the AVFoundation session
    # stays active even when YOLO is slow (3 fps on CPU). YOLO picks up the latest frame.
    latest: list = [None]

    async def _drain() -> None:
        async for frame in cam.frames():
            latest[0] = frame

    drain_task = asyncio.create_task(_drain())
    try:
        while True:
            while latest[0] is None:
                await asyncio.sleep(0.01)
            frame = latest[0]
            latest[0] = None

            fh, fw = frame.shape[:2]
            all_detections = await asyncio.to_thread(
                lambda f=frame: _detect_aruco(f, aruco_devices) + _detect_yolo(model, f, yolo_devices)
            )

            centered: dict[str, tuple] = {}
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
                            print(f"[dual/pov] device_entered_view: {device['friendly_name']}")
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
                            print(f"[dual/pov] device_left_view: {did}")

            if SHOW_CAMERA:
                display = frame.copy()
                mx = int(fw * (1 - CENTERED_REGION_FRACTION) / 2)
                my = int(fh * (1 - CENTERED_REGION_FRACTION) / 2)
                cv2.rectangle(display, (mx, my), (fw - mx, fh - my), (80, 80, 80), 1)
                for device, bbox, conf, method in all_detections:
                    did = device["ha_entity_id"]
                    x, y, w, h = bbox
                    color = (0, 220, 0) if in_view[did] else (0, 140, 255)
                    cv2.rectangle(display, (x, y), (x + w, y + h), color, 2)
                    tag = "IN VIEW" if in_view[did] else f"+{enter_counters[did]}"
                    cv2.putText(display, f"{device['friendly_name']} {conf:.2f} [{method}] {tag}",
                                (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                cv2.imshow("pov camera", display)
                cv2.waitKey(1)
    finally:
        drain_task.cancel()


async def _run_hand(
    bus: Bus, landmarker: mp.tasks.vision.HandLandmarker, cam: CameraSource
) -> None:
    state = _PinchState.OPEN
    hold_counter = 0
    start_time = time.monotonic()

    async for frame in cam.frames():
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
            if state in (_PinchState.HOLDING, _PinchState.FIRED):
                state = _PinchState.OPEN
                hold_counter = 0
        elif state == _PinchState.OPEN:
            if dist <= PINCH_THRESHOLD:
                state = _PinchState.HOLDING
                hold_counter = 1
                print(f"[dual/hand] Pinch started (dist={dist:.3f})")
        elif state == _PinchState.HOLDING:
            if dist <= PINCH_THRESHOLD:
                hold_counter += 1
                if hold_counter >= PINCH_HOLD_FRAMES:
                    await bus.publish(Event(
                        type="pinch_detected",
                        source="hand_pipeline",
                        payload={"confidence": round(float(confidence), 3), "hand": hand_label},
                    ))
                    print(f"[dual/hand] pinch_detected ({hand_label}, conf={confidence:.2f})")
                    state = _PinchState.FIRED
            else:
                state = _PinchState.OPEN
                hold_counter = 0
        elif state == _PinchState.FIRED:
            if dist > PINCH_THRESHOLD:
                state = _PinchState.OPEN
                hold_counter = 0
                print("[dual/hand] Pinch released — re-armed")

        if SHOW_CAMERA:
            display = frame.copy()
            h, w = display.shape[:2]
            if result.hand_landmarks:
                lm = result.hand_landmarks[0]
                tx, ty = int(lm[_THUMB_TIP].x * w), int(lm[_THUMB_TIP].y * h)
                ix, iy = int(lm[_INDEX_TIP].x * w), int(lm[_INDEX_TIP].y * h)
                color = (
                    (0, 255, 0) if state == _PinchState.OPEN
                    else (0, 165, 255) if state == _PinchState.HOLDING
                    else (0, 0, 255)
                )
                cv2.circle(display, (tx, ty), 10, (0, 255, 0), -1)
                cv2.circle(display, (ix, iy), 10, (0, 0, 255), -1)
                cv2.line(display, (tx, ty), (ix, iy), color, 2)
                cv2.putText(display, f"{state.name} d={dist:.3f}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            else:
                cv2.putText(display, "no hand", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 2)
            cv2.imshow("hand camera", display)
            cv2.waitKey(1)


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
    print("[dual] Loading hand landmarker (CPU) ...")
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        print("[dual] Landmarker ready")
        bus = Bus()
        backoff = 1.0
        while True:
            cam_pov = cam_hand = None
            try:
                await bus.connect()
                print("[dual] Bus connected")

                # Load YOLO before opening cameras so cameras don't sit idle.
                model = await asyncio.to_thread(YOLO, YOLO_MODEL)
                # Force CPU inference — YOLO MPS conflicts with AVFoundation on M2.
                await asyncio.to_thread(model.to, "cpu")
                print(f"[dual] YOLO loaded: {YOLO_MODEL} (CPU inference)")

                # Open both cameras concurrently so they warm up at the same time.
                # Sequential open causes camera 1 to stale while camera 0 finishes.
                print(f"[dual] Opening cameras ({POV_CAMERA_SOURCE}, {HAND_CAMERA_SOURCE}) ...")
                cam_pov = make_camera_source(POV_CAMERA_SOURCE)
                cam_hand = make_camera_source(HAND_CAMERA_SOURCE)
                await asyncio.gather(cam_pov.open(), cam_hand.open())
                print("[dual] Both cameras ready")
                print("[dual] Running — POV + hand loops active")

                await asyncio.gather(
                    _run_pov(bus, model, cam_pov),
                    _run_hand(bus, landmarker, cam_hand),
                )
            except Exception as exc:
                print(f"[dual] Error: {exc}. Retrying in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if cam_pov:
                    await cam_pov.close()
                if cam_hand:
                    await cam_hand.close()
                await bus.close()
                if SHOW_CAMERA:
                    cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if SHOW_CAMERA:
            cv2.destroyAllWindows()
