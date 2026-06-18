"""
The `fire_tv` tool — control the Amazon Fire TV Stick via Home Assistant media_player services.
"""

from bus.redis_bus import Bus
from events.schema import Event
from config.settings import FIRE_TV_ENTITY_ID
from tools.home_assistant import _ha_request

_ACTION_TO_SERVICE = {
    "play":          "media_play",
    "pause":         "media_pause",
    "play_pause":    "media_play_pause",
    "stop":          "media_stop",
    "volume_up":     "volume_up",
    "volume_down":   "volume_down",
    "next":          "media_next_track",
    "previous":      "media_previous_track",
    "turn_on":       "turn_on",
    "turn_off":      "turn_off",
}

_APP_SOURCES = {
    "netflix":  "Netflix",
    "prime":    "Prime Video",
    "youtube":  "YouTube",
    "hbo":      "Max",
    "disney":   "Disney+",
    "peacock":  "Peacock",
}


async def control_tv(
    action: str,
    bus: Bus,
    entity_id: str | None = None,
) -> str:
    """
    Control the Fire TV Stick.

    action: play, pause, play_pause, stop, volume_up, volume_down, mute,
            next, previous, turn_on, turn_off
    entity_id: specific HA entity — falls back to FIRE_TV_ENTITY_ID env var.
    """
    target = entity_id or FIRE_TV_ENTITY_ID

    if action == "mute":
        payload = {"entity_id": target, "is_volume_muted": True}
        path = "/api/services/media_player/volume_mute"
    else:
        service = _ACTION_TO_SERVICE.get(action)
        if not service:
            return f"Unknown TV action: {action!r}. Valid: {', '.join(_ACTION_TO_SERVICE)}."
        payload = {"entity_id": target}
        path = f"/api/services/media_player/{service}"

    result = await _ha_request("POST", path, json_body=payload)

    if result is not None:
        await bus.publish(Event(
            type="device_action",
            source="agent",
            payload={"device": target, "action": action, "result": "success"},
        ))
        return f"TV ({target}): {action}."
    else:
        return f"Failed to {action} TV ({target})."


async def launch_tv_app(
    app_name: str,
    bus: Bus,
    entity_id: str | None = None,
) -> str:
    """
    Launch an app on the Fire TV Stick.

    app_name: netflix, prime, youtube, hbo, disney, peacock (case-insensitive).
    entity_id: specific HA entity — falls back to FIRE_TV_ENTITY_ID env var.
    """
    target = entity_id or FIRE_TV_ENTITY_ID
    source = _APP_SOURCES.get(app_name.lower())

    if not source:
        known = ", ".join(_APP_SOURCES)
        return f"Unknown app: {app_name!r}. Known apps: {known}."

    payload = {"entity_id": target, "source": source}
    result = await _ha_request("POST", "/api/services/media_player/select_source", json_body=payload)

    if result is not None:
        await bus.publish(Event(
            type="device_action",
            source="agent",
            payload={"device": target, "action": f"launch:{source}", "result": "success"},
        ))
        return f"Opened {source} on the TV."
    else:
        return f"Failed to open {source} on TV ({target})."
