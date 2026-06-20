"""Full pipeline test: screenshot → Gemini Vision → annotation rings on overlay."""
import asyncio
from bus.redis_bus import Bus
from tools.annotate import annotate_screen


async def main():
    bus = Bus()
    await bus.connect()
    print("Taking screenshot and sending to Gemini...")
    result = await annotate_screen(bus)
    print(f"Spoken result: {result}")
    await bus.close()


asyncio.run(main())
