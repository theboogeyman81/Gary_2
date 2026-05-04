"""
Long-term memory for Gary.

Stores facts about the user in a local SQLite database.
Explicit-only — Gary saves things only when told to.

Schema:
    id          INTEGER PRIMARY KEY
    fact        TEXT       — the actual fact
    category    TEXT       — optional tag (preferences, tools, people, etc.)
    created_at  TEXT       — ISO timestamp
    last_used   TEXT       — ISO timestamp, updated on recall
"""

import aiosqlite
from pathlib import Path
from datetime import datetime


# Database file lives in the memory/ folder.
DB_PATH = Path(__file__).parent / "gary_memory.db"


async def init_db() -> None:
    """Create the memories table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL
            )
        """)
        await db.commit()


async def add_memory(fact: str, category: str = "general") -> int:
    """Save a fact to memory. Returns the ID of the new memory."""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO memories (fact, category, created_at, last_used) VALUES (?, ?, ?, ?)",
            (fact, category, now, now),
        )
        await db.commit()
        return cursor.lastrowid


async def search_memories(query: str, limit: int = 5) -> list[dict]:
    """
    Find memories matching a query (simple LIKE search on fact text).
    
    Returns a list of dicts with id, fact, category.
    Updates last_used for matched memories.
    """
    pattern = f"%{query}%"
    now = datetime.now().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, fact, category FROM memories
            WHERE fact LIKE ? OR category LIKE ?
            ORDER BY last_used DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        )
        rows = await cursor.fetchall()
        results = [dict(row) for row in rows]
        
        # Update last_used for matched memories.
        if results:
            ids = [r["id"] for r in results]
            placeholders = ",".join("?" for _ in ids)
            await db.execute(
                f"UPDATE memories SET last_used = ? WHERE id IN ({placeholders})",
                (now, *ids),
            )
            await db.commit()
        
        return results


async def list_all_memories() -> list[dict]:
    """Return every memory Gary has stored."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, fact, category, created_at FROM memories ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_memory(memory_id: int) -> bool:
    """Delete a memory by ID. Returns True if something was deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await db.commit()
        return cursor.rowcount > 0