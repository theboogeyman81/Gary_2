"""
The `home_assistant` tool — control smart devices via Home Assistant REST API.

This is the async version of the user's existing HA control code.
"""

import aiohttp
from bus.redis_bus import Bus
from events.schema import Event
from config.settings import HA_URL, HA_TOKEN, ENTITY_ID


# Reusable headers for all HA requests.
HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}


async def _ha_request(method: str, path: str, json_body: dict | None = None) -> dict | None:
    """
    Make an async HTTP request to Home Assistant.
    Returns the response JSON, or None on failure.
    """
    url = f"{HA_URL}{path}"
    timeout = aiohttp.ClientTimeout(total=8)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, url, headers=HEADERS, json=json_body) as response:
                if response.status == 200:
                    # Some endpoints return JSON, some return empty. Try to parse.
                    try:
                        return await response.json()
                    except Exception:
                        return {}
                else:
                    print(f"❌ HA request failed: {response.status}")
                    return None
    except aiohttp.ClientError as exc:
        print(f"❌ HA connection error: {exc}")
        return None


async def get_bulb_state() -> str | None:
    """Get the current state of the bulb ('on' or 'off')."""
    result = await _ha_request("GET", f"/api/states/{ENTITY_ID}")
    if result is None:
        return None
    return result.get("state")


async def control_bulb(action: str, bus: Bus) -> str:
    """
    Control the bulb. action must be 'on', 'off', or 'toggle'.
    
    Use this when the user asks about lights, lamps, or the bulb.
    Examples:
      - "turn on the lights" → action='on'
      - "turn off the bulb" → action='off'
      - "toggle the lamp" → action='toggle'
    """
    # Handle toggle by checking state first.
    if action == "toggle":
        state = await get_bulb_state()
        if state == "on":
            action = "off"
        elif state == "off":
            action = "on"
        else:
            return f"Couldn't determine bulb state to toggle."

    # Now action is 'on' or 'off'.
    if action not in ("on", "off"):
        return f"Invalid action: {action}. Must be 'on', 'off', or 'toggle'."

    path = f"/api/services/light/turn_{action}"
    result = await _ha_request("POST", path, json_body={"entity_id": ENTITY_ID})

    if result is not None:
        # Publish a confirmation event for visibility on the bus.
        await bus.publish(Event(
            type="device_action",
            source="agent",
            payload={
                "device": ENTITY_ID,
                "action": action,
                "result": "success",
            },
        ))
        return f"Bulb turned {action}."
    else:
        return f"Failed to turn bulb {action}."