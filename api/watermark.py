import hmac
import hashlib
import json
import os

WATERMARK_TEXT = "Provided by @yorichiiprime"
SECRET_KEY = os.environ.get("WATERMARK_SECRET", "dev-secret-change-in-prod").encode()

def sign_response(payload: dict) -> dict:
    """Add watermark and HMAC signature to response"""
    # Create copy without signature field for signing
    signable = {k: v for k, v in payload.items() if k != "signature"}
    signable["watermark"] = WATERMARK_TEXT
    
    # Generate signature
    message = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(SECRET_KEY, message, hashlib.sha256).hexdigest()
    
    # Return final payload
    return {
        **signable,
        "signature": signature
    }

def verify_signature(payload: dict) -> bool:
    """Verify HMAC signature (for internal use or client verification)"""
    if "signature" not in payload:
        return False
    provided_sig = payload.pop("signature")
    expected = sign_response(payload)["signature"]
    return hmac.compare_digest(provided_sig, expected)
