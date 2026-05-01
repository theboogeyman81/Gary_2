"""
Gary's brain — a Pydantic AI agent.

The agent has:
- A system prompt (who Gary is)
- Tools (functions it can call)
- A model (the LLM)

For now we use a 'test' model that returns canned responses.
We'll swap in Claude when we have the API key.
"""

from dataclasses import dataclass
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

from bus.redis_bus import Bus
from tools.speak import speak as speak_impl
from tools.request_screenshot import request_screenshot as request_screenshot_impl
from tools.show_popup import show_popup as show_popup_impl
from tools.copy_to_clipboard import copy_to_clipboard as copy_to_clipboard_impl


@dataclass
class GaryDeps:
    """Shared state passed to tools."""
    bus: Bus


agent = Agent(
    model=TestModel(),
    deps_type=GaryDeps,
    system_prompt=(
        "You are Gary, a personal assistant living in the user's smart glasses. "
        "Tone: like a friend looking over their shoulder. Casual, sharp, brief. "
        "Never corporate. Never over-explain. "
        "Always keep responses short — they're being spoken out loud. "
        "\n\n"
        "You have these tools:\n"
        "- speak: say something out loud (use this for short replies)\n"
        "- request_screenshot: ask the laptop to capture the screen\n"
        "- show_popup: show text on the laptop screen\n"
        "- copy_to_clipboard: copy text so the user can paste it\n"
        "\n"
        "When the user asks for a prompt, code, or anything they'll paste elsewhere, "
        "use show_popup AND copy_to_clipboard together, then speak a short confirmation."
    ),
)


@agent.tool
async def speak(ctx: RunContext[GaryDeps], text: str) -> str:
    """Say something out loud through the glasses speaker. Keep it brief."""
    return await speak_impl(text, ctx.deps.bus)


@agent.tool
async def request_screenshot(ctx: RunContext[GaryDeps], reason: str) -> str:
    """Ask the laptop to take a screenshot of the current screen."""
    return await request_screenshot_impl(reason, ctx.deps.bus)


@agent.tool
async def show_popup(ctx: RunContext[GaryDeps], text: str, title: str = "Gary") -> str:
    """Show a popup on the laptop screen with the given text."""
    return await show_popup_impl(text, ctx.deps.bus, title)


@agent.tool
async def copy_to_clipboard(ctx: RunContext[GaryDeps], text: str) -> str:
    """Copy text to the user's clipboard."""
    return await copy_to_clipboard_impl(text, ctx.deps.bus)