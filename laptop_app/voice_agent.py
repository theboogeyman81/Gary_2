"""
Gary voice agent — LiveKit worker process.

Run with:
    uv run python -m laptop_app.voice_agent start

This registers with LiveKit Cloud as an agent worker. When a room is created
(triggered by holding spacebar for 5s in main_pywebview), LiveKit dispatches
a job here. We run the full pipeline:
    Deepgram STT → Gemini LLM → Cartesia TTS
with turn detection and interrupt handling built into AgentSession.

State changes are published to the Redis bus so the overlay UI can show
listening / thinking / speaking / idle arcs.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Annotated

import base64 as _base64

import google.genai as genai
import google.genai.types as genai_types

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli, function_tool
from livekit.plugins import deepgram, google, silero, elevenlabs

from bus.redis_bus import Bus
from events.schema import Event
from laptop_app.screenshot import capture_screen
from tools.home_assistant import control_bulb
from tools.fire_tv import control_tv as control_tv_impl, launch_tv_app as launch_tv_app_impl
import tools.annotate as annotate_tool
import tools.teach as teach_tool
import tools.youtube_notes as youtube_notes_tool

# Load .env from project root — worker subprocesses may not inherit shell env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gary.voice")

GARY_SYSTEM_PROMPT = """\
You are Gary, an ambient AI assistant living on the user's laptop.
Be concise and conversational — like a knowledgeable friend, not a search engine.
Keep answers short: 1–3 sentences for simple questions, a bit more only when needed.
No markdown, no bullet points — just natural spoken language.
You can see the user's screen when asked — call describe_screen whenever the user asks what's on their screen, what they're looking at, or needs help with something visible.

IMPORTANT: You have tools available. When the user asks to control lights, turn them on or off, \
or adjust room lighting — you MUST call the control_lights tool. Do not just say you will do it. \
Actually call the tool.

When the user mentions the TV, pausing, playing, volume, or turning it on/off — call control_tv. \
When the user asks to open or launch an app (Netflix, Prime, YouTube, HBO, Disney) — call open_tv_app. \
Do not just say you will do it. Actually call the tool.

TEACHING MODE: When the user asks you to teach them something (HTML, CSS, Python, a button, \
a webpage, etc.) — call begin_teaching with a short topic description like "html button" or \
"css flexbox". Gary will return a diagnostic question for you to speak to the user. \
When the user answers that question, call answer_diagnostic with a short summary of what they said \
(e.g. "no never coded before" or "yes some HTML"). Gary may ask one follow-up — same rule, \
call answer_diagnostic with their answer. Once diagnostics are done, the lesson starts automatically. \
Then wait for the user to say "next", "got it", "continue", "ok", or similar — then call \
next_lesson_block to advance. Do not generate lesson content yourself — always use the tools.

YOUTUBE NOTES: When the user asks you to get notes, summarize, extract code, or take notes from \
a video they are watching — call get_youtube_notes. Gary will read the current browser tab, \
fetch the transcript, and return a spoken confirmation. Do not ask for a URL — Gary finds it \
automatically.

