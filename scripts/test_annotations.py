"""Quick test: fire show_annotations directly at the overlay."""
import asyncio
from bus.redis_bus import Bus
from events.schema import Event


async def main():
    bus = Bus()
    await bus.connect()
    await bus.publish(Event(
        type="show_annotations",
        source="test",
        payload={"points": [
            {"x": 0.25, "y": 0.35, "label": "missing return"},
            {"x": 0.55, "y": 0.65, "label": "typo totall"},
            {"x": 0.70, "y": 0.20, "label": "string not int"},
        ]},
    ))
    print("Published show_annotations with 3 points")
    await bus.close()


asyncio.run(main())
