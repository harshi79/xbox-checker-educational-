"""Xbox Profile Lab educational console — FastAPI/Vercel entrypoint.

The browser authenticates with an opaque, HttpOnly, database-backed session.
API keys remain available for programmatic clients, but are no longer used as
browser session storage.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent.parent
# Local developer convenience only. Platform-provided values always win, and
# .env is excluded from both Git and Vercel uploads.
load_dotenv(BASE_DIR / ".env", override=False)

from . import auth, checker, db, rate_limit, watermark  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

INDEX_HTML = BASE_DIR / "static" / "index.html"
APP_VERSION = "2.0.0"


@asynccontextmanager
async def _lifespan(_: FastAPI):
    try:
        await db.init_db()
        log.info("Database ready (backend=%s, persistent=%s)", db.backend_name(), db.is_persistent())
    except Exception as exc:
        # A failed remote database must not turn the landing page into a cold
        # start crash. Data endpoints return a clear 503 and /ready returns 503.
        log.warning("Database init deferred/failed: %s", exc)
    yield


app = FastAPI(
    title="Xbox Profile Lab API",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
    lifespan=_lifespan,
)

# The production console is same-origin. Explicitly configured development
# origins can be enabled without combining wildcard CORS with browser cookies.
def _valid_cors_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # validate malformed/non-numeric ports
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


_cors_origins = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",")
    if origin.strip() and _valid_cors_origin(origin.strip())
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
    )


# ---------------------------------------------------------------------------
# Lifecycle, errors and response hardening
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _security_headers(request: Request, call_next):
    candidate_id = request.headers.get("x-vercel-id", "")
    request_id = (
        candidate_id
        if candidate_id and len(candidate_id) <= 128 and re.fullmatch(r"[A-Za-z0-9:._-]+", candidate_id)
        else uuid.uuid4().hex
    )
    request.state.request_id = request_id
    response = await call_next(request)

    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/docs"):
        # FastAPI's generated Swagger UI pins assets to jsDelivr and its icon
        # to fastapi.tiangolo.com. Keep those exceptions isolated from the app.
        content_security_policy = (
            "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
    else:
        content_security_policy = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
    response.headers.setdefault("Content-Security-Policy", content_security_policy)
    if request.url.path.startswith(
        ("/auth/", "/user/", "/admin/", "/microsoft/", "/check", "/health", "/ready")
    ):
        response.headers.setdefault("Cache-Control", "no-store")
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if forwarded_proto == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # Starlette handles HTTPException before this generic handler. Keep the
    # branch for direct invocation in unusual serverless adapters.
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": getattr(request.state, "request_id", None)},
            headers=getattr(exc, "headers", None),
        )
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    log.exception("Unhandled error [%s] on %s %s", request_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

# Deliberately avoid Pydantic's EmailStr here. EmailStr imports the optional
# email-validator package while the module is loading, so a packaging mismatch
# can crash *every* route (including / and /health). This conservative syntax
# validator keeps bad input out without making application startup optional.
_EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,189}\.[^\s@.]{2,63}$")


def _normalise_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise ValueError("Enter a valid email address")
    return email


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    device_fingerprint: str = Field(..., min_length=4, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("device_fingerprint")
    @classmethod
    def validate_installation_id(cls, value: str) -> str:
        installation_id = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{4,128}", installation_id):
            raise ValueError("Enter a valid browser installation ID")
        return installation_id


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


# ---------------------------------------------------------------------------
# Authentication dependencies and browser sessions
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _production_environment() -> bool:
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("APP_ENV", "").strip().lower() == "production"
    )


def _require_persistent_production_database() -> None:
    if _production_environment() and not db.is_persistent():
        raise HTTPException(
            503,
            "Persistent database storage is not configured for this production environment",
        )


def _cookie_secure(request: Request) -> bool:
    configured = os.environ.get("SESSION_COOKIE_SECURE")
    if configured is not None:
        return configured.strip().lower() not in {"0", "false", "no", "off"}
    return bool(
        _production_environment()
        or request.headers.get("x-forwarded-proto") == "https"
        or request.url.scheme == "https"
    )


async def _issue_browser_session(user_id: int, request: Request, response: Response) -> None:
    token = auth.generate_session_token()
    ttl = auth.session_ttl_seconds()
    now = _utcnow()
    expires = now + timedelta(seconds=ttl)

    # Opportunistic cleanup keeps the table bounded without a scheduler.
    try:
        await db.execute("DELETE FROM sessions WHERE expires_at <= ?", _iso(now))
    except Exception:
        log.debug("Expired-session cleanup failed", exc_info=True)

    await db.execute(
        """
        INSERT INTO sessions (user_id, token_hash, created_at, expires_at, user_agent_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        user_id,
        auth.hash_session_token(token),
        _iso(now),
        _iso(expires),
        None,
    )
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl,
        expires=expires,
        path="/",
        secure=_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )


