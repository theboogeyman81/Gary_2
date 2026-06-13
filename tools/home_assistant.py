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


async def get_bulb_state(target_entity_id: str | None = None) -> str | None:
    """Get the current state of an entity ('on' or 'off'). Defaults to ENTITY_ID from config."""
    eid = target_entity_id or ENTITY_ID
    result = await _ha_request("GET", f"/api/states/{eid}")
    if result is None:
        return None
    return result.get("state")


async def control_bulb(
    action: str,
    bus: Bus,
    area: str | None = None,
    entity_id: str | None = None,
) -> str:
    """
    Control lights. action must be 'on', 'off', or 'toggle'.

    Target priority: entity_id > area > default ENTITY_ID from config.
      entity_id: a specific HA entity (e.g. 'light.smart_bulb_12_5w_2') — used by gesture pipeline
      area: an HA area_id (e.g. 'bedroom') — used for voice commands like "bedroom lights"
      (neither): falls back to the ENTITY_ID env var

    Examples:
      - "turn on the lights" → action='on'
      - "turn off my room lights" → action='off', area='my_room'
      - gesture toggle → action='toggle', entity_id='light.smart_bulb_12_5w_2'
    """
    # Resolve the target entity first so toggle queries the right state.
    resolved_entity = entity_id or ENTITY_ID
    if action == "toggle":
        state = await get_bulb_state(resolved_entity)
        if state == "on":
            action = "off"
        elif state == "off":
            action = "on"
        else:
            return "Couldn't determine light state to toggle."

    if action not in ("on", "off"):
        return f"Invalid action: {action}. Must be 'on', 'off', or 'toggle'."

    # Build payload — entity_id > area > default ENTITY_ID
    if entity_id:
        payload = {"entity_id": entity_id}
        target_label = entity_id
    elif area:
        payload = {"area_id": area}
        target_label = f"area:{area}"
    else:
        payload = {"entity_id": resolved_entity}
        target_label = resolved_entity

    path = f"/api/services/light/turn_{action}"
    result = await _ha_request("POST", path, json_body=payload)

    if result is not None:
        await bus.publish(Event(
            type="device_action",
            source="agent",
            payload={
                "device": target_label,
                "action": action,
                "result": "success",
            },
        ))
        return f"Lights ({target_label}) turned {action}."
    else:
        return f"Failed to turn lights {action}."