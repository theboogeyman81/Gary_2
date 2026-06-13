import asyncio
from tools.home_assistant import get_bulb_state, control_bulb
from bus.redis_bus import Bus


async def test():
    state = await get_bulb_state("light.smart_bulb_12_5w_2")
    print("Current state:", state)

    bus = Bus()
    await bus.connect()
    result = await control_bulb("toggle", bus, entity_id="light.smart_bulb_12_5w_2")
    print("Result:", result)
    await bus.close()


asyncio.run(test())