async def _user_from_api_key(api_key: str) -> dict | None:
    if len(api_key) < 20 or len(api_key) > 256:
        return None
    record = auth.api_key_record(api_key)
    # The raw-key alternative supports transparent migration from releases
    # that stored API keys in plaintext. New and migrated rows store a digest.
    user = await db.fetchone(
        "SELECT id, email, tier, is_active, api_key FROM users WHERE api_key IN (?, ?)",
        record,
        api_key,
    )
    if user and not auth.is_api_key_record(user.get("api_key", "")):
        await db.execute("UPDATE users SET api_key = ? WHERE id = ?", record, user["id"])
        user["api_key"] = record
    return user


async def _user_from_session(token: str) -> dict | None:
    if len(token) < 32 or len(token) > 256:
        return None
    return await db.fetchone(
        """
        SELECT u.id, u.email, u.tier, u.is_active, u.api_key, s.token_hash AS session_hash
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        auth.hash_session_token(token),
        _iso(_utcnow()),
    )


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_persistent_production_database()
    try:
        # An explicitly supplied Authorization header is authoritative. Never
        # let an invalid API key silently fall back to an ambient browser cookie.
        if authorization is not None:
            scheme, separator, credential = authorization.partition(" ")
            if not separator or scheme.lower() != "bearer" or not credential.strip():
                raise HTTPException(
                    401,
                    "Missing or invalid authorization header",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user = await _user_from_api_key(credential.strip())
            auth_method = "api_key"
        else:
            session_token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
            user = await _user_from_session(session_token) if session_token else None
            auth_method = "session"
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Database error during authentication")
        raise HTTPException(503, "Database temporarily unavailable") from exc

    if not user or not user.get("is_active"):
        raise HTTPException(
            401,
            "Authentication required or session expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user["_auth_method"] = auth_method
    return user


async def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key or not x_admin_key or not hmac.compare_digest(x_admin_key, admin_key):
        raise HTTPException(403, "Invalid admin key")


CurrentUser = Annotated[dict, Depends(get_current_user)]
AdminAccess = Annotated[None, Depends(require_admin)]


def _db_unavailable(exc: Exception) -> HTTPException:
    log.exception("Database error")
    return HTTPException(503, "Database temporarily unavailable")


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _client_rate_identifier(request: Request, email: str = "") -> str:
    address = request.client.host if request.client else "unknown"
    trust_proxy = _production_environment() or os.environ.get(
        "TRUST_PROXY_HEADERS", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            address = forwarded[:128]
    return f"{address}|{email}"


async def _consume_auth_attempt(
    *, scope: str, identifier: str, limit: int, window_seconds: int
) -> str:
    """Atomically consume one distributed auth-attempt allowance."""
    key_hash = hashlib.sha256(f"{scope}|{identifier}".encode("utf-8")).hexdigest()
    now = _utcnow()
    cutoff = now - timedelta(seconds=window_seconds)

    # Keep abandoned identifiers bounded. This index-backed cleanup is safe to
    # race across serverless instances.
    await db.execute(
        "DELETE FROM auth_attempts WHERE last_attempt_at <= ?",
        _iso(now - timedelta(days=2)),
    )
    row = await db.fetchone(
        """
        INSERT INTO auth_attempts
            (key_hash, scope, attempts, window_started_at, last_attempt_at)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(key_hash) DO UPDATE SET
            attempts = CASE
                WHEN window_started_at <= ? THEN 1
                ELSE attempts + 1
            END,
            window_started_at = CASE
                WHEN window_started_at <= ? THEN excluded.window_started_at
                ELSE window_started_at
            END,
            last_attempt_at = excluded.last_attempt_at
        RETURNING attempts
        """,
        key_hash,
        scope,
        _iso(now),
        _iso(now),
        _iso(cutoff),
        _iso(cutoff),
    )
    attempts = int((row or {}).get("attempts", limit + 1))
    if attempts > limit:
        raise HTTPException(
            429,
            "Too many authentication attempts. Please wait and try again.",
            headers={"Retry-After": str(window_seconds)},
        )
    return key_hash


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/auth/register", status_code=201)
async def register(req: RegisterRequest, request: Request, response: Response):
    _require_persistent_production_database()
    email = req.email
    try:
        await _consume_auth_attempt(
            scope="register",
            identifier=_client_rate_identifier(request),
            limit=_bounded_env_int("REGISTRATION_MAX_ATTEMPTS", 8, 2, 100),
            window_seconds=60 * 60,
        )
        if await db.fetchone("SELECT id FROM users WHERE email = ?", email):
            raise HTTPException(409, "An account with that email already exists")
        if await db.fetchone(
            "SELECT id FROM users WHERE device_fingerprint = ?", req.device_fingerprint
        ):
            raise HTTPException(409, "This device already has an account")

        api_key = auth.generate_api_key()
        password_hash = await asyncio.to_thread(auth.hash_password, req.password)
        # Keep the legacy one-account-per-installation rule in the same write
        # statement as insertion. This closes the race between the friendly
        # pre-check above and concurrent registration requests without adding
        # a migration-breaking unique index to databases that may contain old
        # duplicate fingerprint rows.
        user = await db.fetchone(
            """
            INSERT INTO users (email, password_hash, api_key, tier, device_fingerprint)
            SELECT ?, ?, ?, 'free', ?
            WHERE NOT EXISTS (
                SELECT 1 FROM users WHERE device_fingerprint = ?
            )
            RETURNING id
            """,
            email,
            password_hash,
            auth.api_key_record(api_key),
            req.device_fingerprint,
            req.device_fingerprint,
        )
        if not user:
            raise HTTPException(409, "This browser installation already has an account")
        await _issue_browser_session(int(user["id"]), request, response)
    except HTTPException:
        raise
    except Exception as exc:
        message = str(exc).lower()
        if "unique" in message or "constraint" in message:
            if "device_fingerprint" in message or "fingerprint" in message:
                raise HTTPException(409, "This browser installation already has an account") from exc
            raise HTTPException(409, "An account with that email already exists") from exc
        raise _db_unavailable(exc) from exc

    # The full key is returned once for CLI/API users. The browser uses the
    # HttpOnly session cookie and deliberately does not persist this value.
    return {
        "api_key": api_key,
        "tier": "free",
        "email": email,
        "message": "Registration successful",
    }


@app.post("/auth/login")
async def login(req: LoginRequest, request: Request, response: Response):
    _require_persistent_production_database()
    attempt_key = ""
    try:
        attempt_key = await _consume_auth_attempt(
            scope="login",
            identifier=_client_rate_identifier(request, req.email),
            limit=_bounded_env_int("LOGIN_MAX_ATTEMPTS", 10, 3, 100),
            window_seconds=15 * 60,
        )
        user = await db.fetchone(
            """
            SELECT id, email, password_hash, api_key, tier, is_active
            FROM users WHERE email = ?
            """,
            req.email,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    candidate_hash = user.get("password_hash", "") if user else auth.DUMMY_PASSWORD_HASH
    password_ok = await asyncio.to_thread(auth.verify_password, req.password, candidate_hash)
    if not user or not password_ok:
        raise HTTPException(
            401,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active"):
        raise HTTPException(403, "This account has been disabled")

    try:
        # Transparently migrate plaintext API keys created by older releases.
        # Login no longer re-discloses the full developer credential; users can
        # explicitly rotate it if they need a new copy.
        stored_key = user.get("api_key", "")
        if stored_key and not auth.is_api_key_record(stored_key):
            stored_key = auth.api_key_record(stored_key)
            await db.execute("UPDATE users SET api_key = ? WHERE id = ?", stored_key, user["id"])
        if auth.password_needs_rehash(candidate_hash):
            upgraded_hash = await asyncio.to_thread(auth.hash_password, req.password)
            await db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                upgraded_hash,
                user["id"],
            )
        await _issue_browser_session(int(user["id"]), request, response)
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    try:
        await db.execute("DELETE FROM auth_attempts WHERE key_hash = ?", attempt_key)
    except Exception:
        # Authentication already succeeded and the session exists. A failed
        # best-effort throttle reset must not turn that success into a 500/503.
        log.warning("Could not clear successful login throttle", exc_info=True)

    return {
        "api_key_preview": auth.preview_api_key(stored_key),
        "tier": user["tier"],
        "email": user["email"],
        "session": "active",
    }


@app.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response):
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    if token:
        try:
            await db.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                auth.hash_session_token(token),
            )
        except Exception:
            # Logout still clears the client cookie if the DB is unavailable.
            log.warning("Could not delete server-side session during logout", exc_info=True)
    response.delete_cookie(
        key=auth.SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )


@app.post("/auth/logout-all")
async def logout_all(request: Request, response: Response, user: CurrentUser):
    try:
        await db.execute("DELETE FROM sessions WHERE user_id = ?", user["id"])
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    response.delete_cookie(
        key=auth.SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )
    return {"message": "Signed out on all devices"}


@app.get("/user/me")
async def get_profile(user: CurrentUser):
    try:
        used, limit = await rate_limit.current_usage(user["id"], user.get("tier", "free"))
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    return {
        "email": user["email"],
        "tier": user["tier"],
        "daily_usage": used,
        "daily_limit": limit,
        "api_key_preview": auth.preview_api_key(user.get("api_key", "")),
        "auth_method": user.get("_auth_method", "unknown"),
    }


@app.post("/user/key/revoke")
async def revoke_key(user: CurrentUser):
    new_key = auth.generate_api_key()
    try:
        await db.execute(
            "UPDATE users SET api_key = ? WHERE id = ?",
            auth.api_key_record(new_key),
            user["id"],
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    return {"api_key": new_key, "message": "API key regenerated"}


# ---------------------------------------------------------------------------
# Consent-based Microsoft/Xbox connection
# ---------------------------------------------------------------------------

def _valid_microsoft_redirect_uri(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # validate malformed/non-numeric ports
    except ValueError:
        return False
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    production_https = parsed.scheme == "https" and bool(parsed.hostname)
    return bool(
        (local_http or production_https)
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and not re.search(r"\s", value)
    )


def _valid_production_redirect_uri(value: str) -> bool:
    return _valid_microsoft_redirect_uri(value) and urlsplit(value).scheme == "https"


def _microsoft_connection_configured() -> bool:
    if not checker.is_configured():
        return False
    configured = os.environ.get("MICROSOFT_REDIRECT_URI", "").strip()
    if _production_environment():
        return _valid_production_redirect_uri(configured)
    return not configured or _valid_microsoft_redirect_uri(configured)


def _microsoft_redirect_uri(request: Request) -> str:
    configured = os.environ.get("MICROSOFT_REDIRECT_URI", "").strip()
    if configured:
        valid_redirect = (
            _valid_production_redirect_uri(configured)
            if _production_environment()
            else _valid_microsoft_redirect_uri(configured)
        )
        if not valid_redirect:
            raise HTTPException(
                503,
                "MICROSOFT_REDIRECT_URI must be an HTTPS URL (HTTP is allowed only for localhost)",
            )
        return configured

    if _production_environment():
        raise HTTPException(
            503,
            "MICROSOFT_REDIRECT_URI must be configured explicitly in production",
        )

    return str(request.url_for("microsoft_callback"))


@app.get("/microsoft/status")
async def microsoft_status(user: CurrentUser):
    try:
        connection = await db.fetchone(
            """
            SELECT gamertag, gamerscore, xuid, account_tier,
                   connected_at, last_checked_at
            FROM xbox_connections WHERE user_id = ?
            """,
            user["id"],
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    capabilities = checker.configuration()
    capabilities["oauth_configured"] = _microsoft_connection_configured()
    capabilities["profile_access"] = capabilities["oauth_configured"]
    payload = {
        "connected": bool(connection),
        "profile": connection,
        "capabilities": capabilities,
    }
    return JSONResponse(content=watermark.sign_response(payload))


@app.get("/microsoft/connect")
async def microsoft_connect(request: Request, user: CurrentUser):
    if not _microsoft_connection_configured():
        raise HTTPException(
            503,
            "Microsoft OAuth is not configured. Set MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, and MICROSOFT_REDIRECT_URI.",
        )

    state = checker.create_state()
    pair = checker.create_pkce_pair()
    now = _utcnow()
    expires = now + timedelta(minutes=10)
    redirect_uri = _microsoft_redirect_uri(request)
    try:
        await db.execute("DELETE FROM oauth_states WHERE expires_at <= ?", _iso(now))
        await db.execute(
            """
            INSERT INTO oauth_states
                (state_hash, user_id, code_verifier, redirect_uri, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            checker.hash_state(state),
            user["id"],
            pair.verifier,
            redirect_uri,
            _iso(now),
            _iso(expires),
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    url = checker.authorization_url(
        state=state,
        challenge=pair.challenge,
        redirect_uri=redirect_uri,
    )
    return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "no-store"})


