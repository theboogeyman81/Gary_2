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


@dataclass
class GaryDeps:
    """
    Shared state passed to tools.
    
    Anything tools need (bus connection, db connection, etc.) goes here.
    Pydantic AI will inject this into tools that ask for it via RunContext.
    """
    bus: Bus


# The agent itself.
# - model: what LLM to call. TestModel returns fake responses for now.
# - deps_type: the type of the deps object we'll pass at runtime.
# - system_prompt: who Gary is and how to behave.
agent = Agent(
    model=TestModel(),
    deps_type=GaryDeps,
    system_prompt=(
        "You are Gary, a personal assistant living in the user's smart glasses. "
        "Tone: like a friend looking over their shoulder. Casual, sharp, brief. "
        "Never corporate. Never over-explain. "
        "Always keep responses short — they're being spoken out loud. "
        "Use the speak tool to respond to the user."
    ),
)


@agent.tool
async def speak(ctx: RunContext[GaryDeps], text: str) -> str:
    """Say something out loud through the glasses speaker."""
    return await speak_impl(text, ctx.deps.bus)