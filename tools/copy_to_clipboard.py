"""
The `copy_to_clipboard` tool.

Publishes a 'copy_to_clipboard' event. The laptop app will write the text
to the system clipboard so the user can paste it anywhere.
"""

from bus.redis_bus import Bus
from events.schema import Event


async def copy_to_clipboard(text: str, bus: Bus) -> str:
    """
    Copy text to the user's clipboard.
    
    Use this when generating something the user will paste elsewhere —
    a prompt, a code snippet, a URL, etc. Often used together with
    show_popup so the user can both see it and paste it.
    """
    event = Event(
        type="copy_to_clipboard",
        source="agent",
        payload={"text": text},
    )
    await bus.publish(event)
    return f"Copied to clipboard: {text[:50]}..."