@app.get("/microsoft/callback", name="microsoft_callback")
async def microsoft_callback(
    user: CurrentUser,
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=512),
    error: str | None = Query(default=None, max_length=128),
):
    # State is mandatory for both successful and denied authorization results;
    # never trust an OAuth callback solely because it contains an error field.
    if not state:
        return RedirectResponse(url="/?microsoft=invalid", status_code=303)

    try:
        # Atomically fetch and consume the state. A SELECT followed by DELETE
        # leaves a replay race in which concurrent callbacks can both redeem
        # the same state; DELETE ... RETURNING closes that gap on SQLite/libSQL.
        oauth_state = await db.fetchone(
            """
            DELETE FROM oauth_states
            WHERE state_hash = ? AND user_id = ? AND expires_at > ?
            RETURNING state_hash, user_id, code_verifier, redirect_uri
            """,
            checker.hash_state(state),
            user["id"],
            _iso(_utcnow()),
        )
        if not oauth_state:
            return RedirectResponse(url="/?microsoft=expired", status_code=303)
        if error:
            return RedirectResponse(url="/?microsoft=cancelled", status_code=303)
        if not code:
            return RedirectResponse(url="/?microsoft=invalid", status_code=303)

        # Keep enough headroom below the 60-second serverless function limit
        # for persistence and the final redirect, even if an upstream stalls.
        async with asyncio.timeout(45):
            access_token = await checker.exchange_authorization_code(
                code=code,
                verifier=oauth_state["code_verifier"],
                redirect_uri=oauth_state["redirect_uri"],
            )
            profile = await checker.fetch_xbox_profile(access_token)
        now = _iso(_utcnow())
        await db.execute(
            """
            INSERT INTO xbox_connections
                (user_id, xuid, gamertag, gamerscore, account_tier,
                 connected_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                xuid = excluded.xuid,
                gamertag = excluded.gamertag,
                gamerscore = excluded.gamerscore,
                account_tier = excluded.account_tier,
                last_checked_at = excluded.last_checked_at
            """,
            user["id"],
            profile.get("xuid"),
            profile["gamertag"],
            profile.get("gamerscore", 0),
            profile.get("account_tier"),
            now,
            now,
        )
        try:
            await db.execute(
                """
                INSERT INTO audit_events (user_id, event_type, metadata)
                VALUES (?, 'MICROSOFT_PROFILE_CONNECTED', NULL)
                """,
                user["id"],
            )
        except Exception:
            log.warning("Failed to write OAuth audit event", exc_info=True)
    except checker.XboxIntegrationError as exc:
        log.info("Microsoft/Xbox connection failed for user %s: %s", user["id"], exc)
        return RedirectResponse(url="/?microsoft=error", status_code=303)
    except TimeoutError:
        log.info("Microsoft/Xbox connection exceeded callback time budget for user %s", user["id"])
        return RedirectResponse(url="/?microsoft=error", status_code=303)
    except Exception:
        log.exception("Microsoft callback database failure")
        return RedirectResponse(url="/?microsoft=error", status_code=303)

    return RedirectResponse(url="/?microsoft=connected", status_code=303)


