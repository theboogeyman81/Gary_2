"""
The `request_screenshot` tool.

When the agent calls this, it publishes a 'request_screenshot' event.
The laptop companion app (later) will:
  1. Receive this event
  2. Show a permission popup to the user
  3. Capture the screen
  4. Publish a 'screenshot_taken' event with the image
"""

from bus.redis_bus import Bus
from events.schema import Event


async def request_screenshot(reason: str, bus: Bus) -> str:
    """
    Ask the laptop to take a screenshot of the current screen.
    
    Use when you need to see what the user is looking at on their monitor —
    for example, to generate a prompt about a design they're working on,
    or to help them with something visible in their code editor.
    """
    event = Event(
        type="request_screenshot",
        source="agent",
        payload={"reason": reason},
    )
    await bus.publish(event)
    return f"Screenshot requested. Reason: {reason}"