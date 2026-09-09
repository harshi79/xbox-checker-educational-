# 🎮 Xbox Checker

Check Xbox & Microsoft account **Game Pass and subscription status** through a clean web console and a signed JSON API.

> 🔒 **Educational project** — only check accounts you own or are explicitly authorised to test. All checks are logged.

---

## Features

- **Real account checks** — Microsoft login → Xbox Live auth → profile, Game Pass & subscription detection (Ultimate / PC / Core / Gold, EA Play, …)
- **User accounts** — email + password registration with device fingerprinting (one account per device) and API-key authentication
- **Tiered rate limits** — `free` / `premium` / `pro` daily quotas, tracked per user
- **Watermarked & signed responses** — every result carries a watermark and an HMAC-SHA256 signature
- **Admin panel** — list users, change tiers, revoke keys (hidden `X-Admin-Key` flow in the console)
- **Polished console** — mobile-friendly, accessible, offline-safe UI with proper error handling
- **Zero-config database** — works out of the box with SQLite; plug in **Turso** for persistent production storage
- **Vercel-ready** — one-command deploy as a Python serverless function

## Architecture

```
Browser console (static/index.html)
        │  JSON + Bearer <api_key>
        ▼
FastAPI app (api/index.py) ──► Xbox checker (api/checker.py) ──► live.com / xboxlive.com
        │
        ├── auth (api/auth.py) — bcrypt/PBKDF2 passwords, API keys, JWT
        ├── rate limiting (api/rate_limit.py) — daily quotas per tier
        ├── watermarking (api/watermark.py) — HMAC signatures
        └── database (api/db.py) — Turso (libsql) with SQLite fallback
```

## 🚀 Deploy to Vercel

### 1. (Recommended) Create a Turso database

Without this the app still works, but user data is lost on serverless restarts (ephemeral filesystem).

```bash
curl -sSfL https://get.tur.so/install.sh | bash
turso auth login
turso db create xbox-checker
turso db show xbox-checker --url
turso db tokens create xbox-checker
```

### 2. Deploy

```bash
vercel --prod
```

### 3. Set environment variables

Vercel Dashboard → Project → **Settings → Environment Variables**:

| Variable | Required | Description |
|---|---|---|
| `TURSO_DATABASE_URL` | No* | e.g. `libsql://xbox-checker-<org>.turso.io` |
| `TURSO_AUTH_TOKEN` | No* | Turso auth token |
| `ADMIN_API_KEY` | **Yes** | Secret for `/admin/*` endpoints |
| `WATERMARK_SECRET` | **Yes** | Long random string for response signatures |
| `JWT_SECRET` | No | Random string for dashboard sessions |
| `FREE_DAILY_LIMIT` | No | Default `100` |
| `PREMIUM_DAILY_LIMIT` | No | Default `1000` |
| `PRO_DAILY_LIMIT` | No | Default `999999` |

\* Without Turso vars the app uses an ephemeral SQLite database (fine for trying out, not for real users).

Redeploy after changing env vars. Verify with `GET /health`:

```json
{ "status": "ok", "version": "1.1.0", "db_backend": "turso", "db": "up", "timestamp": "..." }
```

## 💻 Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional — SQLite works with no config at all
uvicorn api.index:app --reload
```

Open http://localhost:8000 — the console, API and docs (`/docs`) are served from the same app.

## 🔌 API reference

All authenticated endpoints take `Authorization: Bearer <api_key>`.

| Method & path | Auth | Description |
|---|---|---|
| `POST /auth/register` | — | `{email, password (≥8), device_fingerprint}` → `{api_key, tier}` |
| `POST /auth/login` | — | `{email, password}` → `{api_key, tier, access_token?}` |
| `GET /user/me` | API key | `{email, tier, daily_usage, daily_limit}` |
| `POST /user/key/revoke` | API key | Rotate the API key (old key dies immediately) |
| `POST /check` | API key | `{email, password, proxies?[]}` → signed result |
| `GET /admin/users` | `X-Admin-Key` | List users with usage stats |
| `PATCH /admin/users/{id}?tier=&revoke=&active=` | `X-Admin-Key` | Manage a user |
| `GET /health` | — | Liveness + DB status |

### Check result statuses

| Status | Meaning |
|---|---|
| `PREMIUM` | Valid account with an active Game Pass / subscription (`data.gamepass`, `data.gamertag`, `data.gamerscore`) |
| `FREE` | Valid account, no active subscription |
| `BAD` | Invalid credentials / account doesn't exist |
| `2FA` | Valid credentials, two-factor approval required |
| `BANNED` | Account banned or suspended |
| `TIMEOUT` / `ERROR` | Check couldn't complete (`error` field has details) |

Every result also includes `watermark`, `signature` (HMAC-SHA256 over the canonical JSON payload), `duration` and `rate_limit_remaining`.

## 🧪 Tests

```bash
# Backend: real app + isolated SQLite DB (stubs only the Xbox network call)
python3 qa-backend.test.py

# Frontend: jsdom suites against a mock API (needs node + jsdom)
node qa-mock-preview.mjs &      # mock server on :8080
node qa-live.test.js            # live-HTTP suite
node qa-frontend.test.js        # DOM/unit suite
```

## 📁 Project structure

```
api/            FastAPI app (index), auth, checker, db, rate_limit, watermark
static/         Web console (single-file app)
migrations/     SQL schema (auto-applied on startup)
requirements.txt / vercel.json / .env.example
qa-*.test.*     Backend + frontend test suites
```

## ⚠️ Responsible use

This tool interacts with real Microsoft/Xbox authentication endpoints. Only use it with accounts you own or are explicitly authorised to test. Credential-stuffing third-party accounts is illegal in most jurisdictions. The maintainers accept no liability for misuse.

## License

See [LICENSE](LICENSE).
