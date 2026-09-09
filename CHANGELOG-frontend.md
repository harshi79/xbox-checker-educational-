# Xbox Profile Lab — v2 migration changelog

Date: 2026-09-10

This document supersedes the original frontend-only QA notes. The application is now an end-to-end, consent-based educational profile lab; descriptions of the former password/proxy checker are historical and no longer describe shipped behavior.

## Breaking security migration

- Removed the target-account email/password form, proxy list, proxy parsing/rotation, password visibility controls, `/check` submission code, and hit/bad result UI.
- Retired `POST /check` with HTTP 410. It does not parse or process a supplied Microsoft credential payload.
- Added Microsoft authorization-code OAuth with PKCE through the official `consumers` endpoint.
- Added one-time, user-scoped, ten-minute OAuth state stored only as a SHA-256 digest and consumed atomically before an upstream exchange.
- Microsoft, Xbox User, and XSTS tokens remain callback-local and are never returned, logged, or persisted.
- Added minimal Xbox profile snapshots and explicit disconnect/deletion.
- Added a truthful Game Pass capability notice. Generic entitlement output is not fabricated when Partner Center publisher authorization is unavailable.

## Browser authentication and privacy

- Replaced localStorage Bearer authentication with opaque `HttpOnly`, `SameSite=Lax`, production-`Secure` browser sessions owned by the backend.
- Full developer API keys appear only immediately after registration or explicit rotation and stay in current page memory. Login/session restore exposes only a preview.
- Replaced hardware/canvas/user-agent fingerprint generation with a random local installation ID. Older credential and fingerprint storage keys are removed during startup.
- Removed the browser HMAC secret and misleading authenticity claim. The UI reports signature shape only; verification belongs to a trusted client holding the server secret.
- Server values render through DOM text nodes, including hostile profile/admin values.

## Backend and persistence

- Fixed real `libsql-client` `Row` normalization, the production-only defect that broke named column reads.
- Added idempotent schema for sessions, authentication throttles, OAuth state, and Xbox profile connections.
- Added distributed, atomic login and registration throttles.
- Developer API credentials are stored as SHA-256 digest records plus non-secret previews. Older plaintext rows migrate transparently on use/login.
- Added liveness (`/health`) and strict production readiness (`/ready`) with non-secret database/OAuth/signing diagnostics.
- Admin list output excludes plaintext keys, password hashes, installation IDs, and session data. Admin revocation does not disclose a replacement credential.
- Added safe request IDs and production response hardening.

## User interface

- Renamed the product to **Xbox Profile Lab**.
- Added connected/disconnected Xbox states, profile refresh, disconnect, gamertag/gamerscore/account-tier presentation, callback outcomes, and clear operator configuration guidance.
- Retained registration, login, logout, tier/profile summary, one-time key copy/rotation, and redacted admin viewing.
- Preserved responsive layout, reduced-motion behavior, focus styles, live regions, explicit button types, noscript fallback, and mobile-safe controls.

## Deployment and dependencies

- Added a complete `.env.example` and Vercel/Turso/Entra deployment guide in `README.md`.
- Removed obsolete JWT, SOCKS, proxy, multipart, and email-validator runtime dependencies.
- Updated FastAPI, Starlette, Uvicorn, HTTPX, Pydantic, and python-dotenv to audited versions. `pip-audit` and `npm audit` report no known vulnerabilities.
- Added `.vercelignore` so synthetic QA users, the simulated OAuth preview, local secrets/databases, and Node development dependencies cannot enter the production bundle.
- Added pinned Python and Node development dependencies for reproducible full-matrix QA.

## QA commands

```bash
.venv/bin/python qa-backend.test.py
.venv/bin/python qa-turso.test.py
npm ci
npm run test:frontend
npm run preview:qa   # terminal 1
npm run test:live    # terminal 2
```

Latest clean matrix: **76/76 backend**, **15/15 real-libSQL**, **71/71 frontend DOM**, and **33/33 live HTTP** assertions (**195 total**), plus a real Uvicorn root/health/readiness/register/session/OAuth-redirect smoke test. `pip check`, `pip-audit`, `npm audit`, Ruff import/undefined-name checks, compile, JSON, JavaScript syntax, HTML ID/label, and Git whitespace checks also pass.

External Microsoft/Xbox calls are mocked only by automated QA. Production code has no demo login, profile, entitlement, or fallback result.
