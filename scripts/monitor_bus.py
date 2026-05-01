"""
Dev utility: watch all events flowing through the bus, live.

Usage:
    uv run python -m scripts.monitor_bus

Keep this running in a side terminal during development.
You'll see every event published by any pipeline, the agent, or tools.
"""

import asyncio
from datetime import datetime
from bus.redis_bus import Bus


# ANSI color codes for prettier output in the terminal.
# We color-code by source so it's easy to see who published what.
COLORS = {
    "voice_pipeline":  "\033[36m",  # cyan
    "hand_pipeline":   "\033[35m",  # magenta
    "pov_pipeline":    "\033[33m",  # yellow
    "agent":           "\033[32m",  # green
    "dev_script":      "\033[37m",  # white/grey
    "laptop_app":      "\033[34m",  # blue
}
RESET = "\033[0m"
DIM = "\033[2m"


def format_event(event) -> str:
    """Format an event for pretty terminal output."""
    color = COLORS.get(event.source, RESET)
    timestamp = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")
    
    return (
        f"{DIM}[{timestamp}]{RESET} "
        f"{color}{event.source:<16}{RESET} "
        f"→ {event.type:<20} "
        f"{DIM}{event.payload}{RESET}"
    )


async def main():
    bus = Bus()
    await bus.connect()
    
    print("─" * 80)
    print("  Gary bus monitor — watching all events")
    print("  Press Ctrl+C to stop")
    print("─" * 80)
    
    try:
        async for event in bus.subscribe():
            print(format_event(event))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(main())