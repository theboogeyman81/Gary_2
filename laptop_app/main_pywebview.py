"""
Gary laptop companion — pywebview edition.

Launches a frameless, transparent, always-on-top overlay window that loads
laptop_app/web/index.html. The async Redis bus subscriber runs in a background
thread so it never blocks the GUI.

Python → JS:  window.evaluate_js("gary.renderCard(...)")
JS → Python:  pywebview.api.*  (methods on PythonAPI below)

Run with:
    uv run python -m laptop_app.main_pywebview
"""

import asyncio
import json
import subprocess
import threading
from pathlib import Path

import webview

from bus.redis_bus import Bus
from events.schema import Event
from laptop_app.screenshot import capture_screen


INDEX_HTML = Path(__file__).parent / "web" / "index.html"

LAPTOP_EVENTS = {"show_popup", "request_screenshot", "copy_to_clipboard", "request_permission"}


# ---------------------------------------------------------------------------
# JS → Python bridge
# ---------------------------------------------------------------------------

class PythonAPI:
    """
    Every public method here becomes callable from JS as pywebview.api.<method>.
    pywebview runs these in a worker thread, not the main thread.
    """

    def copy_to_clipboard(self, text: str) -> None:
        subprocess.run(["pbcopy"], input=text.encode())
        print(f"[gary] 📋 copied: {text[:60]}")

    def permission_response(self, allowed: bool) -> None:
        event_type = "permission_granted" if allowed else "permission_denied"
        print(f"[gary] {'✅' if allowed else '❌'} {event_type}")
        threading.Thread(
            target=lambda: asyncio.run(_publish_permission(event_type)),
            daemon=True,
        ).start()



# ---------------------------------------------------------------------------
# Click-through: let the desktop show through transparent areas
# ---------------------------------------------------------------------------

# Keeps the NSTimer target alive (otherwise Cocoa may GC it).
_hot_zone_monitor: object | None = None


def _setup_click_through(window: webview.Window, screen_w: int) -> None:
    """
    Called from on_shown, which pywebview fires on a background thread.
    All NSWindow/NSTimer operations are therefore dispatched to the main thread
    via AppHelper.callAfter — calling them directly crashes on macOS 26.
    """
    import objc
    from AppKit import NSApplication, NSColor, NSEvent, NSObject, NSTimer
    from PyObjCTools import AppHelper

    global _hot_zone_monitor

    app = NSApplication.sharedApplication()
    ns_window = app.keyWindow() or app.windows()[0]
    if ns_window is None:
        raise RuntimeError("NSWindow not ready")

    HOT_W, HOT_H = 420, 360

    class HotZoneMonitor(NSObject):
        def initWithWindow_screenWidth_hotWidth_hotHeight_(  # noqa: N802
            self, ns_win, screen_width, hot_w, hot_h
        ):
            self = objc.super(HotZoneMonitor, self).init()
            if self is None:
                return None
            self._ns_window = ns_win
            self._screen_w = screen_width
            self._hot_w = hot_w
            self._hot_h = hot_h
            self._interactive = False
            return self

        def tick_(self, _timer):  # noqa: N802
            loc = NSEvent.mouseLocation()
            want = loc.x >= self._screen_w - self._hot_w and loc.y <= self._hot_h
            if want == self._interactive:
                return
            self._interactive = want
            self._ns_window.setIgnoresMouseEvents_(not want)

    monitor = HotZoneMonitor.alloc().initWithWindow_screenWidth_hotWidth_hotHeight_(
        ns_window, screen_w, HOT_W, HOT_H
    )
    _hot_zone_monitor = monitor

    def _on_main():
        try:
            # Transparency — access the WKWebView directly from pywebview's
            # internal registry instead of walking the view tree (more reliable
            # on macOS 26 where the class hierarchy may differ).
            from webview.platforms.cocoa import BrowserView
            instance = next(iter(BrowserView.instances.values()), None)
            if instance is not None:
                instance.webview.setValue_forKey_(False, 'drawsBackground')
                print("[gary] WKWebView drawsBackground cleared.", flush=True)

            ns_window.setOpaque_(False)
            ns_window.setBackgroundColor_(NSColor.clearColor())

            # Click-through: default to ignoring mouse events; the timer
            # re-enables them while the cursor is in the hot zone.
            ns_window.setIgnoresMouseEvents_(True)
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.05, monitor, "tick:", None, True
            )
            print(
                f"[gary] Overlay ready — click-through on, hot zone {HOT_W}×{HOT_H}px",
                flush=True,
            )
        except Exception as e:
            print(f"[gary] ⚠️  _on_main failed: {e}", flush=True)

    AppHelper.callAfter(_on_main)


