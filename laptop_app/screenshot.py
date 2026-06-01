"""
Screenshot capture for Gary's laptop companion app.

Uses mss for fast cross-platform screen capture.
Saves to a temp folder, returns both path and base64 for flexibility.
"""

import base64
import io
from pathlib import Path
from datetime import datetime

import mss
from PIL import Image


# Screenshots are saved here. Gitignored.
SCREENSHOT_DIR = Path.home() / ".gary" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def capture_screen() -> dict:
    """
    Capture the primary monitor's screen.
    
    Returns a dict with:
        - path: filesystem path to the saved PNG
        - base64: the image encoded as base64 string (for cloud LLM calls)
        - width, height: dimensions
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"screenshot_{timestamp}.png"
    filepath = SCREENSHOT_DIR / filename
    
    with mss.mss() as sct:
        # Monitor 1 is the primary display.
        # Monitor 0 would be the "all monitors combined" virtual screen.
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        
        # Convert mss screenshot to a Pillow image
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        
        # Save as PNG
        img.save(filepath, "PNG")
        
        # Also encode as base64 for cloud LLM use
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64_string = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        return {
            "path": str(filepath),
            "base64": b64_string,
            "width": screenshot.width,
            "height": screenshot.height,
        }