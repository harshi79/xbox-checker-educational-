"""Xbox Checker SaaS — FastAPI application (Vercel serverless entrypoint)."""

import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

from . import auth, checker, db, rate_limit, watermark

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = BASE_DIR / "static" / "index.html"

APP_VERSION = "1.1.0"

app = FastAPI(
    title="Xbox Checker SaaS",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
)

# The web console is same-origin; the JSON API is also usable cross-origin
# (API-key authenticated), so allow CORS broadly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup() -> None:
    try:
        await db.init_db()
        log.info("Database ready (backend=%s)", db.backend_name())
    except Exception as exc:
        # Never crash the boot on DB issues; endpoints return a clear 503.
        log.warning("Database init deferred/failed: %s", exc)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # HTTPException flows through untouched; everything else becomes a
    # generic JSON 500 (no stack traces leaked to clients).
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    device_fingerprint: str = Field(..., min_length=4, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class CheckRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=512)
    proxies: Optional[list[str]] = Field(default=None, max_length=50)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    api_key = authorization[7:].strip()
    if not api_key:
        raise HTTPException(401, "Missing or invalid authorization header")
    try:
        user = await db.fetchone(
            "SELECT id, email, tier, is_active FROM users WHERE api_key = ?",
            api_key,
        )
    except Exception as exc:
        log.exception("Database error during authentication")
        raise HTTPException(503, "Database temporarily unavailable") from exc
    if not user or not user.get("is_active"):
        raise HTTPException(401, "Invalid or revoked API key")
    return user


