# database/connection.py

"""Database connection and session management."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import asyncpg

from config import get_settings


class Database:
    """Async PostgreSQL connection pool."""

    def __init__(self):
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        settings = get_settings()
        self.pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        await self.run_migrations()

    async def disconnect(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def run_migrations(self) -> None:
        """Execute all migration SQL files in order."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        migrations_dir = Path(__file__).parent / "migrations"
        migration_files = sorted(migrations_dir.glob("*.sql"))

        async with self.pool.acquire() as conn:
            for migration_file in migration_files:
                migration_sql = migration_file.read_text()
                try:
                    await conn.execute(migration_sql)
                    print(f"Executed migration: {migration_file.name}")
                except Exception as e:
                    print(f"Migration {migration_file.name} failed: {e}")
                    raise

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            yield conn

    async def execute(self, query: str, *args) -> str:
        async with self.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> asyncpg.Record | None:
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args) -> any:
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)


db = Database()