SCREEN ANNOTATION: When the user says "annotate this", "what's wrong with my code", \
"highlight the bug", "review my screen", or anything similar — call annotate_screen. Gary will \
capture the screen, analyze it with vision AI, and draw glowing rings on each issue found.\
"""

_STATE_TO_BUS = {
    "listening": "gary_listening",
    "thinking":  "gary_thinking",
    "speaking":  "gary_speaking",
    "idle":      "gary_idle",
}


class GaryVoiceAgent(Agent):
    def __init__(self, bus: Bus, vad: silero.VAD) -> None:
        super().__init__(
            instructions=GARY_SYSTEM_PROMPT,
            stt=deepgram.STT(model="nova-3"),
            vad=vad,
            llm=google.LLM(
                model="gemini-2.5-flash",
                api_key=os.getenv("GOOGLE_API_KEY"),
            ),
            tts=elevenlabs.TTS(
                voice_id=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
                api_key=os.getenv("ELEVENLABS_API_KEY"),
            ),
        )
        self._bus = bus

    @function_tool
    async def control_lights(
        self,
        action: Annotated[str, "Action to perform: 'on', 'off', or 'toggle'"],
    ) -> str:
        """Turn the lights on, off, or toggle them. Use this for any request about lights, room lighting, or brightness."""
        logger.info("[gary-voice] control_lights: action=%s", action)
        return await control_bulb(action, self._bus, area=None)

    @function_tool
    async def describe_screen(self) -> str:
        """Take a screenshot of the user's screen and describe what's on it. Use this when the user asks what's on their screen, what they're looking at, or wants help with something visible on screen."""
        logger.info("[gary-voice] describe_screen: capturing screen")
        loop = asyncio.get_event_loop()
        shot = await loop.run_in_executor(None, capture_screen)
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    genai_types.Part.from_bytes(
                        data=_base64.b64decode(shot["base64"]),
                        mime_type="image/png",
                    ),
                    "Describe what's on this screen concisely in 2-3 sentences. Focus on what the user is actively doing or looking at.",
                ],
            ),
        )
        description = response.text.strip()
        logger.info("[gary-voice] describe_screen: %s", description[:80])
        return description

    @function_tool
    async def begin_teaching(
        self,
        topic: Annotated[str, "What to teach, e.g. 'html button', 'css flexbox', 'python list'"],
    ) -> str:
        """Start a coding lesson for the user. Call this when the user asks Gary to teach them how to build or code something."""
        logger.info("[gary-voice] begin_teaching: topic=%r", topic)
        return await teach_tool.begin_teaching(topic, self._bus)

    @function_tool
    async def answer_diagnostic(
        self,
        answer: Annotated[str, "Short summary of what the user said, e.g. 'no never coded before' or 'yes some HTML'"],
    ) -> str:
        """Record the user's answer to a diagnostic question. Call this whenever the user answers a question Gary asked before starting a lesson."""
        logger.info("[gary-voice] answer_diagnostic: answer=%r", answer)
        return await teach_tool.answer_diagnostic(answer, self._bus)

    @function_tool
    async def next_lesson_block(self) -> str:
        """Advance to the next block in the active lesson. Call this when the user says next, got it, continue, ok, or similar."""
        logger.info("[gary-voice] next_lesson_block")
        return await teach_tool.next_lesson_block(self._bus)

    @function_tool
    async def get_youtube_notes(self) -> str:
        """Get notes from the YouTube video the user is currently watching. Fetches the transcript, summarizes it, saves to a file, and shows a popup. No URL needed — Gary reads it from the browser."""
        logger.info("[gary-voice] get_youtube_notes")
        return await youtube_notes_tool.youtube_notes(self._bus)

    @function_tool
    async def annotate_screen(self) -> str:
        """Capture a screenshot and draw glowing rings on visible issues or bugs. Use when the user asks to annotate, highlight, or review what's on their screen."""
        logger.info("[gary-voice] annotate_screen")
        return await annotate_tool.annotate_screen(self._bus)

    @function_tool
    async def control_tv(
        self,
        action: Annotated[str, "Action: play, pause, play_pause, stop, volume_up, volume_down, mute, next, previous, turn_on, turn_off"],
    ) -> str:
        """Control the Fire TV Stick. Use for any request about the TV: pause, play, volume, skip, turn on/off."""
        logger.info("[gary-voice] control_tv: action=%s", action)
        return await control_tv_impl(action, self._bus)

    @function_tool
    async def open_tv_app(
        self,
        app: Annotated[str, "App name: netflix, prime, youtube, hbo, disney, peacock"],
    ) -> str:
        """Open an app on the Fire TV Stick. Use when the user asks to launch or watch something on TV."""
        logger.info("[gary-voice] open_tv_app: app=%r", app)
        return await launch_tv_app_impl(app, self._bus)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    logger.info("[gary-voice] Connected to room: %s", ctx.room.name)

    bus = Bus()
    bus_ok = False
    try:
        await bus.connect()
        bus_ok = True
        logger.info("[gary-voice] Redis connected")
    except Exception as exc:
        logger.warning("[gary-voice] Redis unavailable — UI states won't update: %s", exc)

    async def _pub(event_type: str) -> None:
        if not bus_ok:
            return
        try:
            await bus.publish(Event(type=event_type, source="voice_agent", payload={}))
        except Exception as exc:
            logger.debug("[gary-voice] publish failed: %s", exc)

    session = AgentSession()

    @session.on("agent_state_changed")
    def on_state_changed(ev) -> None:
        bus_type = _STATE_TO_BUS.get(ev.new_state)
        if bus_type:
            asyncio.create_task(_pub(bus_type))
            logger.info("[gary-voice] state → %s", ev.new_state)

    vad = ctx.proc.userdata["vad"]
    await session.start(GaryVoiceAgent(bus=bus, vad=vad), room=ctx.room)
    logger.info("[gary-voice] Session started")

    # LiveKit 1.5 removed Room.wait_for_disconnect(); wait on the event instead.
    disconnect = asyncio.Event()

    @ctx.room.on("disconnected")
    def _on_disconnect(_reason: object) -> None:
        disconnect.set()

    try:
        await disconnect.wait()
    finally:
        if bus_ok:
            await _pub("gary_idle")
            await bus.close()
        logger.info("[gary-voice] Session ended")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
