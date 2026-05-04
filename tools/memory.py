"""
Memory tools — let the agent save, find, and forget facts about the user.

All three tools wrap the memory store in tools/memory.py-friendly form.
"""

from memory.store import (
    add_memory as add_memory_impl,
    search_memories as search_memories_impl,
    delete_memory as delete_memory_impl,
)


async def remember(fact: str, category: str = "general") -> str:
    """
    Save a fact about the user to long-term memory.
    
    Use this when the user explicitly tells you to remember something —
    a preference, a name, a routine, a tool they use. Don't save things
    automatically; only when asked.
    
    Examples of when to use:
      - "Gary, remember I prefer dark mode"
      - "Save that my dog is named Max"
      - "Remember I work in DaVinci Resolve"
    """
    memory_id = await add_memory_impl(fact, category)
    return f"Saved memory #{memory_id}: {fact}"


async def recall(query: str) -> str:
    """
    Search long-term memory for facts matching a query.
    
    Use this when the user asks about something they've told you before,
    or when context would help answer their question.
    
    Examples of when to use:
      - "What TTS do I prefer?"
      - "What's my dog's name?"
      - User asks about a tool — recall what tools they use first.
    """
    results = await search_memories_impl(query, limit=5)
    if not results:
        return f"No memories found matching '{query}'."
    
    lines = [f"Found {len(results)} memory/memories:"]
    for r in results:
        lines.append(f"  [{r['id']}] {r['fact']} ({r['category']})")
    return "\n".join(lines)


async def forget(memory_id: int) -> str:
    """
    Delete a memory by its ID.
    
    Use this when the user says something like "forget that" or
    "delete memory 5". You'll usually need to call recall first to
    find the right ID.
    """
    deleted = await delete_memory_impl(memory_id)
    if deleted:
        return f"Forgot memory #{memory_id}."
    else:
        return f"No memory with ID {memory_id} found."