"""
The `play_music` tool.

Opens YouTube Music in Chrome, searches for the song, then uses
AppleScript to inject JavaScript and click the first result.
macOS + Chrome only.
"""

import asyncio
import subprocess
from urllib.parse import quote


async def play_music(song: str, bus) -> str:
    url = f"https://music.youtube.com/search?q={quote(song)}"

    # Open in Chrome and bring it to the front
    subprocess.Popen(["open", "-a", "Google Chrome", url])

    # Wait for the page to load and results to render
    await asyncio.sleep(5)

    # Click the first song row via AppleScript → JS
    js = (
        "var row = document.querySelector("
        "'ytmusic-shelf-renderer ytmusic-responsive-list-item-renderer');"
        "if (row) { row.click(); }"
    )
    applescript = (
        f'tell application "Google Chrome"\n'
        f'    activate\n'
        f'    execute front window\'s active tab javascript "{js}"\n'
        f'end tell'
    )
    subprocess.run(["osascript", "-e", applescript], capture_output=True)

    return f"Playing: {song}"
