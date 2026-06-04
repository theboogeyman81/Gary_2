# GARY — Laptop Companion App

## What this is
Gary is an ambient AI assistant for smart glasses that extends to the laptop.
It's event-driven: pipelines publish events to a Redis pub/sub bus; a Pydantic AI
agent reasons and calls tools. THIS app — the laptop companion — is one bus client.
It subscribes to events (show_popup, request_screenshot, copy_to_clipboard),
shows ambient UI, and publishes results back.

Design philosophy: "a presence, not an app." Minimal, restrained, ambient.
Visual signature: a quarter-circle arc anchored to the bottom-right corner.

## Where work happens — and what NOT to touch
ONLY work inside `laptop_app/web/` and `laptop_app/main_pywebview.py`.
DO NOT touch: agent/, bus/, pipelines/, tools/, memory/, events/schema.py,
config/. The old PyQt6 files (laptop_app/main.py, popup.py) are reference only —
do not run or edit them. laptop_app/screenshot.py (mss-based) is still used.

## Tech stack
Python 3.11+ managed by `uv`. Redis pub/sub. Pydantic event schemas.
pywebhe UI (HTML/CSS/JS in laptop_app/web/). Replacing the old PyQt6 app.

## Event schema (events/schema.py — read-only)
Event(type: str, timestamp: float, source: str, payload: dict). One Redis
channel: "events". Laptop app listens for show_popup {title, text},
request_screenshot {reason}, copy_to_clipboard {text}. It publishes
screenshot_taken, permission_granted, permission_denied.

## pywebview architecture
pywebview owns the main thread. The async bus subscriber runs in a background
thread. Python → JS via window.evaluate_js("renderCard(...)"). JS → Python via
pywebview.api.* methods. Window is frameless, transparent, on_top — an invisible
full-screen overlay; only the components are visible.

## CSS conventions — read carefully
- gary.css (in web/assets/) is the source of truth for all styling. Render
  against it; do not restyle components or invent new CSS.
- Use the `.g-` NAMESPACED classes from gary.css (.g-indicator, .g-card, etc.).
  The Gary_UI.html reference file uses NON-namespaced demo ignore those
  class names, they are not what we ship.
- gary.css has NO `.expanded` state. Manage showing/hiding the indicator vs.
  the card yourself in app.js.
- The fixed-height card is `.g-card[data-h]` (add the data-h attribute).
- Clipboard: route through the Python bridge (pywebview.api.copy_to_clipboard),
  NOT navigator.clipboard — it's unreliable inside a webview.

## How to work here
Small steps, one piece at a time. Explain patterns by name (decorators,
generators, threading model) as they come up — the developer is learning.
When something breaks, debug it; don't rewrite from scratch. UI polish matters
(exhibition in July).

## Dev testing (three terminals)
1. `uv run python -m scripts.monitor_bus`
2. `uv run python -m laptop_app.main_pywebview`
3. `uv run python -m scripts.publish_event show_popup "Test message"`