@app.post("/microsoft/disconnect")
async def microsoft_disconnect(user: CurrentUser):
    try:
        await db.execute("DELETE FROM xbox_connections WHERE user_id = ?", user["id"])
        await db.execute("DELETE FROM oauth_states WHERE user_id = ?", user["id"])
    except Exception as exc:
        raise _db_unavailable(exc) from exc
    return {"message": "Microsoft account disconnected"}


@app.post("/check")
async def retired_password_check(_: CurrentUser):
    """Compatibility response for clients of the unsafe legacy endpoint."""
    raise HTTPException(
        410,
        "Direct email/password checks were retired. Use the Microsoft OAuth connection flow.",
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.get("/admin/users")
async def admin_list_users(_: AdminAccess):
    today = _utcnow().date().isoformat()
    try:
        users = await db.fetchall(
            """
            SELECT u.id, u.email, u.tier, u.api_key, u.created_at, u.is_active,
                   COALESCE(d.count, 0) AS daily_usage,
                   COALESCE(d.tier_limit, 0) AS daily_limit,
                   (SELECT COUNT(*) FROM audit_events a WHERE a.user_id = u.id) AS audit_events,
                   (SELECT MAX(a.created_at) FROM audit_events a WHERE a.user_id = u.id) AS last_event_at
            FROM users u
            LEFT JOIN daily_usage d ON d.user_id = u.id AND d.check_date = ?
            ORDER BY u.created_at DESC
            """,
            today,
        )
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    for row in users:
        if not row.get("daily_limit"):
            row["daily_limit"] = rate_limit.tier_limit(row.get("tier", "free"))
        row["api_key_preview"] = auth.preview_api_key(row.pop("api_key", ""))
    return {"users": users, "count": len(users)}


@app.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    _: AdminAccess,
    tier: str | None = None,
    revoke: bool | None = None,
    active: bool | None = None,
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
                "UPDATE users SET is_active = ? WHERE id = ?",
                1 if active else 0,
                user_id,
            )
            if not active:
                await db.execute("DELETE FROM sessions WHERE user_id = ?", user_id)

        if revoke:
            # Administrators can invalidate a compromised credential but do not
            # receive an impersonation-capable replacement. The user signs in
            # and explicitly rotates once to obtain a new key.
            revoked_key = auth.generate_api_key()
            await db.execute(
                "UPDATE users SET api_key = ? WHERE id = ?",
                auth.api_key_record(revoked_key),
                user_id,
            )
            return {
                "api_key_preview": auth.preview_api_key(revoked_key),
                "message": "User API key revoked; the user must regenerate it after signing in",
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise _db_unavailable(exc) from exc

    return {"message": "User updated"}


# ---------------------------------------------------------------------------
# Root, liveness and readiness
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        return INDEX_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Xbox Profile Lab</h1><p>Console unavailable. API is running — see /health and /docs.</p>",
            status_code=503,
        )


