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
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from bus.redis_bus import Bus
from tools.speak import speak as speak_impl
from tools.request_screenshot import request_screenshot as request_screenshot_impl
from tools.show_popup import show_popup as show_popup_impl
from tools.copy_to_clipboard import copy_to_clipboard as copy_to_clipboard_impl
from tools.home_assistant import control_bulb as control_bulb_impl
from tools.play_music import play_music as play_music_impl
from tools.memory import (
    remember as remember_impl,
    recall as recall_impl,
    forget as forget_impl,
)


@dataclass
class GaryDeps:
    """Shared state passed to tools."""
    bus: Bus


agent = Agent(
     model=OpenAIModel(
        model_name="qwen2.5:3b",
        provider=OpenAIProvider(base_url="http://localhost:11434/v1"),
    ),
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
        "- control_bulb: turn the smart bulb on, off, or toggle it\n"
        "- play_music: open YouTube Music and play a song\n"
        "- remember: save a fact when the user tells you to\n"
        "- recall: search for facts you've saved\n"
        "- forget: delete a saved fact by ID\n"
        "\n"
        "When the user asks for a prompt, code, or anything they'll paste elsewhere, "
        "use show_popup AND copy_to_clipboard together, then speak a short confirmation. "
        "When the user asks about lights, the bulb, or the lamp, use control_bulb. "
        "When the user says 'play', 'put on', or asks to listen to a song or artist, use play_music. "
        "When the user says 'remember' or 'save', use the remember tool. "
        "When the user asks 'what did I say about...', 'what do I prefer...', use recall."
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


@agent.tool
async def control_bulb(ctx: RunContext[GaryDeps], action: str, area: str | None = None) -> str:
    """Control lights. action must be 'on', 'off', or 'toggle'.
    area is the room name: 'my_room', 'bedroom', 'living_room', 'kitchen'.
    If the user mentions a room, always pass the area. Otherwise leave it None."""
    return await control_bulb_impl(action, ctx.deps.bus, area)


@agent.tool
async def remember(ctx: RunContext[GaryDeps], fact: str, category: str = "general") -> str:
    """Save a fact about the user to long-term memory."""
    return await remember_impl(fact, category)


@agent.tool
async def recall(ctx: RunContext[GaryDeps], query: str) -> str:
    """Search long-term memory for facts matching a query."""
    return await recall_impl(query)


@agent.tool
async def forget(ctx: RunContext[GaryDeps], memory_id: int) -> str:
    """Delete a memory by its ID."""
    return await forget_impl(memory_id)


@agent.tool
async def play_music(ctx: RunContext[GaryDeps], song: str) -> str:
    """Open YouTube Music in Chrome and play the given song or artist."""
    return await play_music_impl(song, ctx.deps.bus)