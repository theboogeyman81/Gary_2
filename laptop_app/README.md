# Gary Laptop App — Frontend

## Tech stack

| Layer | What |
|---|---|
| Window | **pywebview 6** — frameless, transparent, always-on-top overlay |
| UI | Plain **HTML / CSS / JS** in `laptop_app/web/` |
| Styles | `web/assets/gary.css` — namespaced `.g-` component kit |
| Logic | `web/assets/app.js` — vanilla JS, no frameworks |
| Fonts | Hanken Grotesk + JetBrains Mono via Google Fonts |
| Bus | **Redis pub/sub** — one channel `"events"` |
| Entry point | `laptop_app/main_pywebview.py` |

---

## How it works, A → Z

### 1. Boot
`uv run python -m laptop_app.main_pywebview` starts the process.
- `NSScreen` (AppKit) reads the primary display size before pywebview initialises.
- A **pywebview window** is created: frameless, `on_top=True`, no native chrome.
- pywebview serves `laptop_app/web/` over a local HTTP server (`http_server=True`) to avoid WKWebView's `file://` security restrictions.

### 2. Page load
`web/index.html` loads inside the WKWebView:
- Inline `<style>` resets `html, body` to `background: transparent; margin: 0`.
- Google Fonts are preconnected and loaded.
- `gary.css` is linked.
- `app.js` is deferred.

### 3. First render (`app.js` boot)
As soon as `app.js` runs, it calls `window.gary.renderIndicator()`, which injects
the arc indicator HTML into `.g-overlay`. The page is never a blank pane.

### 4. Transparency + click-through (macOS 26 fix)
In `on_shown` (fires after the window appears), `AppHelper.callAfter` dispatches
to the main Cocoa thread:
- `ns_window.setOpaque_(False)` + `setBackgroundColor_(clearColor)` — transparent frame.
- `wkwebview.setValue_forKey_(False, 'drawsBackground')` — stops WKWebView painting
  a white background. (pywebview's built-in `transparent=True` used the now-fatal
  `_setDrawsTransparentBackground:` private API on macOS 26, so we bypass it.)
- `NSTimer` polls cursor position every 50 ms. Outside the 420×360 px bottom-right
  **hot zone**: `setIgnoresMouseEvents_(True)` — clicks pass through to the desktop.
  Inside the hot zone: events are enabled so Gary is interactive.

### 5. Bus events → UI
`main_pywebview.py` runs an async Redis subscriber on a **daemon thread**:

| Event | What Python does |
|---|---|
| `show_popup` | `window.evaluate_js("gary.queuePopup(title, text)")` |
| `request_screenshot` | `capture_screen()` in a thread pool → publishes `screenshot_taken` |
| `copy_to_clipboard` | `pbcopy` subprocess |

`evaluate_js` is thread-safe in pywebview — it queues the call on the main thread.

### 6. JS state machine (app.js)
Three states, one `.g-overlay` div:

```
idle            → gary.renderIndicator()   shows the arc
arc clicked     → gary.renderCard()        shows the card
card X button   → gary.renderIndicator()   back to arc
```

`_lastCard` stores the last `{title, text}` so the arc always re-opens the most recent message.

### 7. JS → Python (copy button)
The card's Copy button calls `pywebview.api.copy_to_clipboard(text)`, which
routes to `PythonAPI.copy_to_clipboard` and runs `pbcopy`. Browser
`navigator.clipboard` is not used — it's unreliable inside a WKWebView.

---

## Dev testing

```bash
# Terminal 1 — watch the bus
uv run python -m scripts.monitor_bus

# Terminal 2 — run the overlay
uv run python -m laptop_app.main_pywebview

# Terminal 3 — fire a test event
uv run python -m scripts.publish_event show_popup "Test message"
```

Open `laptop_app/web/index.html?dev` in a browser for CSS/JS work without
running pywebview (`?dev` adds a dark background so the overlay is visible).
