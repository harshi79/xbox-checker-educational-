"""Turso/libSQL regression tests using the real libsql-client Row type.

This catches a production-only failure that SQLite tests cannot see: SDK Row
objects are Sequences with ``asdict()``, not list/tuple instances.

Run:  python3 qa-turso.test.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

_db_file = tempfile.NamedTemporaryFile(prefix="xbox_turso_qa_", suffix=".db", delete=False)
_db_file.close()
os.unlink(_db_file.name)  # libSQL creates the database itself

os.environ["TURSO_DATABASE_URL"] = f"file:{_db_file.name}"
os.environ["TURSO_AUTH_TOKEN"] = ""
os.environ["ADMIN_API_KEY"] = "qa-admin-key"
os.environ["WATERMARK_SECRET"] = "qa-watermark-secret-at-least-32-characters"
os.environ["FREE_DAILY_LIMIT"] = "2"
os.environ["MICROSOFT_CLIENT_ID"] = "qa-client-id"
os.environ["MICROSOFT_CLIENT_SECRET"] = "qa-client-secret"
os.environ["MICROSOFT_REDIRECT_URI"] = "http://localhost/microsoft/callback"

from fastapi.testclient import TestClient  # noqa: E402

from api.index import app  # noqa: E402

passed = 0
failed = 0
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  \033[32mPASS\033[0m {name}")
    else:
        failed += 1
        failures.append(name)
        print(f"  \033[31mFAIL\033[0m {name}" + (f"\n        -> {detail}" if detail else ""))


with TestClient(app) as client:
    print("\n\033[1mTurso/libSQL backend\033[0m")
    response = client.get("/health")
    check(
        "health reports reachable Turso",
        response.status_code == 200
        and response.json().get("db_backend") == "turso"
        and response.json().get("db") == "up",
        response.text,
    )

    response = client.post(
        "/auth/register",
        json={
            "email": "turso@example.com",
            "password": "password123",
            "device_fingerprint": "turso-device-001",
        },
    )
    key = response.json().get("api_key", "") if response.status_code == 201 else ""
    check("registration writes and reads back a named Row", response.status_code == 201 and key.startswith("xbsp_"), response.text)
    check("registration issues browser session", "xb_session=" in response.headers.get("set-cookie", ""), str(response.headers))
    with sqlite3.connect(_db_file.name) as raw_db:
        stored_key = raw_db.execute(
            "SELECT api_key FROM users WHERE email = ?", ("turso@example.com",)
        ).fetchone()[0]
    check(
        "database stores only API-key digest record",
        stored_key.startswith("sha256$") and key not in stored_key,
        stored_key,
    )

    response = client.post(
        "/auth/login",
        json={"email": "turso@example.com", "password": "password123"},
    )
    check(
        "login reads password_hash/email/tier by column name",
        response.status_code == 200
        and response.json().get("email") == "turso@example.com"
        and response.json().get("tier") == "free"
        and "api_key" not in response.json()
        and "api_key_preview" in response.json(),
        response.text,
    )

    response = client.get("/user/me")
    check(
        "session JOIN maps named columns",
        response.status_code == 200
        and response.json().get("auth_method") == "session"
        and response.json().get("daily_limit") == 2,
        response.text,
    )

    response = client.get("/user/me", headers={"Authorization": f"Bearer {key}"})
    check("developer API key still authenticates", response.status_code == 200, response.text)

    print("\n\033[1mOAuth tables through real libSQL rows\033[0m")
    response = client.get("/microsoft/connect", follow_redirects=False)
    location = response.headers.get("location", "")
    state = parse_qs(urlparse(location).query).get("state", [""])[0]
    check(
        "connect persists one-time PKCE state and redirects to Microsoft",
        response.status_code == 302
        and urlparse(location).hostname == "login.microsoftonline.com"
        and bool(state),
        str(response.headers),
    )

    xbox_profile = {
        "xuid": "2810000000000001",
        "gamertag": "TursoPlayer",
        "gamerscore": 2718,
        "account_tier": "Gold",
    }
    with patch(
        "api.index.checker.exchange_authorization_code",
        new=AsyncMock(return_value="microsoft-access-token-not-persisted"),
    ), patch(
        "api.index.checker.fetch_xbox_profile",
        new=AsyncMock(return_value=xbox_profile),
    ):
        response = client.get(
            "/microsoft/callback",
            params={"code": "one-time-code", "state": state},
            follow_redirects=False,
        )
    check(
        "callback atomically consumes libSQL state and persists profile",
        response.status_code == 303 and response.headers.get("location") == "/?microsoft=connected",
        str(response.headers),
    )

    response = client.get(
        "/microsoft/callback",
        params={"code": "replay", "state": state},
        follow_redirects=False,
    )
    check(
        "DELETE RETURNING makes OAuth state one-time",
        response.status_code == 303 and response.headers.get("location") == "/?microsoft=expired",
        str(response.headers),
    )

    response = client.get("/microsoft/status")
    status_body = response.json() if response.status_code == 200 else {}
    check(
        "profile status maps OAuth table columns by name",
        response.status_code == 200
        and status_body.get("connected") is True
        and status_body.get("profile", {}).get("gamertag") == "TursoPlayer"
        and "access_token" not in response.text,
        response.text,
    )

    response = client.post("/microsoft/disconnect")
    check("disconnect removes persisted profile", response.status_code == 200, response.text)
    response = client.get("/microsoft/status")
    check(
        "status confirms disconnect",
        response.status_code == 200 and response.json().get("connected") is False,
        response.text,
    )

    response = client.get("/admin/users", headers={"X-Admin-Key": "qa-admin-key"})
    users = response.json().get("users", []) if response.status_code == 200 else []
    check(
        "admin fetchall maps named columns",
        response.status_code == 200
        and len(users) == 1
        and users[0].get("email") == "turso@example.com"
        and users[0].get("daily_usage") == 0,
        response.text,
    )
    check(
        "admin output masks secret key",
        bool(users) and "api_key" not in users[0] and "api_key_preview" in users[0],
        str(users),
    )

print("\n" + "=" * 60)
print(f"  \033[1m{passed} passed, {failed} failed\033[0m   (real libsql-client)")
if failures:
    print("\n  Failures:")
    for failure in failures:
        print(f"   - {failure}")
print("=" * 60)

try:
    os.unlink(_db_file.name)
except FileNotFoundError:
    pass
sys.exit(1 if failed else 0)
