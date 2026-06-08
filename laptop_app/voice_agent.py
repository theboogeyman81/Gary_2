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

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, function_tool
from livekit.plugins import cartesia, deepgram, google, silero

from bus.redis_bus import Bus
from events.schema import Event
from tools.home_assistant import control_bulb

# Load .env from project root — worker subprocesses may not inherit shell env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gary.voice")

GARY_SYSTEM_PROMPT = """\
You are Gary, an ambient AI assistant living on the user's laptop.
Be concise and conversational — like a knowledgeable friend, not a search engine.
Keep answers short: 1–3 sentences for simple questions, a bit more only when needed.
No markdown, no bullet points — just natural spoken language.
You can see the user's screen when asked and help with any task.\
"""

_STATE_TO_BUS = {
    "listening": "gary_listening",
    "thinking":  "gary_thinking",
    "speaking":  "gary_speaking",
    "idle":      "gary_idle",
}


class GaryVoiceAgent(Agent):
    def __init__(self, bus: Bus) -> None:
        super().__init__(
            instructions=GARY_SYSTEM_PROMPT,
            stt=deepgram.STT(model="nova-3"),
            vad=silero.VAD.load(),
            llm=google.LLM(
                model="gemini-2.5-flash",
                api_key=os.getenv("GOOGLE_API_KEY"),
            ),
            tts=cartesia.TTS(
                voice="248be419-c632-4f23-adf1-5324ed7dbf1d",  # Barbershop Man — clear, warm
                model="sonic-2",
                api_key=os.getenv("CARTESIA_API_KEY"),
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

    await session.start(GaryVoiceAgent(bus=bus), room=ctx.room)
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
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
