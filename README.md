# 🎮 Xbox Checker — Educational API Project

## 📚 Project Overview

**Xbox Checker** is an educational API project that teaches modern web development concepts by checking Xbox Live account subscriptions. It is intentionally **API + docs only** — a single self-contained docs/console page, **no login, no registration, no database, no frameworks**:

- **FastAPI** — modern Python web framework with auto-generated docs
- **Pydantic** — request validation and typed response schemas
- **Xbox Live OAuth 2.0** — the real Microsoft → Xbox auth token dance
- **HMAC-SHA256 cryptography** — response signing and verification

> ⚠️ **Educational Use Only**: This project is designed for learning purposes. Only check accounts you own or are explicitly authorised to test.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        EDUCATIONAL LAYERS                       │
├─────────────────────────────────────────────────────────────────┤
│  🌐 DOCS + CONSOLE (static/index.html, served at /)               │
│  • Single file, pure HTML/CSS/JS — no frameworks, no build step  │
│  • 3D brutalism UI: live API status, flip cards, 3D cube         │
│  • Live console — call POST /check, verify the HMAC signature    │
│    in-browser with Web Crypto, copy results as JSON or cURL      │
│  • Full API reference, status codes, proxy formats, quickstart   │
├─────────────────────────────────────────────────────────────────┤
│  🔧 API (api/index.py - FastAPI)                                 │
│  • POST /check — the only real endpoint                          │
│  • GET /health — service health                                  │
│  • GET /docs — auto-generated OpenAPI docs                       │
│  • Pydantic request/response validation                          │
│  • Generic JSON error handling (no stack traces leaked)          │
├─────────────────────────────────────────────────────────────────┤
│  🔐 SERVICES (api/)                                              │
│  • checker.py — Xbox Live auth flow + subscription detection     │
│  • watermark.py — HMAC-SHA256 response signing                   │
├─────────────────────────────────────────────────────────────────┤
│  📊 EXTERNAL SERVICES (live, called by checker.py)                │
│  • Microsoft login (login.live.com)                              │
│  • Xbox Live auth (user.auth.xboxlive.com, xsts.auth.xboxlive.com)│
│  • Xbox profile / subscriptions / store APIs                     │
│  • Minecraft entitlement services                                │
└─────────────────────────────────────────────────────────────────┘
```

There is deliberately **no authentication** on the API: no users table, no
API keys, no JWTs. This keeps the project a clean study of API design,
external service integration and cryptography. If you deploy it publicly,
put a gateway (rate limiting, API keys, auth) in front.

---

## 🛠️ Quick Start

### Prerequisites

- Python 3.11+

### 1. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Key Packages & What They Teach:**

| Package | Educational Focus |
|---------|-------------------|
| `fastapi` | Modern Python web framework, async, auto docs |
| `uvicorn` | ASGI server, production deployment |
| `pydantic` | Data validation, typed API schemas |
| `requests` | Synchronous HTTP client for the Xbox flow |
| `httpx` | Used by FastAPI's test client |
| `python-dotenv` | Optional local `.env` loading |

### 3. (Optional) Environment Configuration

```bash
cp .env.example .env
```

| Variable | Purpose |
|----------|---------|
| `WATERMARK_SECRET` | Shared secret for HMAC-SHA256 response signing |

### 4. Run Locally

```bash
uvicorn api.index:app --reload
```

- **Docs + live console**: http://localhost:8000 (this is where users start)
- Interactive API docs: http://localhost:8000/docs
- OpenAPI schema: http://localhost:8000/openapi.json
- Health check: http://localhost:8000/health

The console at `/` lets users run a real check in the browser and sees the
response's HMAC signature verified live (Web Crypto, using the secret from
`.env` when set) — the docs section on the same page covers every endpoint,
status code, proxy format and the quickstart.

---

## 📖 API Reference

### `POST /check`

Checks a Microsoft/Xbox account for active subscriptions. **No authentication
headers required.**

**Request body**

| Field | Type | Notes |
|-------|------|-------|
| `email` | string (1–320) | Microsoft account email |
| `password` | string (1–512) | Microsoft account password |
| `proxies` | string[] (optional, max 20) | `ip:port`, `user:pass:ip:port`, `http://host:port`, `socks5://host:port`, `user:pass@host:port` |