@app.get("/favicon.ico", status_code=204)
async def favicon():
    return Response(status_code=204)


def _configuration_warnings() -> list[str]:
    warnings: list[str] = []
    database_warning = db.configuration_warning()
    if database_warning:
        warnings.append(database_warning)
    if not watermark.is_configured():
        warnings.append("WATERMARK_SECRET should be a random value of at least 32 characters")
    if _production_environment():
        if not checker.has_client_id():
            warnings.append("MICROSOFT_CLIENT_ID is missing; Microsoft connection is disabled")
        if not checker.has_client_secret():
            warnings.append("MICROSOFT_CLIENT_SECRET is missing for the production confidential web app")
        redirect_uri = os.environ.get("MICROSOFT_REDIRECT_URI", "").strip()
        if not redirect_uri:
            warnings.append("MICROSOFT_REDIRECT_URI is missing; configure the exact production callback URL")
        elif not _valid_production_redirect_uri(redirect_uri):
            warnings.append("MICROSOFT_REDIRECT_URI is invalid; production requires an HTTPS callback URL")
        if not os.environ.get("ADMIN_API_KEY", "").strip():
            warnings.append("ADMIN_API_KEY is missing; administrative routes are disabled")
    return warnings


def _production_ready(db_ok: bool) -> bool:
    if not db_ok:
        return False
    if not _production_environment():
        return True
    return bool(
        db.is_persistent()
        and checker.is_configured()
        and _valid_production_redirect_uri(os.environ.get("MICROSOFT_REDIRECT_URI", "").strip())
        and watermark.is_configured()
    )


def _health_payload(db_ok: bool) -> dict:
    production_ready = _production_ready(db_ok)
    payload = {
        "status": "ok" if production_ready else "degraded",
        "version": APP_VERSION,
        "db_backend": db.backend_name(),
        "db": "up" if db_ok else "down",
        "db_persistent": db.is_persistent(),
        "microsoft_oauth": "configured" if _microsoft_connection_configured() else "not_configured",
        "response_signing": "configured" if watermark.is_configured() else "process_local",
        "ready": production_ready,
        "timestamp": _iso(_utcnow()),
    }
    warnings = _configuration_warnings()
    if warnings:
        payload["warnings"] = warnings
    return payload


@app.get("/health")
async def health():
    # Liveness intentionally remains HTTP 200 so operators can distinguish a
    # running app with a failed dependency from a function cold-start failure.
    return _health_payload(await db.ping())


@app.get("/ready")
async def ready():
    db_ok = await db.ping()
    return JSONResponse(
        status_code=200 if _production_ready(db_ok) else 503,
        content=_health_payload(db_ok),
    )
