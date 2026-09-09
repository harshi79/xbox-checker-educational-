"""Compatibility daily quota metadata backed by the ``daily_usage`` table."""

import os
from datetime import datetime, timezone

from .db import fetchone

_DEFAULT_LIMITS = {"free": 100, "premium": 1000, "pro": 999_999}


def _limit_for(tier: str) -> int:
    tier = (tier or "free").lower()
    if tier not in _DEFAULT_LIMITS:
        tier = "free"
    name = f"{tier.upper()}_DAILY_LIMIT"
    try:
        value = int(os.environ.get(name, str(_DEFAULT_LIMITS[tier])))
    except (TypeError, ValueError):
        value = _DEFAULT_LIMITS[tier]
    return max(0, min(value, 100_000_000))


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
    """Atomically consume one metered operation from the daily quota.

    Retained for compatible educational API extensions. The retired credential
    endpoint never calls this helper. Returns ``(allowed, remaining)`` where
    ``remaining`` is the quota left after this operation (0 when denied).
    """
    today = datetime.now(timezone.utc).date().isoformat()
    limit = tier_limit(tier)
    if limit <= 0:
        return False, 0

    # One statement makes the quota decision and increment atomic across
    # concurrent Vercel instances. The former SELECT-then-UPDATE sequence could
    # admit several requests at the final slot.
    row = await fetchone(
        """
        INSERT INTO daily_usage (user_id, check_date, count, tier_limit)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, check_date) DO UPDATE SET
            count = daily_usage.count + 1,
            tier_limit = excluded.tier_limit
        WHERE daily_usage.count < excluded.tier_limit
        RETURNING count
        """,
        user_id,
        today,
        limit,
    )
    if not row:
        return False, 0
    used = int(row.get("count", limit))
    return True, max(0, limit - used)


async def current_usage(user_id: int, tier: str) -> tuple[int, int]:
    """Return ``(used, limit)`` for today without consuming quota."""
    today = datetime.now(timezone.utc).date().isoformat()
    limit = tier_limit(tier)
    row = await fetchone(
        "SELECT count FROM daily_usage WHERE user_id = ? AND check_date = ?",
        user_id,
        today,
    )
    used = int(row["count"]) if row and row.get("count") is not None else 0
    return used, limit
