"""Backend smoke tests — real FastAPI app + real (SQLite) database.

Run:  python3 qa-backend.test.py
Requires: pip install -r requirements.txt

Uses an isolated temp SQLite file (no Turso needed) and stubs only the
external Xbox network call.
"""

import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(prefix="xbox_qa_", suffix=".db", delete=False)
_tmp.close()
os.environ["SQLITE_PATH"] = _tmp.name
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ["ADMIN_API_KEY"] = "qa-admin-key"
os.environ["WATERMARK_SECRET"] = "qa-secret"
os.environ["JWT_SECRET"] = "qa-jwt"

from fastapi.testclient import TestClient  # noqa: E402

import api.checker as checker_mod  # noqa: E402
from api.index import app  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \x1b[32mPASS\x1b[0m {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  \x1b[31mFAIL\x1b[0m {name}" + (f"\n        -> {extra}" if extra else ""))


def section(title: str) -> None:
    print(f"\n\x1b[1m{title}\x1b[0m")


# Stub the external network call (everything else is real).
async def _fake_check(email, password, proxies=None):
    return {
        "status": "PREMIUM",
        "data": {"gamertag": "QATester", "gamerscore": 12345, "gamepass": "XBOX GAME PASS ULTIMATE"},
        "duration": 0.42,
    }


checker_mod.check_account_async = _fake_check

client = TestClient(app)

section("A. Health & root")
r = client.get("/health")
ok("GET /health -> 200", r.status_code == 200, r.text[:200])
ok("health reports sqlite backend", r.json().get("db_backend") == "sqlite", r.text[:200])
ok("health db is up", r.json().get("db") == "up", r.text[:200])
r = client.get("/")
ok("GET / -> 200 HTML console", r.status_code == 200 and "Xbox Checker" in r.text, str(r.status_code))

section("B. Registration")
r = client.post("/auth/register", json={
    "email": "qa@example.com", "password": "password123", "device_fingerprint": "qa-device-001",
})
ok("register -> 201 with api_key", r.status_code == 201 and bool(r.json().get("api_key")), r.text[:300])
key = r.json().get("api_key", "")
ok("api_key has xbsp_ prefix", key.startswith("xbsp_"), key)

r = client.post("/auth/register", json={
    "email": "qa@example.com", "password": "password123", "device_fingerprint": "qa-device-002",
})
ok("duplicate email -> 409", r.status_code == 409, r.text[:200])
r = client.post("/auth/register", json={
    "email": "other@example.com", "password": "password123", "device_fingerprint": "qa-device-001",
})
ok("duplicate device -> 409", r.status_code == 409, r.text[:200])
r = client.post("/auth/register", json={
    "email": "bad-email", "password": "short", "device_fingerprint": "x",
})
ok("invalid payload -> 422", r.status_code == 422, r.text[:200])

section("C. Login & profile")
r = client.post("/auth/login", json={"email": "qa@example.com", "password": "password123"})
ok("login -> 200 with api_key", r.status_code == 200 and r.json().get("api_key") == key, r.text[:300])
r = client.post("/auth/login", json={"email": "qa@example.com", "password": "wrongpass1"})
ok("wrong password -> 401", r.status_code == 401, r.text[:200])

r = client.get("/user/me", headers={"Authorization": f"Bearer {key}"})
ok("/user/me -> 200 with usage", r.status_code == 200 and r.json().get("daily_limit") == 100, r.text[:300])
r = client.get("/user/me", headers={"Authorization": "Bearer nope"})
ok("bad key -> 401 (not 422/500)", r.status_code == 401, r.text[:200])
r = client.get("/user/me")
ok("missing auth -> 401 (not 422/500)", r.status_code == 401, r.text[:200])

section("D. Check endpoint (stubbed Xbox network)")
r = client.post("/check", headers={"Authorization": f"Bearer {key}"},
                json={"email": "player@example.com", "password": "secretpw", "proxies": []})
body = r.json() if r.status_code == 200 else {}
ok("/check -> 200 PREMIUM", r.status_code == 200 and body.get("status") == "PREMIUM", r.text[:400])
ok("watermark present", body.get("watermark") == "Provided by @yorichiiprime", r.text[:300])
ok("signature present", isinstance(body.get("signature"), str) and len(body["signature"]) == 64, r.text[:300])
ok("rate_limit_remaining present", isinstance(body.get("rate_limit_remaining"), int), r.text[:300])

from api import watermark as wm  # noqa: E402
ok("server-side signature verifies", wm.verify_signature(dict(body)), "hmac mismatch")

r = client.get("/user/me", headers={"Authorization": f"Bearer {key}"})
ok("usage incremented to 1", r.json().get("daily_usage") == 1, r.text[:200])

r = client.post("/check", headers={"Authorization": f"Bearer {key}"},
                json={"email": "", "password": "x"})
ok("empty email -> 400/422 (not 500)", r.status_code in (400, 422), r.text[:200])

r = client.post("/check", headers={"Authorization": f"Bearer {key}"},
                json={"email": "a@b.c", "password": "x", "proxies": [f"http://h:{i}" for i in range(60)]})
ok("too many proxies -> 413/422 (not 500)", r.status_code in (413, 422), r.text[:200])

section("E. Key rotation")
r = client.post("/user/key/revoke", headers={"Authorization": f"Bearer {key}"})
new_key = r.json().get("api_key", "") if r.status_code == 200 else ""
ok("revoke -> 200 new key", r.status_code == 200 and new_key and new_key != key, r.text[:200])
r = client.get("/user/me", headers={"Authorization": f"Bearer {key}"})
ok("old key -> 401", r.status_code == 401, r.text[:200])
r = client.get("/user/me", headers={"Authorization": f"Bearer {new_key}"})
ok("new key -> 200", r.status_code == 200, r.text[:200])

section("F. Admin")
r = client.get("/admin/users")
ok("no admin key -> 403 (not 500)", r.status_code == 403, r.text[:200])
r = client.get("/admin/users", headers={"X-Admin-Key": "wrong"})
ok("wrong admin key -> 403 (not 500)", r.status_code == 403, r.text[:200])
r = client.get("/admin/users", headers={"X-Admin-Key": "qa-admin-key"})
users = r.json().get("users", []) if r.status_code == 200 else []
ok("admin lists users", r.status_code == 200 and any(u.get("email") == "qa@example.com" for u in users), r.text[:400])
has_cols = users and "daily_usage" in users[0] and "total_checks" in users[0]
ok("usage/total_checks columns present", bool(has_cols), str(users[0].keys()) if users else "no users")
uid = next((u["id"] for u in users if u.get("email") == "qa@example.com"), None)
r = client.patch(f"/admin/users/{uid}?tier=premium", headers={"X-Admin-Key": "qa-admin-key"})
ok("admin sets tier -> 200", r.status_code == 200, r.text[:200])
r = client.get("/user/me", headers={"Authorization": f"Bearer {new_key}"})
ok("tier is premium with limit 1000", r.json().get("tier") == "premium" and r.json().get("daily_limit") == 1000, r.text[:200])
r = client.patch("/admin/users/999999?tier=pro", headers={"X-Admin-Key": "qa-admin-key"})
ok("unknown user -> 404", r.status_code == 404, r.text[:200])

section("G. Checker input validation (no network)")
res = checker_mod.check_account("", "")
ok("empty creds -> ERROR dict, no raise", res.get("status") == "ERROR", str(res))
res = checker_mod.check_account("a@b.co", "pw", proxies="not-a-list")
ok("bad proxies type -> ERROR dict, no raise", res.get("status") == "ERROR", str(res))

print("\n" + "=" * 60)
print(f"  \x1b[1m{PASS} passed, {FAIL} failed\x1b[0m   (backend, real app + sqlite)")
if FAILURES:
    print("\n  Failures:")
    for f in FAILURES:
        print(f"   - {f}")
print("=" * 60)

os.unlink(_tmp.name)
sys.exit(1 if FAIL else 0)
