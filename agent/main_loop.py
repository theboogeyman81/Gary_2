"""
Gary's main loop.

This is the long-running process that:
1. Subscribes to the bus
2. Listens for events that need reasoning (e.g. 'speech')
3. Calls the agent to think about them
4. The agent's tools publish action events back to the bus

Run it with:
    uv run python -m agent.main_loop
"""

import asyncio
from bus.redis_bus import Bus
from events.schema import Event
from agent.gary_agent import agent, GaryDeps
from memory.store import init_db


async def handle_speech(event: Event, deps: GaryDeps) -> None:
    """Handle a speech event — send the text to the agent for reasoning."""
    text = event.payload.get("text", "")
    if not text:
        return
    
    print(f"[main_loop] User said: {text!r}")
    
    # Run the agent. It will think and call tools (like speak).
    # Tools publish events back to the bus on their own.
    result = await agent.run(text, deps=deps)
    
    print(f"[main_loop] Agent done. Final output: {result.output!r}")


async def main():
    bus = Bus()
    await bus.connect()
    await init_db()
    
    deps = GaryDeps(bus=bus)
    
    print("─" * 80)
    print("  Gary main loop — agent is alive")
    print("  Press Ctrl+C to stop")
    print("─" * 80)
    
    try:
        async for event in bus.subscribe():
            # We only care about events that need reasoning.
            # For now: speech events.
            if event.type == "speech":
                await handle_speech(event, deps)
            # Other event types we ignore for now.
    except KeyboardInterrupt:
        pass
    finally:
        await bus.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass