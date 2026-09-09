"""Response watermarking + HMAC signing.

Every checker response carries a ``watermark`` string and a hex ``signature``
(HMAC-SHA256 over the canonical JSON of the payload). Clients can verify
payload integrity when they hold the shared ``WATERMARK_SECRET``.
"""

import hashlib
import hmac
import json
import os

WATERMARK_TEXT = "Provided by @yorichiiprime"
_FALLBACK_SECRET = "dev-secret-change-in-prod"


def _secret() -> bytes:
    return os.environ.get("WATERMARK_SECRET", _FALLBACK_SECRET).encode()


def sign_response(payload: dict) -> dict:
    """Return a copy of ``payload`` with ``watermark`` and ``signature`` added."""
    signable = {k: v for k, v in dict(payload).items() if k != "signature"}
    signable["watermark"] = WATERMARK_TEXT

    message = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return {**signable, "signature": signature}


def verify_signature(payload: dict) -> bool:
    """Verify an HMAC signature previously produced by :func:`sign_response`."""
    if not isinstance(payload, dict) or "signature" not in payload:
        return False
    provided = payload["signature"]
    if not isinstance(provided, str) or not provided:
        return False
    expected = sign_response(payload)["signature"]
    try:
        return hmac.compare_digest(provided, expected)
    except Exception:
        return False
