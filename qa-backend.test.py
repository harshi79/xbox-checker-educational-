"""Backend smoke tests — real FastAPI app, stubbed Xbox network.

Run:  python3 qa-backend.test.py
Requires: pip install -r requirements.txt

No database, no login, no registration — the app is API-only now.
Everything is real except the external Xbox/Microsoft HTTP calls, which
are stubbed so the suite runs offline.
"""

import sys

import api.checker as checker_mod  # noqa: E402
from api import watermark as wm  # noqa: E402
from api.index import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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

section("A. Health, root & docs")
r = client.get("/health")
ok("GET /health -> 200", r.status_code == 200, r.text[:200])
ok("health reports status ok", r.json().get("status") == "ok", r.text[:200])
ok("health reports version", bool(r.json().get("version")), r.text[:200])

r = client.get("/")
ok("GET / -> 200 HTML docs+console", r.status_code == 200 and "XBOX CHECKER" in r.text, str(r.status_code))
ok("page content-type is html", r.headers.get("content-type", "").startswith("text/html"), str(r.headers.get("content-type")))
ok("page contains live console form", 'id="check-form"' in r.text, "console form missing")
ok("page documents POST /check", "POST /check" in r.text, "docs section missing")
ok("page links Swagger /docs", 'href="/docs"' in r.text, "swagger link missing")

r = client.get("/docs")
ok("GET /docs -> 200", r.status_code == 200, str(r.status_code))
r = client.get("/openapi.json")
ok("GET /openapi.json -> 200", r.status_code == 200, str(r.status_code))
ok("openapi lists /check", "/check" in r.json().get("paths", {}), str(list(r.json().get("paths", {}))))

section("B. Login/register fully removed")
for path, method in [
    ("/auth/register", "post"),
    ("/auth/login", "post"),
    ("/user/me", "get"),
    ("/user/key/revoke", "post"),
    ("/admin/users", "get"),
    ("/admin/status", "get"),
]:
    r = getattr(client, method)(path)
    ok(f"{method.upper()} {path} -> 404 (removed)", r.status_code == 404, r.text[:200])

section("C. Check endpoint (stubbed Xbox network, NO auth needed)")
r = client.post("/check", json={"email": "player@example.com", "password": "secretpw"})
body = r.json() if r.status_code == 200 else {}
ok("/check -> 200 PREMIUM", r.status_code == 200 and body.get("status") == "PREMIUM", r.text[:400])
ok("no Authorization header required", r.status_code == 200, r.text[:200])
ok("gamertag in data", body.get("data", {}).get("gamertag") == "QATester", r.text[:300])
ok("watermark present", body.get("watermark") == wm.WATERMARK_TEXT, r.text[:300])
ok("signature present (64 hex)", isinstance(body.get("signature"), str) and len(body["signature"]) == 64, r.text[:300])
ok("server-side signature verifies", wm.verify_signature(dict(body)), "hmac mismatch")

r = client.post("/check", json={"email": "a@b.co", "password": "pw", "proxies": ["1.2.3.4:8080"]})
ok("proxies list accepted", r.status_code == 200, r.text[:300])

r = client.post("/check", json={"email": "", "password": "x"})
ok("empty email -> 422 (not 500)", r.status_code == 422, r.text[:200])
r = client.post("/check", json={"email": "a@b.c"})
ok("missing password -> 422 (not 500)", r.status_code == 422, r.text[:200])
r = client.post("/check", json={})
ok("empty body -> 422 (not 500)", r.status_code == 422, r.text[:200])
r = client.post("/check", json={"email": "a@b.c", "password": "x",
                                "proxies": [f"1.1.1.{i}:8080" for i in range(25)]})
ok("too many proxies -> 413 (not 500)", r.status_code == 413, r.text[:200])

section("D. Checker input validation (no network)")
res = checker_mod.check_account("", "")
ok("empty creds -> ERROR dict, no raise", res.get("status") == "ERROR", str(res))
res = checker_mod.check_account("a@b.co", "pw", proxies="not-a-list")
ok("bad proxies type -> ERROR dict, no raise", res.get("status") == "ERROR", str(res))
res = checker_mod.check_account("a" * 400, "pw")
ok("oversized email -> ERROR dict, no raise", res.get("status") == "ERROR", str(res))

section("E. Proxy normalisation (no network)")
pm = checker_mod.ProxyManager(["1.2.3.4:8080", "http://5.6.7.8:3128",
                               "user:pass:9.9.9.9:1080", "socks5://10.0.0.1:1080"])
ok("has_proxies true", pm.has_proxies())
for raw in ["1.2.3.4:8080", "http://5.6.7.8:3128", "user:pass:9.9.9.9:1080", "socks5://10.0.0.1:1080"]:
    p = pm.get()
    ok(f"{raw!r} -> http proxy dict", isinstance(p, dict) and p.get("http", "").startswith("http://"), str(p))
    pm.mark_bad(raw)
ok("all bad -> None", pm.get() is None)

pm_empty = checker_mod.ProxyManager([])
ok("no proxies -> None", pm_empty.get() is None and not pm_empty.has_proxies())

# Each format in isolation (random rotation makes shared pools ambiguous).
expected = {
    "1.2.3.4:8080": "http://1.2.3.4:8080",
    "http://5.6.7.8:3128": "http://5.6.7.8:3128",
    "user:pass:9.9.9.9:1080": "http://9.9.9.9:1080",
    "socks5://10.0.0.1:1080": "http://10.0.0.1:1080",
    "user:pass@10.0.0.1:1080": "http://user:pass@10.0.0.1:1080",
    "@3.3.3.3:1": "http://3.3.3.3:1",
}
for raw, want in expected.items():
    got = checker_mod.ProxyManager([raw]).get()
    ok(f"isolated {raw!r} -> {want!r}", isinstance(got, dict) and got.get("http") == want, str(got))

print("\n" + "=" * 60)
print(f"  \x1b[1m{PASS} passed, {FAIL} failed\x1b[0m   (backend, real FastAPI app, offline)")
if FAILURES:
    print("\n  Failures:")
    for f in FAILURES:
        print(f"   - {f}")
print("=" * 60)

sys.exit(1 if FAIL else 0)
