"""
POV pipeline — detects registered devices in the forward camera.

Reads frames from POV_CAMERA_SOURCE, runs YOLO (for COCO-class devices) and
ArUco detection (for marker-tagged devices), and publishes:
  - device_entered_view  when a device is centered and stable for STABILITY_FRAMES_ENTER frames
  - device_left_view     when a device disappears for STABILITY_FRAMES_LEAVE frames

Device registry is loaded from config/devices.yaml at startup.

Run standalone:
    uv run python -m pipelines.pov_pipeline
"""

import asyncio
from pathlib import Path

import cv2
import numpy as np
import yaml
from ultralytics import YOLO

from bus.redis_bus import Bus
from config.settings import (
    CENTERED_REGION_FRACTION,
    POV_CAMERA_SOURCE,
    SHOW_CAMERA,
    STABILITY_FRAMES_ENTER,
    STABILITY_FRAMES_LEAVE,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL,
)
from events.schema import Event
from pipelines.camera_source import make_camera_source

_DEVICES_YAML = Path(__file__).parent.parent / "config" / "devices.yaml"

# ArUco dictionary — DICT_4X4_50 covers IDs 0-49, easy to print
_ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_ARUCO_PARAMS = cv2.aruco.DetectorParameters()
# Tuned for JPEG-compressed WiFi streams — wider thresholding window and
# higher error correction so compression artifacts don't break decoding.
_ARUCO_PARAMS.adaptiveThreshWinSizeMin = 3
_ARUCO_PARAMS.adaptiveThreshWinSizeMax = 53
_ARUCO_PARAMS.adaptiveThreshWinSizeStep = 4
_ARUCO_PARAMS.adaptiveThreshConstant = 7
_ARUCO_PARAMS.minMarkerPerimeterRate = 0.02
_ARUCO_PARAMS.maxMarkerPerimeterRate = 4.0
_ARUCO_PARAMS.errorCorrectionRate = 0.9


def _load_registry() -> tuple[dict[int, dict], dict[str, dict]]:
    """
    Load devices.yaml and return:
      aruco_devices: {aruco_id: device_entry}
      yolo_devices:  {yolo_class: device_entry}
    """
    with open(_DEVICES_YAML) as f:
        data = yaml.safe_load(f)

    aruco: dict[int, dict] = {}
    yolo: dict[str, dict] = {}

    for device in data.get("devices", []):
        v = device.get("vision", {})
        if v.get("method") == "aruco" and v.get("aruco_id") is not None:
            aruco[int(v["aruco_id"])] = device
        elif v.get("method") == "yolo" and v.get("yolo_class"):
            yolo[v["yolo_class"].lower()] = device

    return aruco, yolo


def _is_centered(cx: float, cy: float, fw: int, fh: int) -> bool:
    """Return True if the point (cx, cy) falls within the centered region."""
    margin_x = fw * (1 - CENTERED_REGION_FRACTION) / 2
    margin_y = fh * (1 - CENTERED_REGION_FRACTION) / 2
    return (margin_x <= cx <= fw - margin_x) and (margin_y <= cy <= fh - margin_y)


def _detect_aruco(
    frame: np.ndarray,
    aruco_devices: dict[int, dict],
) -> list[tuple[dict, list, float, str]]:
    """Returns list of (device_entry, bbox, confidence, "aruco")."""
    detector = cv2.aruco.ArucoDetector(_ARUCO_DICT, _ARUCO_PARAMS)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    corners, ids, _ = detector.detectMarkers(gray)
    results: list[tuple[dict, list, float, str]] = []
    if ids is None:
        return results
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        if int(marker_id) not in aruco_devices:
            continue
        pts = marker_corners[0]
        x = int(pts[:, 0].min())
        y = int(pts[:, 1].min())
        w = int(pts[:, 0].max()) - x
        h = int(pts[:, 1].max()) - y
        results.append((aruco_devices[int(marker_id)], [x, y, w, h], 1.0, "aruco"))
    return results


def _detect_yolo(
    model: YOLO,
    frame: np.ndarray,
    yolo_devices: dict[str, dict],
) -> list[tuple[dict, list, float, str]]:
    """Returns list of (device_entry, bbox, confidence, "yolo")."""
    results = model(frame, verbose=False, conf=YOLO_CONFIDENCE_THRESHOLD)
    detections: list[tuple[dict, list, float, str]] = []
    for r in results:
        for box in r.boxes:
            cls_name = model.names[int(box.cls)].lower()
            if cls_name not in yolo_devices:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            bbox = [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]
            conf = float(box.conf)
            detections.append((yolo_devices[cls_name], bbox, conf, "yolo"))
    return detections