async def require_admin(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")):
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key or not x_admin_key or not hmac.compare_digest(x_admin_key, admin_key):
        raise HTTPException(403, "Invalid admin key")


def _db_unavailable(exc: Exception) -> HTTPException:
    log.exception("Database error")
    return HTTPException(503, "Database temporarily unavailable")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/auth/register", status_code=201)
async def register(req: RegisterRequest):
    email = req.email.lower()
    try:
        if await db.fetchone("SELECT id FROM users WHERE email = ?", email):
            raise HTTPException(409, "An account with that email already exists")
        if await db.fetchone(
            "SELECT id FROM users WHERE device_fingerprint = ?", req.device_fingerprint
        ):
            raise HTTPException(409, "This device already has an account")

        api_key = auth.generate_api_key()
        await db.execute(
            """
            INSERT INTO users (email, password_hash, api_key, tier, device_fingerprint)
            VALUES (?, ?, ?, 'free', ?)
            """,
            email,
            auth.hash_password(req.password),
            api_key,
            req.device_fingerprint,
        )
    except HTTPException:
        raise
    except Exception as exc:
        # Unique-constraint races surface as generic DB errors; report 409.
        message = str(exc).lower()
        if "unique" in message or "constraint" in message:
            raise HTTPException(409, "An account with that email already exists") from exc
        raise _db_unavailable(exc) from exc

    return {"api_key": api_key, "tier": "free", "message": "Registration successful"}


@app.post("/auth/login")
async def login(req: LoginRequest):
    try:
        user = await db.fetchone(
            "SELECT id, email, password_hash, api_key, tier FROM users WHERE email = ?",
            req.email.lower(),
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    if not user or not auth.verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(401, "Incorrect email or password")

    token = auth.create_jwt_token({"sub": user["email"], "user_id": user["id"]})
    body = {"api_key": user["api_key"], "tier": user["tier"], "token_type": "bearer"}
    if token:
        body["access_token"] = token
    return body


@app.get("/user/me")
async def get_profile(user: dict = Depends(get_current_user)):
    try:
        used, limit = await rate_limit.current_usage(user["id"], user.get("tier", "free"))
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    return {
        "email": user["email"],
        "tier": user["tier"],
        "daily_usage": used,
        "daily_limit": limit,
    }


@app.post("/user/key/revoke")
async def revoke_key(user: dict = Depends(get_current_user)):
    new_key = auth.generate_api_key()
    try:
        await db.execute("UPDATE users SET api_key = ? WHERE id = ?", new_key, user["id"])
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    return {"api_key": new_key, "message": "API key regenerated"}


# ---------------------------------------------------------------------------
# Core check endpoint
# ---------------------------------------------------------------------------

@app.post("/check")
async def check_account(req: CheckRequest, user: dict = Depends(get_current_user)):
    email = req.email.strip()
    if not email or not req.password:
        raise HTTPException(400, "email and password are required")
    if req.proxies is not None and len(req.proxies) > checker.MAX_PROXIES_PER_REQUEST:
        raise HTTPException(
            413, f"Too many proxies (max {checker.MAX_PROXIES_PER_REQUEST})"
        )

    try:
        allowed, remaining = await rate_limit.check_and_increment(
            user["id"], user.get("tier", "free")
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    if not allowed:
        raise HTTPException(
            429, "Daily limit reached. Resets at midnight UTC — upgrade your tier for more."
        )

    result = await checker.check_account_async(email, req.password, req.proxies)

    # Audit log (best-effort: a logging failure must not fail the check).
    try:
        await db.execute(
            """
            INSERT INTO request_logs (user_id, proxy_used, status, result_snapshot)
            VALUES (?, ?, ?, ?)
            """,
            user["id"],
            json.dumps(req.proxies) if req.proxies else None,
            str(result.get("status", "UNKNOWN")),
            json.dumps(result)[:8000],
        )
    except Exception:
        log.warning("Failed to write request log", exc_info=True)

    result["rate_limit_remaining"] = remaining
    signed = watermark.sign_response(result)
    return JSONResponse(content=signed)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.get("/admin/users")
async def admin_list_users(_: None = Depends(require_admin)):
    from datetime import date

    try:
        users = await db.fetchall(
            """
            SELECT u.id, u.email, u.tier, u.api_key, u.created_at, u.is_active,
                   u.device_fingerprint,
                   COALESCE(d.count, 0) AS daily_usage,
                   COALESCE(d.tier_limit, 0) AS daily_limit,
                   (SELECT COUNT(*) FROM request_logs r WHERE r.user_id = u.id) AS total_checks,
                   (SELECT MAX(r.timestamp) FROM request_logs r WHERE r.user_id = u.id) AS last_check_at
            FROM users u
            LEFT JOIN daily_usage d ON d.user_id = u.id AND d.check_date = ?
            ORDER BY u.created_at DESC
            """,
            date.today().isoformat(),
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    # Fill in tier default limits where the user has no row for today.
    for row in users:
        if not row.get("daily_limit"):
            row["daily_limit"] = rate_limit.tier_limit(row.get("tier", "free"))
    return {"users": users, "count": len(users)}


@app.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    tier: Optional[str] = None,
    revoke: Optional[bool] = None,
    active: Optional[bool] = None,
    _: None = Depends(require_admin),
):
    try:
        if not await db.fetchone("SELECT id FROM users WHERE id = ?", user_id):
            raise HTTPException(404, "User not found")

        if tier is not None:
            tier = tier.lower()
            if tier not in ("free", "premium", "pro"):
                raise HTTPException(400, "Invalid tier (free, premium, pro)")
            await db.execute("UPDATE users SET tier = ? WHERE id = ?", tier, user_id)

        if active is not None:
            await db.execute(
                "UPDATE users SET is_active = ? WHERE id = ?", 1 if active else 0, user_id
            )

        if revoke:
            new_key = auth.generate_api_key()
            await db.execute("UPDATE users SET api_key = ? WHERE id = ?", new_key, user_id)
            return {"api_key": new_key, "message": "User API key revoked and regenerated"}
    except HTTPException:
        raise
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    return {"message": "User updated"}


# ---------------------------------------------------------------------------
# Root, health & misc
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        return INDEX_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Xbox Checker SaaS</h1><p>Console unavailable. API is running — see /health and /docs.</p>",
            status_code=200,
        )


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(status_code=204, content=None)


@app.get("/health")
async def health():
    db_ok = await db.ping()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "db_backend": db.backend_name(),
        "db": "up" if db_ok else "down",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
