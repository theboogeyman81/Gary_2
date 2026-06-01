"""
Gary's laptop companion app.

Runs on the user's work machine. Connects to Gary's bus and:
- Listens for events from the agent (screenshots, popups, clipboard)
- Executes them on the local machine
- Publishes results back to the bus

Run with:
    uv run python -m laptop_app.main
"""

import asyncio
import sys
from PyQt6.QtWidgets import QApplication
import qasync

from bus.redis_bus import Bus
from events.schema import Event
from laptop_app.popup import show_popup


# Event types the laptop app cares about.
LAPTOP_EVENTS = {
    "request_screenshot",
    "show_popup",
    "copy_to_clipboard",
}


# Keep references to open popups so they don't get garbage collected.
_open_popups = []


async def handle_request_screenshot(event: Event) -> None:
    """Placeholder — we'll implement in Session 4."""
    reason = event.payload.get("reason", "no reason given")
    print(f"[laptop_app] 📸 Screenshot requested. Reason: {reason}")
    print(f"[laptop_app]    (not implemented yet — coming Session 4)")


async def handle_show_popup(event: Event) -> None:
    """Show a real popup window with the event's title and text."""
    title = event.payload.get("title", "Gary")
    text = event.payload.get("text", "")
    print(f"[laptop_app] 💬 Popup: [{title}] {text[:60]}")
    
    # Show the popup. Keep reference so it stays alive.
    popup = show_popup(title, text)
    _open_popups.append(popup)


async def handle_copy_to_clipboard(event: Event) -> None:
    """Placeholder — we'll implement in Session 3."""
    text = event.payload.get("text", "")
    preview = text[:50] + "..." if len(text) > 50 else text
    print(f"[laptop_app] 📋 Copy to clipboard: {preview}")
    print(f"[laptop_app]    (not implemented yet — coming Session 3)")


HANDLERS = {
    "request_screenshot": handle_request_screenshot,
    "show_popup": handle_show_popup,
    "copy_to_clipboard": handle_copy_to_clipboard,
}


async def bus_loop():
    """The async loop that subscribes to the bus and dispatches events."""
    bus = Bus()
    await bus.connect()

    print("─" * 80)
    print("  Gary laptop companion app")
    print("  Connected to bus. Waiting for events...")
    print("  Press Ctrl+C to stop")
    print("─" * 80)

    try:
        async for event in bus.subscribe():
            if event.type in LAPTOP_EVENTS:
                handler = HANDLERS.get(event.type)
                if handler:
                    await handler(event)
    finally:
        await bus.close()


def main():
    # Create the Qt application
    app = QApplication(sys.argv)
    
    # Create an event loop that bridges asyncio and Qt
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    # Schedule the bus loop to run alongside Qt's loop
    loop.create_task(bus_loop())
    
    # Run forever (Qt's event loop + asyncio together)
    try:
        with loop:
            loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()