async def run(bus: Bus) -> None:
    aruco_devices, yolo_devices = _load_registry()

    # Open camera concurrently while YOLO loads — both take several seconds on first run,
    # and starting them together prevents macOS from getting confused by sequential opens.
    cam = make_camera_source(POV_CAMERA_SOURCE)
    open_task = asyncio.create_task(cam.open())
    model = await asyncio.to_thread(YOLO, YOLO_MODEL)
    print(f"[pov_pipeline] Loaded YOLO model: {YOLO_MODEL}")
    print(f"[pov_pipeline] Registry: {len(aruco_devices)} ArUco, {len(yolo_devices)} YOLO devices")
    print(f"[pov_pipeline] Waiting for camera {POV_CAMERA_SOURCE} ...")
    try:
        await asyncio.wait_for(open_task, timeout=12.0)
    except asyncio.TimeoutError:
        await cam.close()
        raise RuntimeError(f"Camera {POV_CAMERA_SOURCE} warmup timed out — is it in use by another process?")
    print(f"[pov_pipeline] Camera ready")

    all_device_ids: set[str] = set()
    for d in aruco_devices.values():
        all_device_ids.add(d["ha_entity_id"])
    for d in yolo_devices.values():
        all_device_ids.add(d["ha_entity_id"])

    in_view: dict[str, bool] = {did: False for did in all_device_ids}
    enter_counters: dict[str, int] = {did: 0 for did in all_device_ids}
    leave_counters: dict[str, int] = {did: 0 for did in all_device_ids}

    backoff = 1.0
    if SHOW_CAMERA:
        cv2.namedWindow("pov pipeline", cv2.WINDOW_NORMAL)

    first_frame = True
    try:
        async for frame in cam.frames():
            if first_frame:
                print(f"[pov_pipeline] First frame: {frame.shape}")
                first_frame = False
            backoff = 1.0
            fh, fw = frame.shape[:2]

            # Gather all centered detections this frame into a dict keyed by device_id.
            # If multiple detections for the same device, keep highest confidence.
            centered: dict[str, tuple[dict, list, float, str]] = {}
            all_detections = _detect_aruco(frame, aruco_devices) + _detect_yolo(model, frame, yolo_devices)
            for device, bbox, conf, method in all_detections:
                did = device["ha_entity_id"]
                cx = bbox[0] + bbox[2] / 2
                cy = bbox[1] + bbox[3] / 2
                if _is_centered(cx, cy, fw, fh):
                    if did not in centered or conf > centered[did][2]:
                        centered[did] = (device, bbox, conf, method)

            # State machine for each registered device
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
                            print(f"[pov_pipeline] device_entered_view: {device['friendly_name']}")
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
                            print(f"[pov_pipeline] device_left_view: {did}")

            if SHOW_CAMERA:
                display = frame.copy()
                # Draw centered region boundary
                mx = int(fw * (1 - CENTERED_REGION_FRACTION) / 2)
                my = int(fh * (1 - CENTERED_REGION_FRACTION) / 2)
                cv2.rectangle(display, (mx, my), (fw - mx, fh - my), (80, 80, 80), 1)
                # Draw all detections (green = in view, orange = detected but not in view yet)
                for device, bbox, conf, method in all_detections:
                    did = device["ha_entity_id"]
                    x, y, w, h = bbox
                    color = (0, 220, 0) if in_view[did] else (0, 140, 255)
                    cv2.rectangle(display, (x, y), (x + w, y + h), color, 2)
                    frames_label = f"+{enter_counters[did]}" if not in_view[did] else "IN VIEW"
                    label = f"{device['friendly_name']} {conf:.2f} [{method}] {frames_label}"
                    cv2.putText(display, label, (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                cv2.imshow("pov pipeline", display)
                cv2.waitKey(10)

    except Exception as exc:
        print(f"[pov_pipeline] Camera error: {exc}. Retrying in {backoff:.0f}s ...")
        await bus.publish(Event(
            type="pipeline_error",
            source="pov_pipeline",
            payload={"error": str(exc)},
        ))
        await cam.close()
        if SHOW_CAMERA:
            cv2.destroyWindow("pov pipeline")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


async def main() -> None:
    bus = Bus()
    backoff = 1.0
    while True:
        try:
            await bus.connect()
            print(f"[pov_pipeline] Connected — reading from {POV_CAMERA_SOURCE}")
            await run(bus)
        except Exception as exc:
            print(f"[pov_pipeline] Bus error: {exc}. Reconnecting in {backoff:.0f}s ...")
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
