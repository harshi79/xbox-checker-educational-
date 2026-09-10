"""Xbox Checker — FastAPI application (Vercel serverless entrypoint).

API-only educational project: no frontend, no login, no registration,
no database. The API surface is intentionally tiny:

    POST /check   — check an Xbox/Microsoft account subscription
    GET  /health  — service health
    GET  /docs    — interactive OpenAPI documentation (auto-generated)

Every ``/check`` response is HMAC-SHA256 signed (see ``api/watermark.py``)
so clients can verify payload integrity when they hold the shared
``WATERMARK_SECRET``.

> ⚠️ Educational use only: only check accounts you own or are explicitly
> authorised to test.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Optional local .env support (no-op when python-dotenv is not installed).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from . import checker, watermark  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = BASE_DIR / "static" / "index.html"

APP_VERSION = "2.0.0"

app = FastAPI(
    title="Xbox Checker API",
    version=APP_VERSION,
    description=(
        "Educational API that checks Xbox Live account subscriptions "
        "(Game Pass / Xbox Live Gold / Microsoft 365, etc.) and reports "
        "gamertag + gamerscore.\n\n"
        "There is **no authentication**: this project deliberately has no "
        "login or registration. Keep it that way in production or put a "
        "gateway in front.\n\n"
        "⚠️ Educational use only — only check accounts you own or are "
        "explicitly authorised to test."
    ),
    docs_url="/docs",
    redoc_url=None,
)

# The JSON API is meant to be callable from anywhere (curl, scripts,
# third-party tools), so CORS is open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # HTTPException flows through untouched; everything else becomes a
    # generic JSON 500 (no stack traces leaked to clients).
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CheckRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=320, description="Microsoft account email")
    password: str = Field(..., min_length=1, max_length=512, description="Microsoft account password")
    proxies: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional proxy list, max "
            f"{checker.MAX_PROXIES_PER_REQUEST} entries. Accepted formats: "
            "ip:port, user:pass:ip:port, http://host:port, socks5://host:port, "
            "user:pass@host:port."
        ),
    )


class CheckResponse(BaseModel):
    """Standard ``/check`` result.

    ``status`` is one of:
    - ``PREMIUM`` — an active subscription was found (details in ``data``)
    - ``FREE`` — account is valid, no active subscription
    - ``BAD`` — credentials rejected (wrong password / account does not exist)
    - ``2FA`` — account requires two-step verification
    - ``BANNED`` — account is suspended or banned
    - ``TIMEOUT`` — upstream request timed out
    - ``ERROR`` — something failed (see ``error``)

    ``watermark`` and ``signature`` are added by the server on every response.
    """

    status: str
    duration: float = Field(description="Seconds the check took")
    data: Optional[dict] = Field(default=None, description="gamertag / gamerscore / subscriptions")
    error: Optional[str] = Field(default=None, description="Only present on ERROR/TIMEOUT")
    watermark: str
    signature: str


# ---------------------------------------------------------------------------
# Core check endpoint
# ---------------------------------------------------------------------------

@app.post("/check", response_model=CheckResponse)
async def check_account(req: CheckRequest):
    """Check a Microsoft/Xbox account for active subscriptions.

    Runs the OAuth-style Xbox Live token dance (login.live.com →
    user.auth.xboxlive.com → xsts.auth.xboxlive.com) and probes the
    subscriptions, store purchases and Minecraft entitlement APIs.
    """
    email = req.email.strip()
    if not email or not req.password:
        raise HTTPException(400, "email and password are required")
    if req.proxies is not None and len(req.proxies) > checker.MAX_PROXIES_PER_REQUEST:
        raise HTTPException(
            413, f"Too many proxies (max {checker.MAX_PROXIES_PER_REQUEST})"
        )

    log.info("check requested for %s (proxies=%d)", email, len(req.proxies or []))
    result = await checker.check_account_async(email, req.password, req.proxies)
    log.info("check result: %s (%.2fs)", result.get("status"), float(result.get("duration", 0)))

    return JSONResponse(content=watermark.sign_response(result))


# ---------------------------------------------------------------------------
# Root & health
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    """Interactive docs + live console (single-file 3D brutalism UI)."""
    try:
        return INDEX_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Xbox Checker API</h1>"
            "<p>Docs page (static/index.html) is missing. The API is still running — "
            "see /docs for the OpenAPI docs and /health for status.</p>"
        )


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(status_code=204, content=None)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
