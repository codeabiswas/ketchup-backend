# utils/invite_expiry.py

"""
Background task that periodically expires stale group invites.

Runs as an asyncio task inside the FastAPI lifespan — think of it
like a drummer keeping time in the background. Every INTERVAL minutes
it wakes up, checks for pending invites older than 24 hours, and
flips them to 'expired'.
"""

import asyncio
import logging

from database import db

logger = logging.getLogger(__name__)

# How often to check for expired invites (in seconds)
CHECK_INTERVAL_SECONDS = 5 * 60  # every 5 minutes

# How long an invite stays valid before auto-expiring
INVITE_TTL_HOURS = 24


async def expire_stale_invites_loop() -> None:
    """
    Infinite loop that runs inside the FastAPI lifespan.
    Sleeps between checks so it doesn't burn CPU.

    Called via: asyncio.create_task(expire_stale_invites_loop())
    Cancelled automatically when the lifespan exits.
    """
    logger.info(
        "Invite expiry task started (interval=%ds, ttl=%dh)",
        CHECK_INTERVAL_SECONDS,
        INVITE_TTL_HOURS,
    )
    while True:
        try:
            await _expire_batch()
        except asyncio.CancelledError:
            logger.info("Invite expiry task cancelled — shutting down")
            raise  # Re-raise so asyncio actually cancels the task
        except Exception:
            # Log but don't crash — we'll retry next cycle
            logger.exception("Error in invite expiry task")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _expire_batch() -> None:
    """
    Find all pending invites older than INVITE_TTL_HOURS and mark them 'expired'.

    Uses a single UPDATE query with make_interval() because asyncpg
    can't parameterize inside INTERVAL '...' string literals.
    """
    result = await db.execute(
        """
        UPDATE group_invites
        SET status = 'expired'
        WHERE status = 'pending'
          AND created_at < NOW() - make_interval(hours => $1)
        """,
        INVITE_TTL_HOURS,
    )

    # asyncpg returns "UPDATE N" — parse the count
    if result and result != "UPDATE 0":
        count = result.split()[-1]
        logger.info("Expired %s stale invite(s)", count)
