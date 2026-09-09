"""Daily per-user rate limiting backed by the ``daily_usage`` table."""

import os
from datetime import date

from .db import execute, fetchone


def _limit_for(tier: str) -> int:
    tier = (tier or "free").lower()
    if tier == "premium":
        return int(os.environ.get("PREMIUM_DAILY_LIMIT", 1000))
    if tier == "pro":
        return int(os.environ.get("PRO_DAILY_LIMIT", 999999))
    return int(os.environ.get("FREE_DAILY_LIMIT", 100))


# Backwards-compatible snapshot evaluated at import time.
TIER_LIMITS = {
    "free": _limit_for("free"),
    "premium": _limit_for("premium"),
    "pro": _limit_for("pro"),
}


def tier_limit(tier: str) -> int:
    """Return the daily check limit for a tier (reads env live)."""
    try:
        return _limit_for(tier)
    except (TypeError, ValueError):
        return 100


async def check_and_increment(user_id: int, tier: str) -> tuple[bool, int]:
    """Atomically consume one check from the user's daily quota.

    Returns ``(allowed, remaining)`` where ``remaining`` is the quota left
    *after* this check (0 when denied).
    """
    today = date.today().isoformat()
    limit = tier_limit(tier)

    row = await fetchone(
        "SELECT count FROM daily_usage WHERE user_id = ? AND check_date = ?",
        user_id,
        today,
    )
    current = int(row["count"]) if row and row.get("count") is not None else 0
    if current >= limit:
        return False, 0

    await execute(
        """
        INSERT INTO daily_usage (user_id, check_date, count, tier_limit)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, check_date) DO UPDATE SET
            count = count + 1,
            tier_limit = excluded.tier_limit
        """,
        user_id,
        today,
        limit,
    )
    return True, limit - current - 1


async def current_usage(user_id: int, tier: str) -> tuple[int, int]:
    """Return ``(used, limit)`` for today without consuming quota."""
    today = date.today().isoformat()
    limit = tier_limit(tier)
    row = await fetchone(
        "SELECT count FROM daily_usage WHERE user_id = ? AND check_date = ?",
        user_id,
        today,
    )
    used = int(row["count"]) if row and row.get("count") is not None else 0
    return used, limit
