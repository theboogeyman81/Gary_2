"""
Gary YouTube Notes tool.

When the user is watching a YouTube video, this tool:
1. Reads the current Chrome/Safari tab URL via AppleScript
2. Extracts the YouTube video ID
3. Fetches the transcript via youtube-transcript-api
4. Summarizes it with Gemini (coding tutorial → code + concepts; general → bullet points)
5. Saves to ~/Gary_notes/{slug}/notes.txt and opens in editor
6. Publishes show_popup + copy_to_clipboard events
"""

import asyncio
import logging
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from bus.redis_bus import Bus
from events.schema import Event

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger("gary.youtube_notes")

_SUMMARY_PROMPT = """\
You are Gary, a concise study assistant. Analyze this YouTube transcript and produce structured notes.

Decide: is this a CODING / TECHNICAL tutorial, or GENERAL content?

If CODING / TECHNICAL:
- Key concepts (dash list, plain English, 1-sentence each)
- Code snippets extracted verbatim (labelled with the language/context)
- One "Try this" challenge at the end

If GENERAL:
- 2-3 sentence summary of what the video covers
- 5-8 key takeaways (dash list)
- Any notable tools, people, or resources mentioned

Rules:
- Plain text only, no # markdown headers, use dashes for bullets
- Under 500 words
- Speak to the learner directly ("you", "your code")

Transcript:
{transcript}
"""


async def _get_browser_url() -> str | None:
    """Get the active tab URL from Chrome, then Safari, via AppleScript."""
    browsers = [
        ("Google Chrome", 'tell application "Google Chrome" to return URL of active tab of front window'),
        ("Safari",        'tell application "Safari" to return URL of current tab of front window'),
    ]
    for browser, script in browsers:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as exc:
            logger.debug("[gary.youtube] %s AppleScript failed: %s", browser, exc)
    return None


def _extract_video_id(url: str) -> str | None:
    """Extract an 11-char YouTube video ID from any YouTube URL variant."""
    for pattern in [
        r"youtube\.com/watch\?.*v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
    ]:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def _fetch_transcript_sync(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    return " ".join(snippet.text for snippet in transcript)


def _fetch_title_sync(video_id: str) -> str:
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read(32768).decode("utf-8", errors="replace")
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            return m.group(1).replace(" - YouTube", "").strip()
    except Exception:
        pass
    return video_id


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]


def _open_in_editor(path: Path) -> None:
    for cmd in ("cursor", "code"):
        try:
            subprocess.Popen([cmd, str(path)])
            logger.info("[gary.youtube] opened %s in %s", path, cmd)
            return
        except FileNotFoundError:
            continue
    subprocess.Popen(["open", str(path)])
    logger.info("[gary.youtube] opened %s via open", path)


async def youtube_notes(bus: Bus) -> str:
    """
    Detect the YouTube video currently open → fetch transcript → summarize → popup.
    Returns a short spoken response for Gary.
    """
    # 1. Get URL from the active browser tab
    url = await _get_browser_url()
    if not url:
        return "I couldn't find an open browser window."

    # 2. Confirm it's a YouTube video
    video_id = _extract_video_id(url)
    if not video_id:
        return "I don't see a YouTube video open right now."

    logger.info("[gary.youtube] fetching notes for video_id=%s", video_id)

    # 3. Fetch title + transcript concurrently
    try:
        title, transcript = await asyncio.gather(
            asyncio.to_thread(_fetch_title_sync, video_id),
            asyncio.to_thread(_fetch_transcript_sync, video_id),
        )
    except Exception as exc:
        err = str(exc).lower()
        if any(k in err for k in ("no transcript", "disabled", "unavailable")):
            return "This video doesn't have captions I can read."
        logger.error("[gary.youtube] fetch failed: %s", exc)
        return "Couldn't reach YouTube right now. Try again in a moment."

    # 4. Summarize with Gemini (cap transcript at 12k chars to stay within context)
    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        prompt = _SUMMARY_PROMPT.format(transcript=transcript[:12000])
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        notes = response.text.strip()
    except Exception as exc:
        logger.error("[gary.youtube] Gemini summarization failed: %s", exc)
        return "Got the transcript but had trouble summarizing it. Try again."

    # 5. Save to ~/Gary_notes/{slug}/notes.txt
    slug = _slugify(title)
    notes_dir = Path.home() / "Gary_notes" / slug
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_path = notes_dir / "notes.txt"
    notes_path.write_text(f"{title}\n{'=' * len(title)}\n\n{notes}", encoding="utf-8")
    logger.info("[gary.youtube] notes saved to %s", notes_path)

    # 6. Open the file in editor
    _open_in_editor(notes_path)

    # 7. Show popup — first 500 chars with a path reminder
    preview = notes[:500] + ("…" if len(notes) > 500 else "")
    try:
        await bus.publish(Event(
            type="show_popup",
            source="voice_agent",
            payload={
                "title": f"Notes: {title}",
                "text": f"{preview}\n\n— Full notes at ~/Gary_notes/{slug}/notes.txt",
            },
        ))
    except Exception as exc:
        logger.warning("[gary.youtube] popup publish failed: %s", exc)

    # 8. Copy full notes to clipboard
    try:
        await bus.publish(Event(
            type="copy_to_clipboard",
            source="voice_agent",
            payload={"text": f"{title}\n\n{notes}"},
        ))
    except Exception as exc:
        logger.warning("[gary.youtube] clipboard publish failed: %s", exc)

    return "Notes saved from that video. Check the card — full notes are in your clipboard too."
