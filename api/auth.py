"""Authentication helpers: password hashing, API keys, and JWT sessions.

Password hashing prefers ``passlib[bcrypt]`` but transparently falls back to
a stdlib PBKDF2-SHA256 scheme if passlib/bcrypt is unavailable or broken
(a known issue with some bcrypt 4.x + passlib combinations). Hashes are
self-describing, so verification works for either scheme.
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

try:
    from passlib.context import CryptContext

    _pwd_context: CryptContext | None = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as exc:  # pragma: no cover - environment dependent
    log.warning("passlib unavailable (%s); using PBKDF2 fallback for passwords", exc)
    _pwd_context = None

try:
    from jose import jwt, JWTError
except Exception as exc:  # pragma: no cover - environment dependent
    log.warning("python-jose unavailable (%s); JWT sessions disabled", exc)
    jwt = None  # type: ignore[assignment]
    JWTError = Exception  # type: ignore[assignment,misc]

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

_PBKDF2_ITERATIONS = 210_000
_PBKDF2_PREFIX = "pbkdf2$"


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def _pbkdf2_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_PREFIX}{salt.hex()}${digest.hex()}"


def _pbkdf2_verify(password: str, hashed: str) -> bool:
    try:
        _, salt_hex, digest_hex = hashed.split("$", 2)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS
        )
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (or PBKDF2 fallback)."""
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
    if hashed.startswith(_PBKDF2_PREFIX):
        return _pbkdf2_verify(plain, hashed)
    if _pwd_context is not None:
        try:
            return bool(_pwd_context.verify(plain, hashed))
        except Exception:
            return False
    return False


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def generate_api_key() -> str:
    return f"xbsp_{secrets.token_urlsafe(32)}"


# ---------------------------------------------------------------------------
# JWT (dashboard sessions; the API itself authenticates via API key)
# ---------------------------------------------------------------------------

def _jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "dev-only-fallback-secret-change-me")


def create_jwt_token(data: dict, expires_delta: timedelta | None = None) -> str | None:
    """Create a signed JWT, or return None when JWT support is unavailable."""
    if jwt is None:
        return None
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict | None:
    """Decode a JWT, returning None when invalid or unsupported."""
    if jwt is None or not token:
        return None
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    except Exception:
        return None
