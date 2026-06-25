"""
Gesture correlator — joins POV and hand pipeline events into gesture commands.

Subscribes to the bus and maintains the set of devices currently in view.
When a pinch_detected arrives:
  - No devices in view → drop silently.
  - One or more devices in view → pick the one with the largest bounding box
    area, publish gesture_command, then apply a cooldown.

Run standalone:
    uv run python -m pipelines.gesture_correlator

Manual test (three terminals):
  1. uv run python -m scripts.monitor_bus
  2. uv run python -m pipelines.gesture_correlator
  3. uv run python -m scripts.publish_event device_entered_view '{"device_id":"light.bedroom_lamp","friendly_name":"bedroom lamp","bbox":[100,100,200,150],"confidence":0.9,"detected_via":"aruco"}'
     uv run python -m scripts.publish_event pinch_detected '{"confidence":0.95,"hand":"right"}'
"""

import asyncio
import time

from bus.redis_bus import Bus
from config.settings import GESTURE_COOLDOWN_MS
from events.schema import Event


async def run(bus: Bus) -> None:
    # Maps device_id → most recent device_entered_view payload (includes bbox).
    in_view: dict[str, dict] = {}
    last_fire_time: float = 0.0

    async for event in bus.subscribe():
        if event.type == "device_entered_view":
            did = event.payload.get("device_id", "")
            if did:
                in_view[did] = event.payload
                print(f"[correlator] in_view +{did} (total: {len(in_view)})")

        elif event.type == "device_left_view":
            did = event.payload.get("device_id", "")
            in_view.pop(did, None)
            print(f"[correlator] in_view -{did} (total: {len(in_view)})")

        elif event.type in ("pinch_detected", "slide_detected"):
            if not in_view:
                print(f"[correlator] {event.type} — no device in view, dropped")
                continue

            now_ms = time.monotonic() * 1000
            if now_ms - last_fire_time < GESTURE_COOLDOWN_MS:
                remaining = GESTURE_COOLDOWN_MS - (now_ms - last_fire_time)
                print(f"[correlator] {event.type} — cooldown active ({remaining:.0f}ms remaining), dropped")
                continue

            # Pick device with largest bbox area (w * h)
            best_id = max(
                in_view,
                key=lambda did: in_view[did].get("bbox", [0, 0, 0, 0])[2]
                * in_view[did].get("bbox", [0, 0, 0, 0])[3],
            )
            best = in_view[best_id]

            is_slide = event.type == "slide_detected"
            last_fire_time = now_ms
            await bus.publish(Event(
                type="gesture_command",
                source="gesture_correlator",
                payload={
                    "device_id": best_id,
                    "friendly_name": best.get("friendly_name", best_id),
                    "gesture": "slide_down" if is_slide else "pinch",
                    "implied_intent": "reduce" if is_slide else "toggle",
                },
            ))
            print(f"[correlator] gesture_command ({event.type}) → {best.get('friendly_name', best_id)}")


async def main() -> None:
    bus = Bus()
    backoff = 1.0
    while True:
        try:
            await bus.connect()
            print("[correlator] Connected — waiting for device_entered_view and pinch_detected")
            await run(bus)
        except Exception as exc:
            print(f"[correlator] Error: {exc}. Reconnecting in {backoff:.0f}s ...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        finally:
            await bus.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