**Example**

```bash
curl -s http://localhost:8000/check \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

**Response `200`** — every check response is watermarked + HMAC signed:

```json
{
  "status": "PREMIUM",
  "duration": 4.21,
  "data": {
    "gamertag": "YourGamertag",
    "gamerscore": 12345,
    "subscriptions": ["XBOX GAME PASS ULTIMATE"],
    "gamepass": "XBOX GAME PASS ULTIMATE"
  },
  "watermark": "Provided by @yorichiiprime",
  "signature": "9f2c…64 hex chars…"
}
```

**`status` values**

| Status | Meaning |
|--------|---------|
| `PREMIUM` | Active subscription found (details in `data`) |
| `FREE` | Account valid, no active subscription |
| `BAD` | Credentials rejected / account does not exist |
| `2FA` | Account requires two-step verification |
| `BANNED` | Account suspended or banned |
| `TIMEOUT` | Upstream request timed out |
| `ERROR` | Something failed (see `error` field) |

**Errors**

| Code | When |
|------|------|
| `400` | Empty email/password after trimming |
| `413` | More than 20 proxies supplied |
| `422` | Invalid request body (Pydantic validation) |
| `500` | Unhandled internal error (JSON, no stack trace) |

### `GET /health`

```json
{ "status": "ok", "version": "2.0.0", "timestamp": "2026-09-10T12:00:00+00:00" }
```

### `GET /docs` & `GET /openapi.json`

Auto-generated interactive documentation (Swagger UI) and the OpenAPI
3.1 schema — built from the Pydantic models in `api/index.py`.

### `GET /`

The docs + live console page (single-file 3D brutalism UI, no frameworks).
Shows live API status, the full API reference, and a working form for
`POST /check` with in-browser signature verification.

---

## 🎓 Educational Concepts Covered

### 1. **FastAPI & Pydantic Schemas**

```python
class CheckRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=512)
    proxies: Optional[list[str]] = None
```

**Learning points:** type hints drive both validation *and* the auto docs at
`/docs`; `Field()` constraints enforce business rules before your code runs.

### 2. **OAuth 2.0 & the Xbox Live Auth Dance**

`api/checker.py` walks the real token chain:

1. **Login** — GET `login.live.com/oauth20_authorize.srf`, parse `PPFT`/`urlPost`
2. **Token exchange** — POST credentials, extract `access_token` from the redirect fragment
3. **Xbox auth** — RPS ticket → `user.auth.xboxlive.com` → XBL JWT
4. **XSTS auth** — XBL token → `xsts.auth.xboxlive.com` → XSTS token
5. **Probes** — profile (gamertag/gamerscore), subscriptions API, store
   purchases, Minecraft entitlements, Microsoft account services

**Learning points:** OAuth token fragments, chained token exchange, probing
multiple JSON APIs with one identity, and graceful handling of each failure
mode (`BAD`, `2FA`, `BANNED`, `TIMEOUT`).

### 3. **HMAC-SHA256 Response Signing**

```python
# api/watermark.py
message = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode()
signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
```

**Learning points:** canonical JSON serialization (sorted keys, compact
separators), integrity verification, tamper detection.

**Verify a signature yourself** (any client that knows the secret):

```python
import hashlib, hmac, json

def verify(payload: dict, secret: str) -> bool:
    provided = payload.pop("signature", None)
    expected = hmac.new(
        secret.encode(),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided or "", expected)
