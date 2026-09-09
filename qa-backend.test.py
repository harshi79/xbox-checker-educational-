"""Backend integration tests — real FastAPI app + isolated SQLite database.

Only Microsoft's external OAuth/Xbox HTTP calls are stubbed; registration,
password hashing, cookies, database sessions, OAuth state, profile persistence,
admin operations and signatures use the real application code.

Run:  python3 qa-backend.test.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

_tmp = tempfile.NamedTemporaryFile(prefix="xbox_qa_", suffix=".db", delete=False)
_tmp.close()
os.environ["SQLITE_PATH"] = _tmp.name
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ["ADMIN_API_KEY"] = "qa-admin-key"
os.environ["WATERMARK_SECRET"] = "qa-watermark-secret-at-least-32-characters"
os.environ["MICROSOFT_CLIENT_ID"] = "qa-microsoft-client"
os.environ["MICROSOFT_CLIENT_SECRET"] = "qa-microsoft-client-secret"
os.environ["MICROSOFT_REDIRECT_URI"] = "http://localhost/microsoft/callback"
os.environ["FREE_DAILY_LIMIT"] = "2"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.checker as checker_mod  # noqa: E402
from api import auth as auth_mod  # noqa: E402
from api import watermark as wm  # noqa: E402
from api.index import app  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def ok(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  \033[32mPASS\033[0m {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  \033[31mFAIL\033[0m {name}" + (f"\n        -> {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


exchange_seen: dict = {}


async def _fake_exchange(*, code: str, verifier: str, redirect_uri: str) -> str:
    exchange_seen.update(code=code, verifier=verifier, redirect_uri=redirect_uri)
    return "qa-consented-access-token-that-is-never-persisted"


async def _fake_profile(access_token: str) -> dict:
    exchange_seen["access_token"] = access_token
    return {
        "gamertag": "ConsentTester",
        "gamerscore": 12345,
        "xuid": "2533274800000001",
        "account_tier": "Gold",
    }


_real_exchange_authorization_code = checker_mod.exchange_authorization_code
_real_fetch_xbox_profile = checker_mod.fetch_xbox_profile
_real_async_client = httpx.AsyncClient
checker_mod.exchange_authorization_code = _fake_exchange
checker_mod.fetch_xbox_profile = _fake_profile

client = TestClient(app)

section("A. Health, readiness and root")
response = client.get("/health")
ok("GET /health -> 200", response.status_code == 200, response.text)
ok("health reports SQLite up", response.json().get("db_backend") == "sqlite" and response.json().get("db") == "up", response.text)
ok("local SQLite reports persistent", response.json().get("db_persistent") is True, response.text)
ok("security/request headers present", bool(response.headers.get("x-request-id")) and response.headers.get("x-content-type-options") == "nosniff", str(response.headers))
response = client.get("/ready")
ok("GET /ready -> 200", response.status_code == 200 and response.json().get("db") == "up", response.text)
response = client.get("/")
ok("GET / serves professional console", response.status_code == 200 and "Xbox Profile Lab" in response.text and "Microsoft password is never" in response.text, str(response.status_code))
ok("root has CSP and frame protection", "frame-ancestors 'none'" in response.headers.get("content-security-policy", "") and response.headers.get("x-frame-options") == "DENY", str(response.headers))
response = client.get("/docs")
ok(
    "generated API docs load with a path-scoped asset CSP",
    response.status_code == 200
    and "Swagger UI" in response.text
    and "https://cdn.jsdelivr.net" in response.headers.get("content-security-policy", ""),
    str(response.headers),
)

section("B. Registration")
response = client.post(
    "/auth/register",
    json={
        "email": "QA@Example.com",
        "password": "password123",
        "device_fingerprint": "qa-device-001",
    },
)
body = response.json()
key = body.get("api_key", "")
ok("register -> 201 with one-time API key", response.status_code == 201 and key.startswith("xbsp_"), response.text)
ok("email is normalized", body.get("email") == "qa@example.com", response.text)
cookie = response.headers.get("set-cookie", "")
ok("HttpOnly SameSite session issued", "xb_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie, cookie)
ok("auth response is not cacheable", response.headers.get("cache-control") == "no-store", str(response.headers))
with sqlite3.connect(_tmp.name) as raw_db:
    stored_key = raw_db.execute(
        "SELECT api_key FROM users WHERE email = ?", ("qa@example.com",)
    ).fetchone()[0]
ok(
    "database stores only an API-key digest record",
    stored_key.startswith("sha256$") and key not in stored_key,
    stored_key,
)
# Simulate credentials created by a pre-v2 deployment; successful login below
# must upgrade them without changing the plaintexts held by the user/client.
legacy_login_salt = bytes.fromhex("102132435465768798a9bacbdcedfe0f")
legacy_login_digest = hashlib.pbkdf2_hmac(
    "sha256", b"password123", legacy_login_salt, 210_000
)
legacy_login_hash = f"pbkdf2${legacy_login_salt.hex()}${legacy_login_digest.hex()}"
with sqlite3.connect(_tmp.name) as raw_db:
    raw_db.execute(
        "UPDATE users SET api_key = ?, password_hash = ? WHERE email = ?",
        (key, legacy_login_hash, "qa@example.com"),
    )
    raw_db.commit()

response = client.post(
    "/auth/register",
    json={"email": "qa@example.com", "password": "password123", "device_fingerprint": "qa-device-002"},
)
ok("duplicate email -> 409", response.status_code == 409, response.text)
response = client.post(
    "/auth/register",
    json={"email": "other@example.com", "password": "password123", "device_fingerprint": "qa-device-001"},
)
ok("duplicate device -> 409", response.status_code == 409, response.text)
response = client.post(
    "/auth/register",
    json={"email": "bad-email", "password": "short", "device_fingerprint": "x"},
)
ok("invalid payload -> 422 without import-time email-validator", response.status_code == 422, response.text)
os.environ["REGISTRATION_MAX_ATTEMPTS"] = "3"
response = client.post(
    "/auth/register",
    json={"email": "throttled@example.com", "password": "password123", "device_fingerprint": "qa-device-003"},
)
ok(
    "registration throttle is database-backed and returns 429",
    response.status_code == 429 and response.headers.get("retry-after") == "3600",
    response.text,
)
os.environ.pop("REGISTRATION_MAX_ATTEMPTS", None)

section("C. Login and backend browser session")
response = client.post("/auth/login", json={"email": "qa@example.com", "password": "password123"})
ok(
    "login -> 200 without re-disclosing developer key",
    response.status_code == 200
    and response.json().get("session") == "active"
    and "api_key" not in response.json()
    and "api_key_preview" in response.json(),
    response.text,
)
with sqlite3.connect(_tmp.name) as raw_db:
    migrated_key, migrated_password = raw_db.execute(
        "SELECT api_key, password_hash FROM users WHERE email = ?", ("qa@example.com",)
    ).fetchone()
ok(
    "login transparently migrates a legacy plaintext API key",
    migrated_key.startswith("sha256$") and key not in migrated_key,
    migrated_key,
)
ok(
    "login transparently upgrades a legacy password hash",
    migrated_password != legacy_login_hash
    and auth_mod.verify_password("password123", migrated_password),
    migrated_password,
)
response = client.post("/auth/login", json={"email": "qa@example.com", "password": "wrongpass1"})
ok("wrong password -> generic 401", response.status_code == 401 and response.json().get("detail") == "Incorrect email or password", response.text)
os.environ["LOGIN_MAX_ATTEMPTS"] = "3"
for _ in range(4):
    throttled_login = client.post(
        "/auth/login",
        json={"email": "brute-force@example.com", "password": "wrongpass1"},
    )
ok(
    "login throttle is atomic and returns Retry-After",
    throttled_login.status_code == 429 and throttled_login.headers.get("retry-after") == "900",
    throttled_login.text,
)
os.environ.pop("LOGIN_MAX_ATTEMPTS", None)

response = client.get("/user/me")
ok("cookie authenticates with no JS token", response.status_code == 200 and response.json().get("auth_method") == "session", response.text)
ok("profile includes only API-key preview", "api_key_preview" in response.json() and "api_key" not in response.json(), response.text)
response = client.get("/user/me", headers={"Authorization": f"Bearer {key}"})
ok("developer Bearer API key remains supported", response.status_code == 200 and response.json().get("auth_method") == "api_key", response.text)
response = client.get("/user/me", headers={"Authorization": "Bearer definitely-wrong"})
ok("bad explicit key cannot fall back to cookie", response.status_code == 401, response.text)
anonymous = TestClient(app)
response = anonymous.get("/user/me")
ok("no cookie/header -> 401", response.status_code == 401, response.text)

section("D. Microsoft OAuth + real profile persistence")
response = client.get("/microsoft/status")
status = response.json()
ok("initial Microsoft status is disconnected", response.status_code == 200 and status.get("connected") is False, response.text)
ok("status advertises OAuth but not fake Game Pass access", status.get("capabilities", {}).get("oauth_configured") is True and status.get("capabilities", {}).get("game_pass_entitlement_access") is False, response.text)
ok("status response is server-signed", wm.verify_signature(dict(status)), response.text)
tampered_status = dict(status)
tampered_status["watermark"] = "forged"
ok("signature verification rejects watermark tampering", not wm.verify_signature(tampered_status))

response = client.get("/microsoft/connect", follow_redirects=False)
location = response.headers.get("location", "")
query = parse_qs(urlparse(location).query)
state = query.get("state", [""])[0]
ok("connect redirects only to Microsoft consumers OAuth", response.status_code == 302 and location.startswith(checker_mod.AUTHORIZE_URL), location)
ok("OAuth request contains state + PKCE S256", bool(state) and query.get("code_challenge_method") == ["S256"] and bool(query.get("code_challenge", [""])[0]), location)
ok(
    "OAuth scope is least-privilege Xbox sign-in without offline access",
    query.get("scope") == ["XboxLive.signin"],
    location,
)

response = client.get(
    "/microsoft/callback",
    params={"code": "qa-one-time-code", "state": state},
    follow_redirects=False,
)
ok("callback consumes state and redirects to success", response.status_code == 303 and response.headers.get("location") == "/?microsoft=connected", str(response.headers))
ok("callback sent PKCE verifier to token exchange", exchange_seen.get("code") == "qa-one-time-code" and len(exchange_seen.get("verifier", "")) > 40, str(exchange_seen))
ok("temporary Microsoft token only reached profile adapter", exchange_seen.get("access_token", "").startswith("qa-consented"), str(exchange_seen))

response = client.get("/microsoft/status")
status = response.json()
profile = status.get("profile") or {}
ok(
    "connected profile is the minimal OAuth snapshot",
    status.get("connected") is True
    and profile.get("gamertag") == "ConsentTester"
    and profile.get("gamerscore") == 12345
    and "display_picture" not in profile,
    response.text,
)
ok("tokens are absent from status payload", "token" not in response.text.lower(), response.text)
with sqlite3.connect(_tmp.name) as raw_db:
    database_dump = "\n".join(raw_db.iterdump())
ok(
    "authorization code and Microsoft token are absent from database",
    "qa-one-time-code" not in database_dump
    and "qa-consented-access-token-that-is-never-persisted" not in database_dump,
)

response = client.get(
    "/microsoft/callback",
    params={"code": "replay", "state": state},
    follow_redirects=False,
)
ok("OAuth state cannot be replayed", response.status_code == 303 and response.headers.get("location") == "/?microsoft=expired", str(response.headers))

# A denied authorization must also carry and consume a valid state.
response = client.get("/microsoft/connect", follow_redirects=False)
denied_state = parse_qs(urlparse(response.headers.get("location", "")).query).get("state", [""])[0]
response = client.get(
    "/microsoft/callback",
    params={"error": "access_denied", "state": denied_state},
    follow_redirects=False,
)
ok("denied OAuth callback validates and consumes state", response.status_code == 303 and response.headers.get("location") == "/?microsoft=cancelled", str(response.headers))
response = client.get(
    "/microsoft/callback",
    params={"error": "access_denied", "state": denied_state},
    follow_redirects=False,
)
ok("denied callback state cannot be replayed", response.headers.get("location") == "/?microsoft=expired", str(response.headers))
response = client.get(
    "/microsoft/callback",
    params={"error": "access_denied"},
    follow_redirects=False,
)
ok("OAuth error without state is rejected", response.headers.get("location") == "/?microsoft=invalid", str(response.headers))

response = client.post("/microsoft/disconnect")
ok("disconnect -> 200", response.status_code == 200, response.text)
response = client.get("/microsoft/status")
ok("disconnect removes profile snapshot", response.status_code == 200 and response.json().get("connected") is False, response.text)

response = client.post(
    "/check",
    json={"email": "someone@example.com", "password": "must-not-be-accepted", "proxies": []},
)
ok("legacy password checker is retired with 410", response.status_code == 410 and "OAuth" in response.json().get("detail", ""), response.text)

section("E. API-key rotation")
response = client.post("/user/key/revoke", headers={"Authorization": f"Bearer {key}"})
new_key = response.json().get("api_key", "") if response.status_code == 200 else ""
ok("rotation returns a new key", response.status_code == 200 and new_key.startswith("xbsp_") and new_key != key, response.text)
response = client.get("/user/me", headers={"Authorization": f"Bearer {key}"})
ok("old key is immediately rejected", response.status_code == 401, response.text)
response = client.get("/user/me", headers={"Authorization": f"Bearer {new_key}"})
ok("new key works", response.status_code == 200, response.text)

section("F. Admin")
response = client.get("/admin/users")
ok("missing admin key -> 403, not 500", response.status_code == 403, response.text)
response = client.get("/admin/users", headers={"X-Admin-Key": "wrong"})
ok("wrong admin key -> 403", response.status_code == 403, response.text)
response = client.get("/admin/users", headers={"X-Admin-Key": "qa-admin-key"})
users = response.json().get("users", []) if response.status_code == 200 else []
ok("admin lists real database users", response.status_code == 200 and any(u.get("email") == "qa@example.com" for u in users), response.text)
ok("admin never exposes full keys/fingerprints", bool(users) and "api_key" not in users[0] and "device_fingerprint" not in users[0] and "api_key_preview" in users[0], str(users))
user_id = next((u["id"] for u in users if u.get("email") == "qa@example.com"), None)
response = client.patch(f"/admin/users/{user_id}?tier=premium", headers={"X-Admin-Key": "qa-admin-key"})
ok("admin can change tier", response.status_code == 200, response.text)
response = client.get("/user/me", headers={"Authorization": f"Bearer {new_key}"})
ok("tier update is reflected", response.json().get("tier") == "premium" and response.json().get("daily_limit") == 1000, response.text)
response = client.patch("/admin/users/999999?tier=pro", headers={"X-Admin-Key": "qa-admin-key"})
ok("unknown admin user -> 404", response.status_code == 404, response.text)

section("G. Server-side logout")
response = client.post("/auth/logout")
ok("logout -> 204 and expires cookie", response.status_code == 204 and "xb_session=" in response.headers.get("set-cookie", ""), str(response.headers))
response = client.get("/user/me")
ok("logged-out session -> 401", response.status_code == 401, response.text)
response = client.get("/user/me", headers={"Authorization": f"Bearer {new_key}"})
ok("browser logout does not revoke developer key", response.status_code == 200, response.text)

section("H. OAuth helper safety")
original_redirect = os.environ["MICROSOFT_REDIRECT_URI"]
os.environ["MICROSOFT_REDIRECT_URI"] = "http://localhost.evil.example/callback"
response = client.get(
    "/microsoft/connect",
    headers={"Authorization": f"Bearer {new_key}"},
    follow_redirects=False,
)
os.environ["MICROSOFT_REDIRECT_URI"] = original_redirect
ok("redirect validation rejects localhost-prefix lookalikes", response.status_code == 503, response.text)
response = client.patch(
    f"/admin/users/{user_id}?revoke=true",
    headers={"X-Admin-Key": "qa-admin-key"},
)
ok(
    "admin can revoke but cannot retrieve a replacement credential",
    response.status_code == 200
    and "api_key" not in response.json()
    and "api_key_preview" in response.json(),
    response.text,
)
response = client.get("/user/me", headers={"Authorization": f"Bearer {new_key}"})
ok("admin revocation invalidates the old developer key", response.status_code == 401, response.text)
pair = checker_mod.create_pkce_pair()
expected_challenge = __import__("base64").urlsafe_b64encode(
    __import__("hashlib").sha256(pair.verifier.encode("ascii")).digest()
).rstrip(b"=").decode("ascii")
ok("PKCE challenge matches verifier", pair.challenge == expected_challenge and len(pair.verifier) > 40)
source = open(os.path.join(os.path.dirname(__file__), "api", "checker.py"), encoding="utf-8").read().lower()
ok("checker contains no password/proxy form automation", "passwd" not in source and "proxymanager" not in source and "verify = false" not in source)
long_password = "é" * 80
long_hash = auth_mod.hash_password(long_password)
ok(
    "long Unicode passwords use versioned PBKDF2 without bcrypt truncation",
    long_hash.startswith("pbkdf2_sha256$600000$")
    and auth_mod.verify_password(long_password, long_hash)
    and not auth_mod.verify_password(long_password + "x", long_hash)
    and not auth_mod.password_needs_rehash(long_hash),
)
legacy_salt = bytes.fromhex("00112233445566778899aabbccddeeff")
legacy_digest = hashlib.pbkdf2_hmac("sha256", b"legacy-password", legacy_salt, 210_000)
legacy_hash = f"pbkdf2${legacy_salt.hex()}${legacy_digest.hex()}"
ok(
    "pre-v2 PBKDF2 password hashes remain valid",
    auth_mod.verify_password("legacy-password", legacy_hash)
    and not auth_mod.verify_password("wrong-password", legacy_hash)
    and auth_mod.password_needs_rehash(legacy_hash),
)

section("I. Microsoft/Xbox HTTP adapter contract")
token_request: dict = {}


async def _token_transport(request: httpx.Request) -> httpx.Response:
    token_request["url"] = str(request.url)
    token_request["form"] = parse_qs(request.content.decode("utf-8"))
    return httpx.Response(200, json={"access_token": "m" * 48, "token_type": "Bearer"})


def _client_for(transport: httpx.MockTransport):
    def factory(**kwargs):
        return _real_async_client(transport=transport, **kwargs)
    return factory


checker_mod.httpx.AsyncClient = _client_for(httpx.MockTransport(_token_transport))
try:
    adapter_token = asyncio.run(
        _real_exchange_authorization_code(
            code="adapter-code",
            verifier="v" * 64,
            redirect_uri="http://localhost/microsoft/callback",
        )
    )
finally:
    checker_mod.httpx.AsyncClient = _real_async_client
ok(
    "token exchange uses fixed HTTPS consumers endpoint",
    token_request.get("url") == checker_mod.TOKEN_URL and adapter_token == "m" * 48,
    str(token_request),
)
ok(
    "token exchange sends code, PKCE verifier, redirect, and confidential secret",
    token_request.get("form", {}).get("code") == ["adapter-code"]
    and token_request.get("form", {}).get("code_verifier") == ["v" * 64]
    and token_request.get("form", {}).get("client_secret") == ["qa-microsoft-client-secret"],
    str(token_request.get("form")),
)

xbox_requests: list[tuple[str, str]] = []


async def _xbox_transport(request: httpx.Request) -> httpx.Response:
    xbox_requests.append((request.method, str(request.url)))
    if str(request.url) == checker_mod.XBOX_USER_AUTH_URL:
        payload = __import__("json").loads(request.content)
        ok(
            "Xbox User Token request carries consented token as RPS ticket",
            payload.get("Properties", {}).get("RpsTicket") == "d=" + ("m" * 48),
            str(payload),
        )
        return httpx.Response(200, json={
            "Token": "user-token",
            "DisplayClaims": {"xui": [{"uhs": "user-stage-hash"}]},
        })
    if str(request.url) == checker_mod.XSTS_URL:
        return httpx.Response(200, json={
            "Token": "xsts-token",
            "DisplayClaims": {"xui": [{
                "uhs": "xsts-stage-hash", "xid": "2810000000000007", "gtg": "FallbackTag"
            }]},
        })
    if str(request.url) == checker_mod.XBOX_PROFILE_URL:
        token_header = request.headers.get("authorization", "")
        ok(
            "profile request pairs XSTS token with its own user hash",
            token_header == "XBL3.0 x=xsts-stage-hash;xsts-token",
            token_header,
        )
        return httpx.Response(200, json={
            "profileUsers": [{
                "id": "2810000000000007",
                "settings": [
                    {"id": "Gamertag", "value": "AdapterPlayer"},
                    {"id": "Gamerscore", "value": "54321"},
                    {"id": "AccountTier", "value": "Gold"},
                ],
            }]
        })
    return httpx.Response(500, json={"unexpected": str(request.url)})


checker_mod.httpx.AsyncClient = _client_for(httpx.MockTransport(_xbox_transport))
try:
    adapter_profile = asyncio.run(_real_fetch_xbox_profile("m" * 48))
finally:
    checker_mod.httpx.AsyncClient = _real_async_client
ok(
    "Xbox adapter follows fixed User Token, XSTS, and profile sequence",
    [url for _, url in xbox_requests] == [
        checker_mod.XBOX_USER_AUTH_URL,
        checker_mod.XSTS_URL,
        checker_mod.XBOX_PROFILE_URL,
    ],
    str(xbox_requests),
)
ok(
    "Xbox adapter safely normalizes the minimal profile",
    adapter_profile == {
        "gamertag": "AdapterPlayer",
        "gamerscore": 54321,
        "xuid": "2810000000000007",
        "account_tier": "Gold",
    },
    str(adapter_profile),
)

section("J. Fail-safe serverless configuration")
os.environ["VERCEL"] = "1"
response = client.get("/health")
serverless_health = response.json()
ok(
    "serverless liveness stays 200 with non-secret warnings",
    response.status_code == 200
    and serverless_health.get("db") == "up"
    and serverless_health.get("db_persistent") is False
    and "TURSO_AUTH_TOKEN" not in response.text,
    response.text,
)
response = client.get("/ready")
ok("misconfigured production readiness is 503", response.status_code == 503, response.text)
response = client.post(
    "/auth/register",
    json={
        "email": "must-not-be-ephemeral@example.com",
        "password": "password123",
        "device_fingerprint": "serverless-installation",
    },
)
ok(
    "production rejects ephemeral auth writes with 503, not 500",
    response.status_code == 503 and "Persistent database" in response.json().get("detail", ""),
    response.text,
)
os.environ.pop("VERCEL", None)

print("\n" + "=" * 60)
print(f"  \033[1m{PASS} passed, {FAIL} failed\033[0m   (backend + SQLite)")
if FAILURES:
    print("\n  Failures:")
    for failure in FAILURES:
        print(f"   - {failure}")
print("=" * 60)

try:
    os.unlink(_tmp.name)
except FileNotFoundError:
    pass
sys.exit(1 if FAIL else 0)