# ---------------------------------------------------------------------------
# Bus event handling
# ---------------------------------------------------------------------------

async def _publish_permission(event_type: str) -> None:
    bus = Bus()
    await bus.connect()
    await bus.publish(Event(type=event_type, source="laptop_app", payload={}))
    await bus.close()


async def dispatch(event: Event, window: webview.Window, bus: Bus) -> None:
    if event.type == "show_popup":
        title = event.payload.get("title", "Gary")
        text = event.payload.get("text", "")
        print(f"[gary] 💬 show_popup: {title}")
        # json.dumps produces a safe, quoted JS string literal — handles quotes,
        # newlines, and Unicode without any manual escaping.
        # Indicator first; user taps the arc to open the card (PyQt flow).
        window.evaluate_js(
            f"gary.queuePopup({json.dumps(title)}, {json.dumps(text)})"
        )

    elif event.type == "request_screenshot":
        reason = event.payload.get("reason", "")
        print(f"[gary] 📸 screenshot requested: {reason}")
        try:
            # capture_screen() is blocking (mss + Pillow); run it in a thread
            # pool so it doesn't stall the event loop.
            result = await asyncio.to_thread(capture_screen)
            await bus.publish(Event(
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
            print(f"[gary]    captured {result['width']}x{result['height']}")
        except Exception as e:
            print(f"[gary]    ❌ screenshot failed: {e}")
            await bus.publish(Event(
                type="screenshot_failed",
                source="laptop_app",
                payload={"error": str(e), "reason": reason},
            ))

    elif event.type == "request_permission":
        title = event.payload.get("title", "Permission required")
        description = event.payload.get("description", "")
        print(f"[gary] 🔐 permission request: {title}")
        window.evaluate_js(
            f"gary.showPermission({json.dumps(title)}, {json.dumps(description)})"
        )

    elif event.type == "copy_to_clipboard":
        text = event.payload.get("text", "")
        if text:
            subprocess.run(["pbcopy"], input=text.encode())
            print(f"[gary] 📋 clipboard (bus): {text[:60]}")


async def bus_loop(window: webview.Window) -> None:
    bus = Bus()
    try:
        await bus.connect()
    except Exception as e:
        print(f"[gary] ⚠️  Redis unavailable: {e}")
        return

    print("[gary] Connected to bus. Waiting for events...", flush=True)
    try:
        async for event in bus.subscribe():
            if event.type in LAPTOP_EVENTS:
                await dispatch(event, window, bus)
    finally:
        await bus.close()


def _run_bus(window: webview.Window) -> None:
    """Entry point for the background daemon thread."""
    asyncio.run(bus_loop(window))


# ---------------------------------------------------------------------------
# Window setup and click-through setup
# ---------------------------------------------------------------------------

def main() -> None:
    # Read the real screen dimensions before pywebview starts so the overlay
    # covers the primary display exactly. webview.screens isn't reliable until
    # after start(), so we ask AppKit directly.
    try:
        from AppKit import NSScreen
        frame = NSScreen.mainScreen().frame()
        w, h = int(frame.size.width), int(frame.size.height)
    except Exception:
        w, h = 1920, 1080

    api = PythonAPI()

    window = webview.create_window(
        "Gary",
        str(INDEX_HTML),
        js_api=api,
        width=w,
        height=h,
        x=0,
        y=0,
        frameless=True,
        on_top=True,
        # transparent=True is intentionally OMITTED. In pywebview 6.2.1 on
        # macOS 26 it calls _setDrawsTransparentBackground: via KVC key
        # 'drawsTransparentBackground', which Apple turned into a fatal
        # exception in macOS 26. We apply transparency ourselves in on_shown
        # using the modern 'drawsBackground' key instead.
    )

    click_through_ready = False

    def on_loaded():
        print("[gary] UI loaded.", flush=True)
        threading.Thread(target=_run_bus, args=(window,), daemon=True).start()

    def on_shown():
        nonlocal click_through_ready
        if click_through_ready:
            return
        click_through_ready = True
        try:
            _setup_click_through(window, w)
        except Exception as e:
            print(f"[gary] ⚠️  Click-through failed: {e}", flush=True)
            print(
                "[gary]    Overlay will block clicks until this is fixed.",
                flush=True,
            )

    window.events.loaded += on_loaded
    window.events.shown += on_shown

    print(f"[gary] Starting overlay ({w}×{h})…", flush=True)
    webview.start(http_server=True)


if __name__ == "__main__":
    main()




