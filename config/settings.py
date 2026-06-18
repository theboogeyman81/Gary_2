"""
Central config for Gary.

Loads environment variables from .env once, makes them available
as module-level constants. Anywhere in Gary, you can do:

    from config.settings import HA_URL, HA_TOKEN, ENTITY_ID
"""

import os
from dotenv import load_dotenv


# Load .env file from the project root.
load_dotenv()


# Home Assistant
HA_URL = os.getenv("HA_URL", "")
HA_TOKEN = os.getenv("HA_TOKEN", "")
ENTITY_ID = os.getenv("ENTITY_ID", "")
FIRE_TV_ENTITY_ID = os.getenv("FIRE_TV_ENTITY_ID", "media_player.living_room_tv")

# Gesture pipeline — camera sources
POV_CAMERA_SOURCE = os.getenv("POV_CAMERA_SOURCE", "mac:0")
HAND_CAMERA_SOURCE = os.getenv("HAND_CAMERA_SOURCE", "mac:1")

# Gesture pipeline — YOLO
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
YOLO_CONFIDENCE_THRESHOLD = float(os.getenv("YOLO_CONFIDENCE_THRESHOLD", "0.5"))

# Gesture pipeline — framing
CENTERED_REGION_FRACTION = float(os.getenv("CENTERED_REGION_FRACTION", "0.4"))

# Gesture pipeline — state machine timing (frames at ~30fps)
STABILITY_FRAMES_ENTER = int(os.getenv("STABILITY_FRAMES_ENTER", "5"))
STABILITY_FRAMES_LEAVE = int(os.getenv("STABILITY_FRAMES_LEAVE", "10"))
PINCH_HOLD_FRAMES = int(os.getenv("PINCH_HOLD_FRAMES", "5"))

# Gesture pipeline — thresholds
PINCH_THRESHOLD = float(os.getenv("PINCH_THRESHOLD", "0.04"))
PINCH_ENTER_THRESHOLD = float(os.getenv("PINCH_ENTER_THRESHOLD", "0.05"))
PINCH_EXIT_THRESHOLD = float(os.getenv("PINCH_EXIT_THRESHOLD", "0.09"))
PINCH_HOLD_DURATION = float(os.getenv("PINCH_HOLD_DURATION", "0.6"))
GESTURE_COOLDOWN_MS = int(os.getenv("GESTURE_COOLDOWN_MS", "1500"))

# Set SHOW_CAMERA=true in .env to display live camera feeds while pipelines run
SHOW_CAMERA = os.getenv("SHOW_CAMERA", "false").lower() == "true"


def validate() -> None:
    """Raise an error if required config is missing."""
    missing = []
    if not HA_URL:
        missing.append("HA_URL")
    if not HA_TOKEN:
        missing.append("HA_TOKEN")
    if not ENTITY_ID:
        missing.append("ENTITY_ID")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")