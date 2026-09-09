import os
from datetime import date
from .db import execute, fetchone

TIER_LIMITS = {
    "free": int(os.environ.get("FREE_DAILY_LIMIT", 100)),
    "premium": int(os.environ.get("PREMIUM_DAILY_LIMIT", 1000)),
    "pro": int(os.environ.get("PRO_DAILY_LIMIT", 999999)),
}

async def check_and_increment(user_id: int, tier: str) -> tuple[bool, int]:
    """Returns (allowed: bool, remaining: int)"""
    today = date.today().isoformat()
    limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    
    # Try to insert or update atomically
    await execute("""
        INSERT INTO daily_usage (user_id, check_date, count, tier_limit)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, check_date) DO UPDATE SET 
            count = count + 1
        WHERE count < ?
    """, user_id, today, limit, limit)
    
    # Fetch current count
    row = await fetchone(
        "SELECT count FROM daily_usage WHERE user_id = ? AND check_date = ?",
        user_id, today
    )
    
    if row is None:
        # First check of day - insert succeeded
        return True, limit - 1
    
    current = row["count"]
    if current > limit:
        return False, 0
    return True, limit - current
