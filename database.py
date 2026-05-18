"""
database.py — Async SQLite layer using aiosqlite.
All queries are centralised here; no SQL leaks into handlers.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import aiosqlite

from config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async wrapper around the SQLite database."""

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    category   TEXT    NOT NULL,
                    encrypted  TEXT    NOT NULL,
                    created_at TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_mem_cat
                    ON memories (category COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS media (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT    NOT NULL,
                    file_id    TEXT    NOT NULL,
                    caption    TEXT    DEFAULT '',
                    created_at TEXT    NOT NULL
                );
            """)
            await conn.commit()
        logger.info("Database ready at %s", self.path)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Memories ──────────────────────────────────────────────────────────────

    async def add_memory(self, category: str, encrypted: str) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO memories (category, encrypted, created_at) VALUES (?,?,?)",
                (category, encrypted, self._now()),
            )
            await conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def fetch_memories(
        self,
        *,
        category: str = "",
        limit: int = 0,
        offset: int = 0,
    ) -> list[tuple]:
        q = "SELECT id, category, encrypted, created_at FROM memories"
        params: list = []
        if category:
            q += " WHERE category LIKE ? COLLATE NOCASE"
            params.append(f"%{category}%")
        q += " ORDER BY id DESC"
        if limit:
            q += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(q, params)
            return await cur.fetchall()

    async def delete_memory(self, mid: int) -> bool:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute("DELETE FROM memories WHERE id=?", (mid,))
            await conn.commit()
            return cur.rowcount > 0

    async def count_memories(self, *, category: str = "") -> int:
        q, params = "SELECT COUNT(*) FROM memories", []
        if category:
            q += " WHERE category LIKE ? COLLATE NOCASE"
            params.append(f"%{category}%")
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(q, params)
            row = await cur.fetchone()
            return row[0] if row else 0

    # ── Media ─────────────────────────────────────────────────────────────────

    async def add_media(self, media_type: str, file_id: str, caption: str = "") -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO media (media_type, file_id, caption, created_at) VALUES (?,?,?,?)",
                (media_type, file_id, caption, self._now()),
            )
            await conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def fetch_media(self, *, limit: int = 0, offset: int = 0) -> list[tuple]:
        q = "SELECT id, media_type, caption, created_at FROM media ORDER BY id DESC"
        params: list = []
        if limit:
            q += " LIMIT ? OFFSET ?"
            params = [limit, offset]
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(q, params)
            return await cur.fetchall()

    async def get_media(self, mid: int) -> Optional[tuple]:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "SELECT media_type, file_id, caption FROM media WHERE id=?", (mid,)
            )
            return await cur.fetchone()

    async def delete_media(self, mid: int) -> bool:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute("DELETE FROM media WHERE id=?", (mid,))
            await conn.commit()
            return cur.rowcount > 0

    async def count_media(self) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM media")
            row = await cur.fetchone()
            return row[0] if row else 0

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def stats(self) -> dict:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT category) FROM memories"
            )
            mem_total, cat_total = await cur.fetchone()  # type: ignore[misc]
            cur = await conn.execute("SELECT COUNT(*) FROM media")
            media_total = (await cur.fetchone())[0]  # type: ignore[index]
        return {"memories": mem_total, "categories": cat_total, "media": media_total}


# Singleton
db = DatabaseManager(DB_PATH)
