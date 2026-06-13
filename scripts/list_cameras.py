"""
Diagnostic: enumerate USB webcams and save one frame each.

Run with:
    uv run python -m scripts.list_cameras

Saves camera_0.jpg, camera_1.jpg, etc. to the project root.
Inspect the images to identify which camera index maps to which physical camera,
then set POV_CAMERA_SOURCE and HAND_CAMERA_SOURCE in .env accordingly.
"""

import os
import sys

import cv2


def main() -> None:
    found = []
    print("Scanning camera indices 0–4 ...")

    for idx in range(5):
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f"  index {idx}: not available")
            cap.release()
            continue

        ok, frame = cap.read()
        cap.release()

        if not ok or frame is None:
            print(f"  index {idx}: opened but could not read frame")
            continue

        out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), f"camera_{idx}.jpg")
        cv2.imwrite(out_path, frame)
        h, w = frame.shape[:2]
        print(f"  index {idx}: {w}x{h}  →  saved {out_path}")
        found.append(idx)

    if not found:
        print("\nNo cameras found. Check USB connections.")
        sys.exit(1)

    print(f"\nFound {len(found)} camera(s): indices {found}")
    print("Set POV_CAMERA_SOURCE=mac:<index> and HAND_CAMERA_SOURCE=mac:<index> in .env")


if __name__ == "__main__":
    main()
