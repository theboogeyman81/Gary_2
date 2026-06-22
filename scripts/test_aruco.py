"""
Grab one frame from the POV XIAO and test ArUco detection.
Saves annotated result to /tmp/aruco_test.jpg so you can see what's detected.

Run:
    uv run python -m scripts.test_aruco
"""

import sys
import cv2
import numpy as np
import requests
from config.settings import POV_CAMERA_SOURCE


def grab_frame(url: str) -> np.ndarray:
    resp = requests.get(url, stream=True, timeout=(10, None))
    buf = b""
    for chunk in resp.iter_content(chunk_size=4096):
        buf += chunk
        start = buf.find(b'\xff\xd8')
        end = buf.find(b'\xff\xd9', start + 2 if start != -1 else 0)
        if start != -1 and end != -1:
            jpg = buf[start:end + 2]
            frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                return frame
    raise RuntimeError("No frame received")


def main() -> None:
    if not POV_CAMERA_SOURCE.startswith("xiao:"):
        print(f"POV_CAMERA_SOURCE is {POV_CAMERA_SOURCE!r} — must be xiao:HOST")
        sys.exit(1)

    host = POV_CAMERA_SOURCE.split(":", 1)[1]
    url = f"http://{host}/stream"
    print(f"Grabbing frame from {url} ...")
    frame = grab_frame(url)
    print(f"Frame shape: {frame.shape}")

    # Try detection with default params
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)
    corners, ids, rejected = detector.detectMarkers(frame)

    print(f"Default params  → detected: {ids.flatten().tolist() if ids is not None else []}, rejected: {len(rejected)}")

    # Try with lenient params
    params2 = cv2.aruco.DetectorParameters()
    params2.adaptiveThreshWinSizeMin = 3
    params2.adaptiveThreshWinSizeMax = 53
    params2.adaptiveThreshWinSizeStep = 4
    params2.adaptiveThreshConstant = 7
    params2.minMarkerPerimeterRate = 0.02
    params2.maxMarkerPerimeterRate = 4.0
    params2.errorCorrectionRate = 0.9
    detector2 = cv2.aruco.ArucoDetector(aruco_dict, params2)
    corners2, ids2, rejected2 = detector2.detectMarkers(frame)

    print(f"Lenient params  → detected: {ids2.flatten().tolist() if ids2 is not None else []}, rejected: {len(rejected2)}")

    # Annotate and save
    display = frame.copy()
    fh, fw = frame.shape[:2]

    # Draw centered region box
    from config.settings import CENTERED_REGION_FRACTION
    mx = int(fw * (1 - CENTERED_REGION_FRACTION) / 2)
    my = int(fh * (1 - CENTERED_REGION_FRACTION) / 2)
    cv2.rectangle(display, (mx, my), (fw - mx, fh - my), (0, 255, 255), 2)
    cv2.putText(display, "centered region", (mx + 4, my + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    # Draw detected markers (lenient)
    if ids2 is not None:
        cv2.aruco.drawDetectedMarkers(display, corners2, ids2)

    # Draw rejected candidates (helps see if marker is visible but failing)
    for r in rejected2:
        pts = r[0].astype(int)
        cv2.polylines(display, [pts], True, (0, 0, 255), 1)

    out = "/tmp/aruco_test.jpg"
    cv2.imwrite(out, display)
    print(f"\nAnnotated frame saved to {out}")
    print("  Yellow box  = centered region (marker must be inside this)")
    print("  Green box   = detected ArUco marker")
    print("  Red outline = rejected candidate (marker seen but failed decode)")
    print("\nOpen /tmp/aruco_test.jpg to inspect.")


if __name__ == "__main__":
    main()
