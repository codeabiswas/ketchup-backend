"""Run SQL migration files incrementally (idempotent)."""

from __future__ import annotations

import logging
from pathlib import Path

from database.connection import db

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _ensure_migrations_table() -> None:
    """Create the migrations tracking table if it doesn't exist."""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        "  filename VARCHAR(255) PRIMARY KEY,"
        "  applied_at TIMESTAMPTZ DEFAULT NOW()"
        ")"
    )


async def _seed_existing_database() -> None:
    """Mark base migrations as applied if the schema already exists."""
    already_seeded = await db.fetchval("SELECT EXISTS(SELECT 1 FROM _migrations)")
    if already_seeded:
        return

    has_schema = await db.fetchval(
        "SELECT EXISTS("
        "  SELECT 1 FROM information_schema.tables"
        "  WHERE table_schema = 'public' AND table_name = 'users'"
        ")"
    )
    if not has_schema:
        return

    logger.info("Existing database detected — seeding migration history")
    for name in ("01_schema.sql", "02_analytics.sql"):
        if (MIGRATIONS_DIR / name).exists():
            await db.execute("INSERT INTO _migrations (filename) VALUES ($1)", name)


async def run_migrations() -> None:
    """Execute any migration SQL files that haven't been applied yet."""
    await _ensure_migrations_table()
    await _seed_existing_database()

    applied = {
        row["filename"] for row in await db.fetch("SELECT filename FROM _migrations")
    }

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in applied:
            logger.info("  already applied %s — skipping", sql_file.name)
            continue
        logger.info("  applying %s", sql_file.name)
        sql = sql_file.read_text()
        async with db.acquire() as conn:
            await conn.execute(sql)
        await db.execute(
            "INSERT INTO _migrations (filename) VALUES ($1)", sql_file.name
        )

    logger.info("Migrations complete.")
