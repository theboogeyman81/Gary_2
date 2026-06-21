"""
Gary teaching tool — block-by-block code lesson via voice.

Flow:
  begin_teaching(topic, bus)    → asks a diagnostic question
  answer_diagnostic(answer, bus) → records answer, may ask follow-up, then starts lesson
  next_lesson_block(bus)         → advances to next block until done

Each block: appends code to file on disk + publishes show_popup to overlay.
"""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from bus.redis_bus import Bus
from events.schema import Event

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger("gary.teach")

# ---------------------------------------------------------------------------
# Spec prompts — one per experience level
# ---------------------------------------------------------------------------

_SPEC_PROMPTS = {
    "beginner": """\
You are a patient coding teacher for complete beginners who have NEVER written code before.
Generate a step-by-step lesson for: "{topic}".

Return ONLY a valid JSON array — no markdown fences, no text outside the JSON.

Each item has these fields:
  "file"        — filename to write to (e.g. "index.html", "style.css")
  "action"      — "append" to add new lines to the end, or "overwrite" to replace the entire file
  "code"        — the code for this step (see rules below)
  "explanation" — what to say aloud

Format example:
[
  {{"file": "index.html", "action": "append", "code": "<!DOCTYPE html>\\n<html lang=\\"en\\">", "explanation": "Every HTML page starts with DOCTYPE — it tells the browser this is HTML5."}},
  {{"file": "style.css", "action": "overwrite", "code": "button {{\\n  background: blue;\\n  color: white;\\n}}", "explanation": "Now we are rewriting the CSS to make the button look nicer."}}
]

CRITICAL RULES:
- Use "append" when adding new lines that come after what was already written.
- Use "overwrite" when changing or improving something already written — put the FULL new file content in "code".
- 7 to 8 blocks total — take it slow, one small concept per block
- Append blocks: 1 to 4 new lines maximum
- Explanation: 1-2 sentences, plain spoken English, no jargon — explain what every term means
- For an HTML button topic: use index.html and style.css
""",

    "some": """\
You are a coding teacher. The student knows basic HTML tags but is still learning CSS.
Generate a step-by-step lesson for: "{topic}".

Return ONLY a valid JSON array — no markdown fences, no text outside the JSON.

Each item has these fields:
  "file"        — filename to write to
  "action"      — "append" to add new lines, or "overwrite" to replace the entire file
  "code"        — the code for this step
  "explanation" — what to say aloud

Format example:
[
  {{"file": "index.html", "action": "append", "code": "<!DOCTYPE html>\\n<html lang=\\"en\\">", "explanation": "Standard HTML5 boilerplate — the lang attribute helps screen readers."}},
  {{"file": "style.css", "action": "overwrite", "code": "button {{\\n  background: #3498db;\\n}}", "explanation": "Now we refine the CSS — overwriting it with the improved version."}}
]

CRITICAL RULES:
- Use "append" when adding lines that come after what was already written.
- Use "overwrite" when modifying existing content — include the FULL updated file in "code".
- 6 to 7 blocks total
- Append blocks: 1 to 6 new lines maximum
- Explanation: 1-2 sentences, conversational English — basic HTML/CSS terms are fine
- For an HTML button topic: use index.html and style.css
""",

    "comfortable": """\
You are a coding teacher. The student is comfortable with HTML and CSS fundamentals.
Generate a focused, efficient lesson for: "{topic}".

Return ONLY a valid JSON array — no markdown fences, no text outside the JSON.

Each item has these fields:
  "file"        — filename to write to
  "action"      — "append" to add new lines, or "overwrite" to replace the entire file
  "code"        — the code for this step
  "explanation" — what to say aloud

Format example:
[
  {{"file": "index.html", "action": "append", "code": "<!DOCTYPE html>\\n<html lang=\\"en\\">\\n<head>\\n  <meta charset=\\"UTF-8\\">\\n  <link rel=\\"stylesheet\\" href=\\"style.css\\">\\n</head>\\n<body>", "explanation": "Standard boilerplate — nothing new here."}},
  {{"file": "style.css", "action": "overwrite", "code": "button {{\\n  background: #3498db;\\n  border-radius: 6px;\\n  transition: opacity 0.2s;\\n}}\\nbutton:hover {{ opacity: 0.8; }}", "explanation": "Rewriting the stylesheet to add the hover transition."}}
]

CRITICAL RULES:
- Use "append" when adding lines after existing content.
- Use "overwrite" when refining or modifying existing content — include the FULL updated file.
- 5 to 6 blocks total — group related lines, move at a brisk pace
- Append blocks: up to 8 lines
- Explanation: 1 sentence, proper terminology, focus on the WHY
- For an HTML button topic: use index.html and style.css
""",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TeachingBlock:
    file: str
    code: str
    explanation: str
    action: str = "append"  # "append" | "overwrite"


@dataclass
class TeachingSession:
    topic: str
    project_dir: Path
    blocks: list[TeachingBlock]
    level: str
    current: int = 0


@dataclass
class DiagnosticState:
    topic: str
    questions_asked: int = 0
    level: str = "beginner"


# ---------------------------------------------------------------------------
# Module-level state (one session at a time)
# ---------------------------------------------------------------------------

_active_session: TeachingSession | None = None
_diagnostic: DiagnosticState | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _parse_experience(answer: str) -> str:
    """Map a free-text voice answer to one of three experience levels."""
    lower = answer.lower()
    if any(w in lower for w in ["no", "never", "nope", "not really", "beginner", "first time", "nothing"]):
        return "beginner"
    if any(w in lower for w in ["comfortable", "lot", "lots", "plenty", "good at", "know it well", "very familiar"]):
        return "comfortable"
    # "yes", "some", "a bit", "kind of", "little", "basic" → intermediate
    return "some"


def _open_in_editor(project_dir: Path) -> None:
    """Open the lesson folder in Cursor, falling back to VS Code, then macOS Finder."""
    for cmd in ("cursor", "code"):
        try:
            subprocess.Popen([cmd, str(project_dir)])
            logger.info("[gary.teach] opened %s in %s", project_dir, cmd)
            return
        except FileNotFoundError:
            continue
    subprocess.Popen(["open", str(project_dir)])
    logger.info("[gary.teach] opened %s via open", project_dir)


async def _generate_notes(session: TeachingSession, bus: Bus) -> None:
    """Summarise the session into a short notes file and show a popup."""
    blocks_summary = "\n".join(
        f"- [{b.file}] {b.explanation}" for b in session.blocks
    )
    prompt = (
        f'Write brief revision notes (max 200 words) for a beginner who just completed a coding lesson.\n'
        f'Topic: "{session.topic}"\n'
        f'Experience level: {session.level}\n\n'
        f'What was covered:\n{blocks_summary}\n\n'
        f'Include:\n'
        f'1. One sentence on what they built\n'
        f'2. Key concepts (3-5 bullet points, plain English, no code)\n'
        f'3. Files created and what each does (one line each)\n'
        f'4. One "try next" suggestion\n\n'
        f'Plain text only — no markdown, no code blocks.'
    )

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        notes = response.text.strip()
    except Exception as exc:
        logger.error("[gary.teach] notes generation failed: %s", exc)
        notes = f"Lesson: {session.topic}\n\nCovered:\n{blocks_summary}"

    notes_path = session.project_dir / "notes.txt"
    notes_path.write_text(notes, encoding="utf-8")
    logger.info("[gary.teach] notes written to %s", notes_path)

    try:
        await bus.publish(Event(
            type="show_popup",
            source="voice_agent",
            payload={
                "title": f"Session Notes — {session.topic}",
                "text": f"Saved to: {notes_path}\n\n{notes}",
            },
        ))
    except Exception as exc:
        logger.warning("[gary.teach] notes popup failed: %s", exc)


def _build_lesson_spec(topic: str, level: str) -> list[TeachingBlock]:
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    prompt = _SPEC_PROMPTS[level].format(topic=topic)
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    raw = response.text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    data = json.loads(raw)
    return [
        TeachingBlock(
            file=b["file"],
            code=b["code"],
            explanation=b["explanation"],
            action=b.get("action", "append"),
        )
        for b in data
    ]


async def _teach_block(session: TeachingSession, bus: Bus) -> str:
    block = session.blocks[session.current]
    total = len(session.blocks)
    idx = session.current

    target = session.project_dir / block.file
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if block.action == "overwrite" else "a"
    with target.open(mode) as f:
        f.write(block.code + "\n")

    logger.info("[gary.teach] wrote block %d/%d to %s", idx + 1, total, target)

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


async def _start_lesson(bus: Bus) -> str:
    """Build the spec and teach block 0. Called after diagnostics are complete."""
    global _diagnostic, _active_session

    topic = _diagnostic.topic
    level = _diagnostic.level
    _diagnostic = None

    project_dir = Path.home() / "Gary_lessons" / _slugify(topic)
    project_dir.mkdir(parents=True, exist_ok=True)
    _open_in_editor(project_dir)

    logger.info("[gary.teach] building spec for topic=%r level=%r", topic, level)
    try:
        blocks = _build_lesson_spec(topic, level)
    except Exception as exc:
        logger.error("[gary.teach] spec generation failed: %s", exc)
        return "Sorry, I had trouble generating the lesson. Try again in a moment."

    _active_session = TeachingSession(
        topic=topic, project_dir=project_dir, blocks=blocks, level=level
    )

    explanation = await _teach_block(_active_session, bus)
    total = len(blocks)

    level_phrase = {
        "beginner": "We'll start from absolute scratch — I'll explain every single step.",
        "some": "Since you know the basics, I'll keep things focused on what's new.",
        "comfortable": "You know your stuff, so I'll keep the pace brisk and focus on the key patterns.",
    }[level]

    return (
        f"Alright, let's build {topic}. {level_phrase} "
        f"Your project folder is at Gary lessons slash {_slugify(topic)}. "
        f"We have {total} steps. Here's the first one. {explanation} "
        f"Say next whenever you're ready to continue."
    )


# ---------------------------------------------------------------------------
# Public API (called by voice_agent.py function_tools)
# ---------------------------------------------------------------------------

async def begin_teaching(topic: str, bus: Bus) -> str:
    """Ask the first diagnostic question. Lesson spec is not built yet."""
    global _diagnostic, _active_session

    _active_session = None
    _diagnostic = DiagnosticState(topic=topic)

    logger.info("[gary.teach] diagnostic started for topic=%r", topic)
    return "Before we dive in — have you written any HTML or CSS before?"


async def answer_diagnostic(answer: str, bus: Bus) -> str:
    """Record one diagnostic answer. Returns the next question or kicks off the lesson."""
    global _diagnostic

    if _diagnostic is None:
        return "There's no lesson being set up right now. Ask me to teach you something first."

    if _diagnostic.questions_asked == 0:
        level = _parse_experience(answer)
        _diagnostic.level = level
        _diagnostic.questions_asked += 1

        if level == "some":
            # One follow-up to separate intermediate from advanced
            return "Got it. Are you comfortable with things like CSS classes and flexbox, or are you still getting the hang of the basics?"

        # beginner or comfortable — enough signal, start the lesson
        return await _start_lesson(bus)

    else:
        # Second answer — refine between "some" and "comfortable"
        lower = answer.lower()
        if any(w in lower for w in ["comfortable", "yes", "yeah", "know", "familiar", "flexbox", "fine", "easy"]):
            _diagnostic.level = "comfortable"
        else:
            _diagnostic.level = "some"
        return await _start_lesson(bus)


async def next_lesson_block(bus: Bus) -> str:
    global _active_session

    if _active_session is None:
        return "There's no active lesson right now. Ask me to teach you something to start one."

    _active_session.current += 1
    total = len(_active_session.blocks)

    if _active_session.current >= total:
        topic = _active_session.topic
        await _generate_notes(_active_session, bus)
        _active_session = None
        return (
            f"That's the whole lesson on {topic}. "
            f"I've saved a notes file to your project folder — check the overlay for a summary. "
            f"Open the HTML file in a browser and you'll see your work. Nice job."
        )

    explanation = await _teach_block(_active_session, bus)
    remaining = total - _active_session.current - 1
    suffix = (
        f"{remaining} block{'s' if remaining != 1 else ''} left after this."
        if remaining else "This is the last block."
    )
    return f"{explanation} {suffix}"
