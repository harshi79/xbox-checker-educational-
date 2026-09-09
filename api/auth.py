"""Authentication helpers for passwords, API keys and opaque sessions.

Password hashing prefers ``passlib[bcrypt]`` but transparently falls back to
a stdlib PBKDF2-SHA256 scheme if passlib/bcrypt is unavailable or broken.
Browser sessions and developer API keys are random opaque values; only their
SHA-256 digests (plus a non-secret API-key display preview) are stored.
"""

import hashlib
import logging
import os
import secrets

log = logging.getLogger(__name__)

try:
    from passlib.context import CryptContext

    _pwd_context: CryptContext | None = CryptContext(
        schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=True
    )
except Exception as exc:  # pragma: no cover - environment dependent
    log.warning("passlib unavailable (%s); using PBKDF2 fallback for passwords", exc)
    _pwd_context = None

SESSION_COOKIE_NAME = "xb_session"
DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 7

_PBKDF2_ITERATIONS = 600_000
_LEGACY_PBKDF2_ITERATIONS = 210_000
_PBKDF2_PREFIX = "pbkdf2_sha256$"
_LEGACY_PBKDF2_PREFIX = "pbkdf2$"
# Used when an email is unknown so failed logins take approximately the same
# amount of work and do not become a cheap account-enumeration timing oracle.
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$3f7b1d9a2c4e6f801122334455667788$"
    "9116506c6e458832a2918cf73ab7d20a0229c4c1e496f29d9332a68ad4ce749d"
)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def _pbkdf2_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_PREFIX}{_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _pbkdf2_verify(password: str, hashed: str) -> bool:
    try:
        parts = hashed.split("$")
        if len(parts) == 3 and parts[0] == "pbkdf2":
            # Compatibility with hashes issued by the original release.
            iterations = _LEGACY_PBKDF2_ITERATIONS
            salt_hex, digest_hex = parts[1:]
        elif len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            iterations = int(parts[1])
            salt_hex, digest_hex = parts[2:]
            if not 100_000 <= iterations <= 1_000_000:
                return False
        else:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
        )
        return secrets.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (or PBKDF2 fallback).

    Bcrypt has a 72-byte input boundary. Use PBKDF2 for longer Unicode
    passphrases rather than silently truncating two distinct passwords.
    """
    if len(password.encode("utf-8")) > 72:
        return _pbkdf2_hash(password)
    if _pwd_context is not None:
        try:
            return _pwd_context.hash(password)
        except Exception as exc:
            log.warning("bcrypt hashing failed (%s); using PBKDF2 fallback", exc)
    return _pbkdf2_hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt or PBKDF2 hash."""
    if not plain or not hashed:
        return False
    if hashed.startswith((_PBKDF2_PREFIX, _LEGACY_PBKDF2_PREFIX)):
        return _pbkdf2_verify(plain, hashed)
    if _pwd_context is not None:
        try:
            return bool(_pwd_context.verify(plain, hashed))
        except Exception:
            return False
    return False


def password_needs_rehash(hashed: str) -> bool:
    """Whether a verified hash should be upgraded during successful login."""
    if hashed.startswith(_LEGACY_PBKDF2_PREFIX):
        return True
    if hashed.startswith(_PBKDF2_PREFIX):
        try:
            return int(hashed.split("$", 2)[1]) != _PBKDF2_ITERATIONS
        except (TypeError, ValueError, IndexError):
            return True
    if _pwd_context is not None:
        try:
            return bool(_pwd_context.needs_update(hashed))
        except Exception:
            return True
    return False


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

_API_KEY_RECORD_PREFIX = "sha256$"


def generate_api_key() -> str:
    return f"xbsp_{secrets.token_urlsafe(32)}"


def api_key_record(api_key: str) -> str:
    """Return the deterministic, non-reversible database form of an API key.

    The prefix/suffix are retained only so the dashboard can identify a key;
    authentication uses the SHA-256 digest. API keys have 256 random bits, so
    an offline dictionary attack against a leaked database is impractical.
    """
    value = str(api_key or "")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{_API_KEY_RECORD_PREFIX}{digest}${value[:9]}${value[-4:]}"


def is_api_key_record(value: str) -> bool:
    parts = str(value or "").split("$")
    return (
        len(parts) == 4
        and parts[0] == "sha256"
        and len(parts[1]) == 64
        and all(char in "0123456789abcdef" for char in parts[1])
    )


def preview_api_key(api_key: str) -> str:
    """Return a safe display form for a raw key or stored digest record."""
    value = str(api_key or "")
    if is_api_key_record(value):
        _, _, prefix, suffix = value.split("$", 3)
        return f"{prefix}…{suffix}" if prefix and suffix else "••••"
    if len(value) < 13:
        return "••••"
    return f"{value[:9]}…{value[-4:]}"


# ---------------------------------------------------------------------------
# Opaque browser sessions
# ---------------------------------------------------------------------------

def generate_session_token() -> str:
    """Return a high-entropy bearer value suitable for an HttpOnly cookie."""
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    """Hash a session token before database storage or lookup."""
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def session_ttl_seconds() -> int:
    """Read and safely clamp the browser session lifetime."""
    try:
        value = int(os.environ.get("SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS))
    except (TypeError, ValueError):
        value = DEFAULT_SESSION_TTL_SECONDS
    return max(300, min(value, 60 * 60 * 24 * 30))
