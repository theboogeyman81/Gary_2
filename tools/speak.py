"""
The `speak` tool.

When the agent calls speak(text), this publishes a 'speak' event to the bus.
The TTS pipeline (later) will subscribe to these events and turn them into 
audio sent to the glasses.

For now, the bus monitor will just show the event — that's enough to verify 
the agent is working.
"""

from bus.redis_bus import Bus
from events.schema import Event


async def speak(text: str, bus: Bus) -> str:
    """
    Say something out loud through the glasses speaker.
    
    Use this whenever you want to respond to the user with voice.
    Keep responses short — they're being spoken, not read.
    """
    event = Event(
        type="speak",
        source="agent",
        payload={"text": text},
    )
    await bus.publish(event)
    return f"Spoke: {text}"