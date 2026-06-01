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
# Module-level bus reference, set in bus_loop().
_bus: Bus | None = None

async def handle_request_screenshot(event: Event) -> None:
    """Capture the screen and publish a screenshot_taken event back to the bus."""
    from laptop_app.screenshot import capture_screen
    
    reason = event.payload.get("reason", "no reason given")
    print(f"[laptop_app] 📸 Screenshot requested. Reason: {reason}")
    
    try:
        # Run the blocking screenshot in a thread so we don't block the event loop
        result = await asyncio.to_thread(capture_screen)
        print(f"[laptop_app]    Captured {result['width']}x{result['height']} → {result['path']}")
        
        # Publish back to the bus so the agent knows the screenshot is ready
        await _bus.publish(Event(
            type="screenshot_taken",
            source="laptop_app",
            payload={
                "path": result["path"],
                "base64": result["base64"],
                "width": result["width"],
                "height": result["height"],
                "reason": reason,
            },
        ))
    except Exception as e:
        print(f"[laptop_app]    ❌ Screenshot failed: {e}")
        await _bus.publish(Event(
            type="screenshot_failed",
            source="laptop_app",
            payload={"error": str(e), "reason": reason},
        ))


async def handle_show_popup(event: Event) -> None:
    """Show a real popup window with the event's title and text."""
    import traceback
    title = event.payload.get("title", "Gary")
    text = event.payload.get("text", "")
    print(f"[laptop_app] 💬 Popup: [{title}] {text[:60]}")
    
    try:
        popup = show_popup(title, text)
        _open_popups.append(popup)
        print(f"[laptop_app]    Popup created: {popup}")
    except Exception as e:
        print(f"[laptop_app]    ❌ Popup error: {e}")
        traceback.print_exc()

        
async def handle_copy_to_clipboard(event: Event) -> None:
    """Write the event's text to the system clipboard."""
    from PyQt6.QtWidgets import QApplication
    
    text = event.payload.get("text", "")
    if not text:
        print("[laptop_app] 📋 Copy requested but no text provided")
        return
    
    clipboard = QApplication.clipboard()
    clipboard.setText(text)
    
    preview = text[:50] + "..." if len(text) > 50 else text
    print(f"[laptop_app] 📋 Copied to clipboard: {preview}")


HANDLERS = {
    "request_screenshot": handle_request_screenshot,
    "show_popup": handle_show_popup,
    "copy_to_clipboard": handle_copy_to_clipboard,
}


async def bus_loop():
    """The async loop that subscribes to the bus and dispatches events."""
    global _bus
    _bus = Bus()
    await _bus.connect()

    print("─" * 80)
    print("  Gary laptop companion app")
    print("  Connected to bus. Waiting for events...")
    print("  Press Ctrl+C to stop")
    print("─" * 80)

    try:
        async for event in _bus.subscribe():
            if event.type in LAPTOP_EVENTS:
                handler = HANDLERS.get(event.type)
                if handler:
                    await handler(event)
    finally:
        await _bus.close()


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