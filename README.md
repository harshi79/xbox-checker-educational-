# Xbox Profile Lab

A consent-based educational FastAPI application that demonstrates account authentication, server-side sessions, Microsoft OAuth 2.0 with PKCE, Xbox profile retrieval, and Turso/libSQL persistence.

The application **never asks for a Microsoft password**. A user signs in on Microsoft's own domain, consents to Xbox profile access, and returns through a one-time OAuth callback. The old email/password/proxy checker is permanently retired.

## What it does

- Registers local workspace accounts with hashed passwords.
- Authenticates the browser with opaque, `HttpOnly`, database-backed cookies.
- Issues developer API keys once and stores only SHA-256 digest records at rest.
- Connects a consenting personal Microsoft account with authorization code + PKCE.
- Exchanges the short-lived Microsoft token for Xbox User/XSTS tokens server-side.
- Stores only a minimal Xbox profile snapshot: gamertag, gamerscore, XUID, Xbox account tier, and timestamps.
- Supports SQLite for local development and Turso/libSQL for persistent serverless deployment.
- Exposes liveness and production-readiness diagnostics without exposing secrets.

## What it deliberately does not do

- Collect, replay, or validate third-party Microsoft passwords.
- Accept or rotate proxies, automate sign-in pages, bypass MFA, or disable TLS.
- Persist Microsoft access, refresh, Xbox User, or XSTS tokens.
- Claim that Xbox `AccountTier` is a Game Pass subscription.
- Fabricate Game Pass results when Microsoft Store partner access is unavailable.

