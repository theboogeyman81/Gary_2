"""
Gary Screen Annotation tool.

When the user asks Gary to annotate or review their screen:
1. Takes a screenshot via capture_screen() (reuses laptop_app/screenshot.py)
2. Sends the image to Gemini Vision (gemini-2.5-flash) with a structured prompt
3. Receives JSON with normalized (0–1) screen coordinates for each issue found
4. Publishes show_annotations event so the overlay draws pulsing rings
5. Returns a concise spoken summary mentioning each issue by screen location
"""

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from bus.redis_bus import Bus
from events.schema import Event
from laptop_app.screenshot import capture_screen

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger("gary.annotate")

_PROMPT = """\
Look at this screenshot carefully. Identify up to 4 specific issues, bugs, errors, or points of interest.
For each one, return its location as normalized screen coordinates (x and y as decimals between 0 and 1, where 0,0 is top-left).
Return only a JSON array, no markdown:
[{"x": 0.42, "y": 0.31, "label": "short label max 4 words", "note": "one sentence explanation"}]
If there are no notable issues, return an empty array: []
"""


def _location(x: float, y: float) -> str:
    h = "left" if x < 0.35 else ("right" if x > 0.65 else "center")
    v = "top" if y < 0.35 else ("bottom" if y > 0.65 else "middle")
    if h == "center" and v == "middle":
        return "in the middle"
    if h == "center":
        return f"at the {v}"
    if v == "middle":
        return f"on the {h}"
    return f"{v} {h}"


async def annotate_screen(bus: Bus) -> str:
    """
    Capture the screen → send to Gemini Vision → publish show_annotations.
    Returns a short spoken summary of findings for Gary to read aloud.
    """
    data = await asyncio.to_thread(capture_screen)
    img_bytes = base64.b64decode(data["base64"])

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                _PROMPT,
            ],
        )

        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        try:
            points = json.loads(raw)
            if not isinstance(points, list):
                points = []
        except json.JSONDecodeError:
            logger.warning("[gary.annotate] JSON parse failed: %s", raw[:200])
            points = []

        await bus.publish(Event(
            type="show_annotations",
            source="annotate_tool",
            payload={"points": points},
        ))

        if not points:
            return "No notable issues found on screen."

        n = len(points)
        parts = [f"{p.get('label', 'issue')} {_location(p['x'], p['y'])}" for p in points]
        return f"Found {n} issue{'s' if n > 1 else ''}: {', '.join(parts)}."

    except Exception as exc:
        logger.warning("[gary.annotate] annotate_screen failed: %s", exc)
        return "I had trouble analyzing the screen. Try again in a moment."
