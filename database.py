"""
database.py — Async PostgreSQL layer using asyncpg.
All queries are centralised here; no SQL leaks into handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async wrapper around a PostgreSQL connection pool."""

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create the connection pool and ensure tables exist."""
        self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id         SERIAL PRIMARY KEY,
                    category   TEXT    NOT NULL,
                    encrypted  TEXT    NOT NULL,
                    created_at TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_mem_cat
                    ON memories (LOWER(category));

                CREATE TABLE IF NOT EXISTS media (
                    id         SERIAL PRIMARY KEY,
                    media_type TEXT    NOT NULL,
                    file_id    TEXT    NOT NULL,
                    caption    TEXT    DEFAULT '',
                    created_at TEXT    NOT NULL
                );
            """)
        logger.info("PostgreSQL database ready.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not initialised. Call initialize() first.")
        return self._pool

    # ── Memories ──────────────────────────────────────────────────────────────

    async def add_memory(self, category: str, encrypted: str) -> int:
        row = await self.pool.fetchrow(
            "INSERT INTO memories (category, encrypted, created_at) "
            "VALUES ($1, $2, $3) RETURNING id",
            category, encrypted, self._now(),
        )
        return row["id"]  # type: ignore[index]

    async def fetch_memories(
        self,
        *,
        category: str = "",
        limit: int = 0,
        offset: int = 0,
    ) -> list[tuple]:
        if category:
            q = (
                "SELECT id, category, encrypted, created_at FROM memories "
                "WHERE LOWER(category) LIKE LOWER($1) ORDER BY id DESC"
            )
            params = [f"%{category}%"]
        else:
            q = "SELECT id, category, encrypted, created_at FROM memories ORDER BY id DESC"
            params = []

        if limit:
            q += f" LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
            params += [limit, offset]

        rows = await self.pool.fetch(q, *params)
        return [tuple(r) for r in rows]

    async def delete_memory(self, mid: int) -> bool:
        result = await self.pool.execute("DELETE FROM memories WHERE id=$1", mid)
        return result.split()[-1] != "0"  # "DELETE N" — N > 0 means success

    async def count_memories(self, *, category: str = "") -> int:
        if category:
            row = await self.pool.fetchrow(
                "SELECT COUNT(*) FROM memories WHERE LOWER(category) LIKE LOWER($1)",
                f"%{category}%",
            )
        else:
            row = await self.pool.fetchrow("SELECT COUNT(*) FROM memories")
        return row[0] if row else 0  # type: ignore[index]

    # ── Media ─────────────────────────────────────────────────────────────────

    async def add_media(self, media_type: str, file_id: str, caption: str = "") -> int:
        row = await self.pool.fetchrow(
            "INSERT INTO media (media_type, file_id, caption, created_at) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            media_type, file_id, caption, self._now(),
        )
        return row["id"]  # type: ignore[index]

    async def fetch_media(self, *, limit: int = 0, offset: int = 0) -> list[tuple]:
        q = "SELECT id, media_type, caption, created_at FROM media ORDER BY id DESC"
        params: list = []
        if limit:
            q += " LIMIT $1 OFFSET $2"
            params = [limit, offset]
        rows = await self.pool.fetch(q, *params)
        return [tuple(r) for r in rows]

    async def get_media(self, mid: int) -> Optional[tuple]:
        row = await self.pool.fetchrow(
            "SELECT media_type, file_id, caption FROM media WHERE id=$1", mid
        )
        return tuple(row) if row else None

    async def delete_media(self, mid: int) -> bool:
        result = await self.pool.execute("DELETE FROM media WHERE id=$1", mid)
        return result.split()[-1] != "0"

    async def count_media(self) -> int:
        row = await self.pool.fetchrow("SELECT COUNT(*) FROM media")
        return row[0] if row else 0  # type: ignore[index]

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def stats(self) -> dict:
        mem_row = await self.pool.fetchrow(
            "SELECT COUNT(*), COUNT(DISTINCT LOWER(category)) FROM memories"
        )
        med_row = await self.pool.fetchrow("SELECT COUNT(*) FROM media")
        return {
            "memories":   mem_row[0],   # type: ignore[index]
            "categories": mem_row[1],   # type: ignore[index]
            "media":      med_row[0],   # type: ignore[index]
        }


# Singleton
db = DatabaseManager()
