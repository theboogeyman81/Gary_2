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
from tools.home_assistant import control_bulb as control_bulb_impl
from tools.fire_tv import control_tv as control_tv_impl

_local_states: dict[str, bool] = {}   # device_id → True = on/playing
_local_levels: dict[str, int] = {}    # device_id → brightness/volume 0-100


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


async def handle_gesture_command(event: Event, deps: GaryDeps) -> None:
    """Handle a gesture_command — show a demo toast then attempt HA (silently)."""
    entity_id = event.payload.get("device_id", "")
    friendly_name = event.payload.get("friendly_name", entity_id)
    gesture = event.payload.get("gesture", "pinch")

    if gesture == "slide_down":
        # Reduce brightness/volume by 20%, cycling back to 100% after 20%
        current = _local_levels.get(entity_id, 100)
        new_level = current - 20 if current > 20 else 100
        _local_levels[entity_id] = new_level
        if entity_id.startswith("media_player."):
            message = f"{friendly_name} — volume {new_level}%"
        else:
            message = f"{friendly_name} — brightness {new_level}%"
    else:
        # Pinch → toggle on/off
        _local_states[entity_id] = not _local_states.get(entity_id, False)
        new_state = _local_states[entity_id]
        if entity_id.startswith("media_player."):
            message = f"{friendly_name} — {'playing' if new_state else 'paused'}"
        else:
            message = f"{friendly_name} — turned {'on' if new_state else 'off'}"

    await deps.bus.publish(Event(
        type="show_toast",
        source="agent",
        payload={"message": message, "duration": 3000},
    ))
    print(f"[main_loop] Gesture ({gesture}): {entity_id} → {message}")

    # Attempt real HA call — fails gracefully when HA is unavailable (exhibition)
    try:
        if gesture == "slide_down":
            pass  # HA brightness/volume control not wired for demo
        elif entity_id.startswith("media_player."):
            await control_tv_impl("play_pause", deps.bus, entity_id=entity_id)
        else:
            await control_bulb_impl("toggle", deps.bus, entity_id=entity_id)
    except Exception as exc:
        print(f"[main_loop] HA skipped: {exc}")


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
            elif event.type == "gesture_command":
                await handle_gesture_command(event, deps)
    except KeyboardInterrupt:
        pass
    finally:
        await bus.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass