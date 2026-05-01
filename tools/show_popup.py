"""
The `show_popup` tool.

Publishes a 'show_popup' event. The laptop app will render a popup with
the given text — usually for things the user needs to see, copy, or click.
"""

from bus.redis_bus import Bus
from events.schema import Event


async def show_popup(text: str, bus: Bus, title: str = "Gary") -> str:
    """
    Show a popup on the user's laptop with the given text.
    
    Use this when you have something visual or long for the user to see —
    like a generated prompt, a code snippet, or a list of options.
    Don't use for short conversational replies — use speak() instead.
    """
    event = Event(
        type="show_popup",
        source="agent",
        payload={"title": title, "text": text},
    )
    await bus.publish(event)
    return f"Popup shown with title: {title}"