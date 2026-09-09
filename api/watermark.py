"""Response watermarking + HMAC signing.

Every checker response carries a ``watermark`` string and a hex ``signature``
(HMAC-SHA256 over the canonical JSON of the payload). Clients can verify
payload integrity when they hold the shared ``WATERMARK_SECRET``.
"""

import hashlib
import hmac
import json
import os
import secrets

WATERMARK_TEXT = "Provided by @yorichiiprime"
# Local development still works without configuration, but never falls back to
# a published, forgeable key. Production readiness reports missing config.
_PROCESS_SECRET = secrets.token_bytes(32)


def is_configured() -> bool:
    return len(os.environ.get("WATERMARK_SECRET", "")) >= 32


def _secret() -> bytes:
    configured = os.environ.get("WATERMARK_SECRET", "")
    return configured.encode() if configured else _PROCESS_SECRET


def sign_response(payload: dict) -> dict:
    """Return a copy of ``payload`` with ``watermark`` and ``signature`` added."""
    signable = {k: v for k, v in dict(payload).items() if k != "signature"}
    signable["watermark"] = WATERMARK_TEXT

    message = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return {**signable, "signature": signature}


def verify_signature(payload: dict) -> bool:
    """Verify an HMAC signature previously produced by :func:`sign_response`."""
    if not isinstance(payload, dict) or payload.get("watermark") != WATERMARK_TEXT:
        return False
    provided = payload.get("signature")
    if not isinstance(provided, str) or not provided:
        return False

    signable = {k: v for k, v in payload.items() if k != "signature"}
    message = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)
