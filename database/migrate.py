"""Run SQL migration files on first deploy (idempotent)."""

from __future__ import annotations

import logging
from pathlib import Path

from database.connection import db

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations() -> None:
    """Execute migration SQL files if the base schema does not exist yet."""
    exists = await db.fetchval(
        "SELECT EXISTS("
        "  SELECT 1 FROM information_schema.tables"
        "  WHERE table_schema = 'public' AND table_name = 'users'"
        ")"
    )
    if exists:
        logger.info("Base schema already present — skipping migrations.")
        return

    logger.info("Fresh database detected — running migrations …")
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        logger.info("  applying %s", sql_file.name)
        sql = sql_file.read_text()
        async with db.acquire() as conn:
            await conn.execute(sql)
    logger.info("Migrations complete.")