```

### 4. **API Design Best Practices**

| Pattern | Implementation | Educational Goal |
|---------|----------------|------------------|
| Typed responses | `CheckResponse` model | Predictable, documented output |
| Clear error codes | `400 / 413 / 422 / 500` | HTTP semantics done right |
| Versioning | `APP_VERSION = "2.0.0"` | API evolution |
| Safe errors | Generic JSON 500, no stack traces | Security by default |
| OpenAPI docs | `/docs`, `/openapi.json` | Docs as code |

### 5. **Proxy Handling**

`ProxyManager` in `checker.py` normalises many real-world proxy formats
(`ip:port`, `user:pass:ip:port`, scheme prefixes, `user:pass@host:port`),
tracks failing proxies, and rotates through the pool — a nice study in
defensive input normalisation.

### 6. **Canonical JSON & Cross-Language Crypto**

The console page verifies server signatures in the browser (Web Crypto).
Matching Python's `json.dumps(sort_keys=True, separators=(",",":"))`
byte-for-byte in JavaScript means: recursive key sorting, compact
separators, `ensure_ascii`-style `\uXXXX` escaping, and the `4.0` vs `4`
float edge. `qa-signature.test.mjs` proves the two sides agree.

**Learning points:** canonicalisation as a contract, Web Crypto HMAC,
surrogate-pair escaping, and how to test the same logic in two languages.

### 7. **A Whole UI in One File**

The docs/console page is a single dependency-free HTML file: CSS 3D
transforms (spinning cube, perspective flip cards, press-down buttons),
marquee, live API-status polling, and a working API client with error
handling — no frameworks, no build step.

---

## 🧪 Testing

### Backend (Python, offline)

```bash
python3 qa-backend.test.py
```

**44 assertions, fully offline:**
- Health, docs and the console page
- Login/register/admin endpoints are gone (404s)
- `/check` with a stubbed Xbox network (watermark + signature verification)
- Input validation (422 / 413 / 400 — never a 500)
- Checker input validation and proxy normalisation, all formats (no network)

### Cross-language signature audit (Node, optional)

```bash
node qa-signature.test.mjs
# if python3 lacks the deps:  PYTHON=.venv/bin/python node qa-signature.test.mjs
```

**14 assertions.** Extracts the pure canonical-JSON functions from the
console page, signs the same realistic payloads with the real Python
`watermark` module, and proves the two implementations agree byte-for-byte —
including the Python `4.0` vs JS `4` float edge case and tamper detection.
This is the guarantee that the in-browser "✓ SIGNATURE VERIFIED" badge is
actually true.

---

## 📁 Project Structure

```
xbox-checker-educational/
├── api/
│   ├── __init__.py          # package marker
│   ├── index.py             # FastAPI app + routes (the whole API)
│   ├── checker.py           # Xbox Live auth flow + subscription detection
│   └── watermark.py         # HMAC-SHA256 response signing
├── static/
│   └── index.html           # Docs + live console (served at /)
├── qa-backend.test.py       # Offline backend test suite (Python)
├── qa-signature.test.mjs    # JS<->Python signature audit (Node, optional)
├── requirements.txt         # Python dependencies
├── vercel.json              # Vercel deployment config
├── .env.example             # Environment variables template
└── README.md                # This documentation
```

---

## 🚀 Deployment (Vercel)

```bash
# 1. Push the repo and import it in Vercel (framework: Python)
# 2. vercel.json already routes everything to api/index.py
# 3. Set WATERMARK_SECRET in Project Settings → Environment Variables
# 4. vercel --prod

# Verify:
curl https://<your-project>.vercel.app/health
```

No database setup needed — there is no database.

---

## ⚠️ Responsible Use & Safety

This project teaches integration with Microsoft/Xbox APIs. Please observe:

1. **Only test accounts you own** — never check third-party accounts without permission
2. **API terms of service** — Microsoft's terms restrict automated access; this is a learning demo
3. **Credential security** — never hardcode secrets in real apps; the API itself is unauthenticated by design, so don't expose it publicly without a gateway
4. **Legal compliance** — credential stuffing and unauthorized account checking is illegal in most jurisdictions

---

## 🔧 Extending the Project

Learning opportunities:

1. **Add new subscription types** — extend `SUB_TYPES` in `checker.py`
2. **Rate limiting** — add a gateway in front (per-IP quotas, Redis-backed)
3. **Webhooks** — notify when an account's status changes
4. **Caching** — cache repeated checks of the same account for a short TTL
5. **Observability** — structured logging / OpenTelemetry spans
6. **Unit tests** — add tests for each checker step with recorded fixtures

---

## 📜 License

See [LICENSE](LICENSE) — this is an educational open-source project.

---

**Happy coding! This project is designed to be learned from, modified, and built upon.** 🎓

---

*Last updated: 2026-09-10*  
*Educational project for learning API design, OAuth flows and cryptography*
