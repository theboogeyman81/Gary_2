"""
Dev utility: publish a fake event to the bus from the command line.

Usage:
    uv run python -m scripts.publish_event speech "hey gary turn off the lights"
    uv run python -m scripts.publish_event gesture "pinch"
    uv run python -m scripts.publish_event speak "hello there"

This lets us test Gary without real glasses, mics, or cameras.
"""

import asyncio
import sys
from bus.redis_bus import Bus
from events.schema import Event


async def main():
    # Check we got the right number of arguments
    if len(sys.argv) < 3:
        print("Usage: uv run python -m scripts.publish_event <type> <content>")
        print("Examples:")
        print('  uv run python -m scripts.publish_event speech "hey gary"')
        print('  uv run python -m scripts.publish_event gesture "pinch"')
        sys.exit(1)

    event_type = sys.argv[1]
    content = sys.argv[2]

    # Build the payload based on the event type.
    # Different event types have different payload shapes.
    if event_type == "speech":
        payload = {"text": content}
    elif event_type == "gesture":
        payload = {"gesture": content}
    elif event_type == "speak":
        payload = {"text": content}
    elif event_type == "show_popup":
        payload = {"title": "Gary", "text": content}
    elif event_type == "copy_to_clipboard":
        payload = {"text": content}
    elif event_type == "request_screenshot":
        payload = {"reason": content}
    else:
        # Generic fallback
        payload = {"value": content}

    # Connect to the bus and publish.
    bus = Bus()
    await bus.connect()

    event = Event(
        type=event_type,
        source="dev_script",
        payload=payload,
    )

    await bus.publish(event)
    print(f"Published: {event.model_dump_json()}")

    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())