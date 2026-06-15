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
    if len(sys.argv) < 2:
        print("Usage: uv run python -m scripts.publish_event <type> [content]")
        print("Examples:")
        print('  uv run python -m scripts.publish_event show_listening')
        print('  uv run python -m scripts.publish_event show_thinking')
        print('  uv run python -m scripts.publish_event show_idle')
        print('  uv run python -m scripts.publish_event show_toast "Screenshot taken"')
        print('  uv run python -m scripts.publish_event show_popup "Hello from Gary"')
        print('  uv run python -m scripts.publish_event request_permission "Access microphone"')
        print('  uv run python -m scripts.publish_event speech "hey gary"')
        sys.exit(1)

    event_type = sys.argv[1]
    content = sys.argv[2] if len(sys.argv) >= 3 else ""

    # Build the payload based on the event type.
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
    elif event_type == "show_toast":
        payload = {"message": content}
    elif event_type == "request_permission":
        payload = {"title": content, "description": "Gary is requesting access."}
    # No-content states — content arg is ignored
    elif event_type in {"show_listening", "show_thinking", "show_idle"}:
        payload = {}
    else:
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