Microsoft documents Game Pass entitlement lookup as a publisher service. A participating publisher must be authorized for the relevant tiers through its Microsoft contact/Developer Partner Manager. A normal profile OAuth registration cannot provide a truthful generic Game Pass checker. See [Microsoft's Game Pass service documentation](https://learn.microsoft.com/en-us/gaming/gdk/docs/store/commerce/service-to-service/xstore-detecting-game-pass).

## Architecture

```text
Browser                         FastAPI                         External services
   |                               |                                  |
   |-- register/login ------------>|-- bcrypt/PBKDF2 ----------------> Turso or SQLite
   |<-- HttpOnly xb_session -------|   (only session digest stored)    |
   |                               |                                  |
   |-- /microsoft/connect -------->|-- hash OAuth state + store PKCE -> DB
   |<-- 302 -----------------------|                                  |
   |------------------------------ Microsoft authorization ---------->|
   |<-- authorization code -------------------------------------------|
   |-- callback + session -------->|-- atomic state consume ----------> DB
   |                               |-- code/token/Xbox exchanges ------> Microsoft/Xbox
   |                               |-- minimal profile snapshot -------> DB
   |<-- 303 / dashboard -----------|   (all tokens discarded)          |
```

The browser uses same-origin cookie sessions. Programmatic clients may use `Authorization: Bearer <developer-api-key>`. An explicitly invalid Bearer credential never falls back to an ambient browser cookie.

## Repository layout

```text
api/index.py             FastAPI routes, sessions, OAuth callbacks, readiness
api/auth.py              password, API-key digest, and opaque-session helpers
api/checker.py           fixed Microsoft/Xbox OAuth and profile integration
api/db.py                normalized async SQLite/Turso adapter
api/rate_limit.py        compatibility tier-usage metadata
api/watermark.py         server-side HMAC response signing
migrations/initial.sql   idempotent application schema
static/index.html        same-origin browser console
vercel.json              Vercel Python serverless routing
.env.example             complete environment template
```

## Local development

### 1. Install

Python 3.11 is the deployment runtime.

```bash
git clone <repository-url>
cd xbox-checker-educational-
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For local SQLite development, leave the Turso lines commented in `.env`, then set:

```dotenv
SESSION_COOKIE_SECURE=false
WATERMARK_SECRET=replace-with-at-least-32-random-characters
ADMIN_API_KEY=replace-with-a-different-random-value
```

Generate secrets with, for example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. Register the Microsoft application

Microsoft's official [Xbox services sign-in for title websites](https://learn.microsoft.com/en-us/gaming/gdk/docs/services/fundamentals/s2s-auth-calls/service-authentication/live-website-authentication) describes this provisioning flow.

1. In Microsoft Entra ID, open **App registrations** and choose **New registration**.
2. Select **Personal Microsoft accounts only** as the supported account type.
3. Add a **Web** redirect URI exactly matching the local callback:
   `http://localhost:8000/microsoft/callback`
4. Copy the **Application (client) ID** to `MICROSOFT_CLIENT_ID`.
5. Under **Certificates & secrets**, create a client secret and copy its **value** (not its identifier) to `MICROSOFT_CLIENT_SECRET`.
6. Set `MICROSOFT_REDIRECT_URI` to the exact same callback URL.

The application requests only `XboxLive.signin`, which is sufficient for immediate profile retrieval. It deliberately omits optional offline access, does not receive or persist a refresh token, and starts a new consented authorization when the user chooses to refresh.

### 3. Run

```bash
uvicorn api.index:app --host 0.0.0.0 --port 8000 --reload
```

Open <http://localhost:8000>. Useful diagnostics:

- <http://localhost:8000/health> — liveness; always HTTP 200 when the app process responds.
- <http://localhost:8000/ready> — dependency/configuration readiness; HTTP 503 when production requirements are missing.
- <http://localhost:8000/docs> — generated API reference.

The schema is initialized automatically with idempotent `CREATE TABLE IF NOT EXISTS` statements.

## Production deployment on Vercel

### 1. Create persistent Turso storage

A serverless function's `/tmp` SQLite file is ephemeral and can differ between instances. It is suitable only for liveness/diagnostic fallback. Production readiness fails and authentication routes return a clear 503 until a persistent Turso backend is configured, rather than creating users or sessions that appear to vanish.

```bash
turso db create xbox-profile-lab
turso db show xbox-profile-lab --url
turso db tokens create xbox-profile-lab
```

Store the URL and token as `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. Use a database-scoped token with only the access this app needs and rotate it if exposed.

### 2. Register the production callback

Add the exact HTTPS URL to the Entra application's **Web** redirect URIs, for example:

```text
https://your-project.vercel.app/microsoft/callback
```

Set this exact value as `MICROSOFT_REDIRECT_URI`. A stable production or custom domain is preferable. Preview deployments have different hostnames; either register and configure each preview callback separately or test OAuth on a stable staging domain.

### 3. Set Vercel environment variables

Set these for the appropriate Production/Preview environments in **Project Settings -> Environment Variables**:

| Variable | Production | Purpose |
|---|---:|---|
| `TURSO_DATABASE_URL` | Required | Persistent `libsql://` database URL |
| `TURSO_AUTH_TOKEN` | Required | Database-scoped Turso token |
| `MICROSOFT_CLIENT_ID` | Required | Entra application/client ID |
| `MICROSOFT_CLIENT_SECRET` | Required | Confidential Web application secret |
| `MICROSOFT_REDIRECT_URI` | Required | Exact HTTPS `/microsoft/callback` URL |
| `WATERMARK_SECRET` | Required | Independent random value, at least 32 characters |
| `ADMIN_API_KEY` | Recommended | Independent random admin credential; admin is disabled without it |
| `SESSION_TTL_SECONDS` | Optional | Cookie/session lifetime, default 7 days, max 30 days |
| `SESSION_COOKIE_SECURE` | Optional | Defaults to secure on Vercel; keep `true` |
| `LOGIN_MAX_ATTEMPTS` | Optional | Per email/client 15-minute login limit; default 10 |
| `REGISTRATION_MAX_ATTEMPTS` | Optional | Per-client hourly registration limit; default 8 |
| `CORS_ALLOW_ORIGINS` | Optional | Explicit origins only; same-origin UI needs none |

Do not put secrets in `vercel.json`, source code, browser JavaScript, or variables prefixed with `NEXT_PUBLIC_`/`VITE_`.

### 4. Deploy and verify

After deployment, verify in this order:

```bash
curl -i https://your-domain.example/health
curl -i https://your-domain.example/ready
curl -i https://your-domain.example/
```

`/health` identifies the database backend, persistence status, OAuth configuration status, response-signing status, application version, and non-secret warnings. `/ready` must return HTTP 200 before production traffic is considered healthy. On Vercel it returns 503 if Turso, Microsoft confidential OAuth, the exact redirect URI, or response signing is not configured.

Then perform a real browser smoke test:

1. Register a workspace account.
2. Log out and log back in; confirm the cookie session survives navigation.
3. Select **Connect Microsoft account** and confirm the browser goes to `login.microsoftonline.com`, not an application-owned password form.
4. Approve consent and confirm the gamertag/gamerscore snapshot appears.
5. Disconnect and confirm the snapshot is deleted.
6. Rotate the developer API key and confirm the old key receives 401.

## API behavior

### Authentication and account routes

| Route | Authentication | Behavior |
|---|---|---|
| `POST /auth/register` | None | Creates an account/session and returns a developer key once |
| `POST /auth/login` | None | Creates an opaque session; returns only the API-key preview |
| `POST /auth/logout` | Cookie optional | Revokes the current session and expires its cookie |
| `POST /auth/logout-all` | Cookie or Bearer | Revokes every browser session for the account |
| `GET /user/me` | Cookie or Bearer | Returns profile/tier data and only a key preview |
| `POST /user/key/revoke` | Cookie or Bearer | Atomically replaces the developer key and returns it once |

`POST /auth/register` retains the legacy JSON field name `device_fingerprint` for API compatibility. The browser now sends a random, local installation ID; it does not derive any value from canvas, screen, hardware, or user-agent signals.

### Microsoft routes

| Route | Authentication | Behavior |
|---|---|---|
| `GET /microsoft/status` | Cookie or Bearer | Returns the minimal saved profile and capability disclosure |
| `GET /microsoft/connect` | Cookie or Bearer | Stores ten-minute PKCE/state data and redirects to Microsoft |
| `GET /microsoft/callback` | Cookie or Bearer | Atomically consumes state, retrieves profile, discards tokens |
| `POST /microsoft/disconnect` | Cookie or Bearer | Deletes OAuth state and the saved profile snapshot |
| `POST /check` | Cookie or Bearer | Always HTTP 410; unsafe direct checking is retired |

### Admin routes

Admin calls require `X-Admin-Key`. Full API keys, password hashes, browser installation IDs, session tokens, and session hashes are not included in list output. An administrator may invalidate a developer key, but the endpoint returns only a preview; only the signed-in user can explicitly rotate and receive the replacement plaintext key.

```bash
curl -H "X-Admin-Key: $ADMIN_API_KEY" \
  https://your-domain.example/admin/users
```

Do not expose the admin endpoint directly to browser users in a production product. Prefer a private operator network or an identity-aware gateway in front of it.

## Security design

- Passwords use bcrypt when available. Long passphrases and fallback environments use a versioned 600,000-round PBKDF2-SHA256 format; verified legacy hashes are transparently upgraded at login.
- Unknown-account login checks use a dummy password hash to reduce timing differences.
- Login and registration throttles use atomic database counters keyed by one-way hashes, so limits work across serverless instances without storing source addresses/emails in the throttle table.
- Session and OAuth-state bearer values are high entropy and stored only as SHA-256 digests.
- Developer API keys carry 256 random bits; the database stores a digest plus a short display preview. Plaintext rows from an older release are transparently upgraded at login or API use.
- OAuth state is scoped to the local user, expires after ten minutes, and is consumed atomically with `DELETE ... RETURNING` before any upstream call.
- PKCE uses SHA-256 (`S256`). The OAuth client secret and code verifier never reach browser JavaScript.
- External URLs are fixed HTTPS Microsoft/Xbox endpoints, redirects are not followed, TLS verification is never disabled, and requests have bounded timeouts.
- The callback stores no Microsoft or Xbox token. Only the minimal profile snapshot persists.
- Cookie sessions use `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- Sensitive responses use `Cache-Control: no-store`; the app also sends CSP, frame, MIME-sniffing, referrer, permissions, and HSTS headers where applicable.
- HMAC signatures are created only server-side. The browser reports whether a signature is well formed but does not pretend to authenticate it, because browser code does not possess the shared secret.

## Quality assurance

The QA fixtures are excluded from Vercel by `.vercelignore`; their synthetic users and simulated OAuth route never ship with the application.

```bash
# Install pinned test-only packages (httpx2 TestClient + pip-audit)
pip install -r requirements-dev.txt

# Backend + isolated SQLite + mocked external Microsoft/Xbox calls
.venv/bin/python qa-backend.test.py

# Real libsql-client Row adapter + OAuth tables against a file-backed libSQL DB
.venv/bin/python qa-turso.test.py

# Install the pinned development-only browser harness
npm ci

# Browser DOM behavior
npm run test:frontend

# Live same-origin UI/API fixture (use two terminals)
npm run preview:qa
npm run test:live
```

External Microsoft calls are mocked only in automated QA. No test profile or entitlement is substituted by production code.

## Troubleshooting

### Vercel returns HTTP 500

1. Open `/health`. If it does not respond, inspect the Vercel function import/build log.
2. Confirm every package in `requirements.txt` installed and that Vercel uses Python 3.11.
3. Open `/ready`. A 503 with `db: down` normally indicates a Turso URL/token/network problem; configuration warnings identify missing non-secret variable names.
4. Confirm `TURSO_DATABASE_URL` begins with `libsql://` and that the token belongs to that database.
5. Confirm the exact Entra Web redirect URI matches `MICROSOFT_REDIRECT_URI`, including scheme, host, path, and environment.
6. Redeploy after changing Vercel variables; old function instances do not gain new environment values in place.
7. Use the returned `X-Request-ID` to correlate a safe client error with Vercel logs. Unhandled responses never include stack traces or credentials.

### Microsoft redirects back with an error

- `microsoft=expired`: state expired, was already consumed, belongs to another local session, or the callback was replayed. Start **Connect** again.
- `microsoft=cancelled`: the user denied/cancelled a callback carrying a valid state.
- `microsoft=invalid`: code or state was missing.
- `microsoft=error`: token exchange, Xbox authorization/profile access, or persistence failed. Inspect server logs by request ID without logging any token.

### Users disappear between requests

`/health` will show `db_backend: sqlite`, `db_persistent: false` on Vercel, and authentication will return 503 to prevent further ephemeral writes. Configure Turso. A `/tmp` SQLite database is not production persistence.

## References

- [Microsoft identity platform authorization-code flow with PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Xbox services sign-in for title websites](https://learn.microsoft.com/en-us/gaming/gdk/docs/services/fundamentals/s2s-auth-calls/service-authentication/live-website-authentication)
- [Microsoft Store: detecting Game Pass access from a publisher service](https://learn.microsoft.com/en-us/gaming/gdk/docs/store/commerce/service-to-service/xstore-detecting-game-pass)

## License

Educational use. Review your Microsoft, Xbox, Entra, Turso, and hosting terms before deploying a public service.
