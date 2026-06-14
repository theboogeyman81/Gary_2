"""
Gary teaching tool — block-by-block code lesson via voice.

Flow:
  begin_teaching(topic, bus) → generates lesson spec, teaches block 0
  next_lesson_block(bus)     → advances to next block until done
Each block: appends code to file on disk + publishes show_popup to overlay.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from bus.redis_bus import Bus
from events.schema import Event

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger("gary.teach")

_SPEC_PROMPT = """\
You are a patient coding teacher for complete beginners.
Generate a step-by-step lesson for: "{topic}".

Return ONLY a valid JSON array — no markdown fences, no text outside the JSON.

Format:
[
  {{"file": "index.html", "code": "<!DOCTYPE html>\\n<html lang=\\"en\\">", "explanation": "Every HTML page starts with DOCTYPE — it tells the browser this is HTML5."}},
  {{"file": "index.html", "code": "<head>\\n  <title>My Button</title>\\n</head>", "explanation": "The head section holds metadata — like the page title shown in the browser tab."}},
  ...
]

CRITICAL RULES:
- Each block's "code" field must contain ONLY the NEW lines being added in that step — NOT the full file.
- Think of it as: if you stacked all blocks for a file together in order, you get the complete file.
- 6 to 8 blocks total across all files
- Each block: 1 to 6 lines maximum
- explanation: 1-2 sentences, plain spoken English (will be read aloud — no backticks or markdown)
- For an HTML button topic: use index.html and style.css
"""


@dataclass
class TeachingBlock:
    file: str
    code: str
    explanation: str


@dataclass
class TeachingSession:
    topic: str
    project_dir: Path
    blocks: list[TeachingBlock]
    current: int = 0


_active_session: TeachingSession | None = None


def _slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _build_lesson_spec(topic: str) -> list[TeachingBlock]:
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    prompt = _SPEC_PROMPT.format(topic=topic)
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    raw = response.text.strip()
    # Strip markdown fences if Gemini adds them despite instructions
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    data = json.loads(raw)
    return [TeachingBlock(file=b["file"], code=b["code"], explanation=b["explanation"]) for b in data]


async def _teach_block(session: TeachingSession, bus: Bus) -> str:
    block = session.blocks[session.current]
    total = len(session.blocks)
    idx = session.current

    # Append code block to file on disk
    target = session.project_dir / block.file
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(block.code + "\n")

    logger.info("[gary.teach] wrote block %d/%d to %s", idx + 1, total, target)

    # Show code on laptop overlay
    try:
        await bus.publish(Event(
            type="show_popup",
            source="voice_agent",
            payload={
                "title": f"Block {idx + 1} of {total} — {block.file}",
                "text": block.code,
            },
        ))
    except Exception as exc:
        logger.warning("[gary.teach] popup publish failed: %s", exc)

    return block.explanation


async def begin_teaching(topic: str, bus: Bus) -> str:
    global _active_session

    project_dir = Path.home() / "Gary_lessons" / _slugify(topic)
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[gary.teach] building spec for topic=%r", topic)
    try:
        blocks = _build_lesson_spec(topic)
    except Exception as exc:
        logger.error("[gary.teach] spec generation failed: %s", exc)
        return "Sorry, I had trouble generating the lesson. Try again in a moment."

    _active_session = TeachingSession(topic=topic, project_dir=project_dir, blocks=blocks)

    explanation = await _teach_block(_active_session, bus)
    total = len(blocks)
    return (
        f"Alright, let's learn {topic}. I've set up your project folder at Gary lessons slash {_slugify(topic)}. "
        f"We have {total} blocks to go through. Here's the first one. {explanation} "
        f"Say next whenever you're ready to continue."
    )


async def next_lesson_block(bus: Bus) -> str:
    global _active_session

    if _active_session is None:
        return "There's no active lesson right now. Ask me to teach you something to start one."

    _active_session.current += 1
    total = len(_active_session.blocks)

    if _active_session.current >= total:
        topic = _active_session.topic
        project_dir = _active_session.project_dir
        _active_session = None
        return (
            f"That's the whole lesson on {topic}. "
            f"Your files are saved in Gary lessons slash {_slugify(topic)}. "
            f"Open them in a browser and you'll see your button. Nice work."
        )

    explanation = await _teach_block(_active_session, bus)
    remaining = total - _active_session.current - 1
    suffix = f"{remaining} block{'s' if remaining != 1 else ''} left after this." if remaining else "This is the last block."
    return f"{explanation} {suffix}"
