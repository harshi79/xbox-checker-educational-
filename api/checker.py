"""Consent-based Microsoft/Xbox account connection.

This module intentionally uses Microsoft's OAuth 2.0 authorization-code flow
with PKCE. It never accepts Microsoft passwords, rotates proxies, disables TLS
verification, or automates the Microsoft sign-in form.

A normal Entra application can retrieve the consenting user's Xbox profile.
Game Pass subscription entitlement APIs are partner services and require a
Microsoft Partner Center relationship/authorization; this project therefore
never invents subscription data when that capability is unavailable.

Official references:
- https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow
- https://learn.microsoft.com/gaming/gdk/docs/services/fundamentals/s2s-auth-calls/service-authentication/live-website-authentication
- https://learn.microsoft.com/gaming/gdk/docs/store/commerce/service-to-service/xstore-detecting-game-pass
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBOX_USER_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
XBOX_PROFILE_URL = (
    "https://profile.xboxlive.com/users/me/profile/settings"
    "?settings=Gamertag,Gamerscore,AccountTier"
)
# Immediate profile retrieval needs sign-in scope only. Offline access would
# mint a refresh token that this privacy-minimizing implementation never uses.
OAUTH_SCOPES = "XboxLive.signin"
UPSTREAM_TIMEOUT_SECONDS = 20.0


class XboxIntegrationError(RuntimeError):
    """Safe, user-facing integration failure (never contains a token)."""


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def has_client_id() -> bool:
    return bool(os.environ.get("MICROSOFT_CLIENT_ID", "").strip())


def has_client_secret() -> bool:
    return bool(os.environ.get("MICROSOFT_CLIENT_SECRET", "").strip())


def is_configured() -> bool:
    """Whether the confidential Entra Web application is fully configured."""
    return has_client_id() and has_client_secret()


def configuration() -> dict[str, Any]:
    """Return non-secret capability information for the dashboard."""
    return {
        "oauth_configured": is_configured(),
        "oauth_provider": "Microsoft identity platform",
        "oauth_flow": "authorization_code_pkce",
        "profile_access": is_configured(),
        "game_pass_entitlement_access": False,
        "game_pass_requirement": (
            "Microsoft Partner Center publisher authorization is required for "
            "Game Pass entitlement queries. No demo result is substituted."
        ),
        "manage_subscriptions_url": "https://account.microsoft.com/services",
    }


def create_pkce_pair() -> PkcePair:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


def create_state() -> str:
    return secrets.token_urlsafe(48)


def hash_state(state: str) -> str:
    return hashlib.sha256(str(state or "").encode("utf-8")).hexdigest()


def authorization_url(*, state: str, challenge: str, redirect_uri: str) -> str:
    client_id = os.environ.get("MICROSOFT_CLIENT_ID", "").strip()
    if not client_id:
        raise XboxIntegrationError("Microsoft OAuth is not configured")
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": OAUTH_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise XboxIntegrationError("Microsoft returned an unreadable response") from exc
    if not isinstance(payload, dict):
        raise XboxIntegrationError("Microsoft returned an unexpected response")
    return payload


async def exchange_authorization_code(
    *, code: str, verifier: str, redirect_uri: str
) -> str:
    """Exchange one authorization code for an Xbox-scoped Microsoft token."""
    client_id = os.environ.get("MICROSOFT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MICROSOFT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise XboxIntegrationError("Microsoft OAuth is not configured")

    form = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": OAUTH_SCOPES,
        "code_verifier": verifier,
    }
    form["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(
            timeout=UPSTREAM_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                TOKEN_URL,
                data=form,
                headers={"Accept": "application/json"},
            )
    except httpx.TimeoutException as exc:
        raise XboxIntegrationError("Microsoft sign-in timed out; please try again") from exc
    except httpx.HTTPError as exc:
        raise XboxIntegrationError("Microsoft sign-in is temporarily unavailable") from exc

    payload = _safe_json(response)
    access_token = payload.get("access_token")
    if response.status_code != 200 or not isinstance(access_token, str) or len(access_token) < 20:
        error = str(payload.get("error", "authorization_failed"))
        if error == "invalid_grant":
            raise XboxIntegrationError("The sign-in approval expired or was already used")
        raise XboxIntegrationError("Microsoft did not approve the requested Xbox access")
    return access_token


_XSTS_ERRORS = {
    2148916229: "This Xbox account is currently restricted",
    2148916233: "This Microsoft account does not have an Xbox profile yet",
    2148916235: "Xbox services are not available in this account region",
    2148916236: "This account needs adult verification before using Xbox services",
    2148916237: "This account needs adult verification before using Xbox services",
    2148916238: "A family organizer must add this child account to an Xbox family",
}


async def fetch_xbox_profile(access_token: str) -> dict[str, Any]:
    """Exchange a consented Microsoft token and return a minimal Xbox profile.

    Tokens are held only in local variables for this request and are never
    returned, logged, or persisted by this function.
    """
    if not access_token or len(access_token) < 20:
        raise XboxIntegrationError("Microsoft access token is missing")

    try:
        async with httpx.AsyncClient(
            timeout=UPSTREAM_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            user_response = await client.post(
                XBOX_USER_AUTH_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "x-xbl-contract-version": "1",
                },
                json={
                    "Properties": {
                        "AuthMethod": "RPS",
                        "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": f"d={access_token}",
                    },
                    "RelyingParty": "http://auth.xboxlive.com",
                    "TokenType": "JWT",
                },
            )
            user_payload = _safe_json(user_response)
            user_token = user_payload.get("Token")
            claims = user_payload.get("DisplayClaims", {}).get("xui", [])
            user_hash = claims[0].get("uhs") if claims and isinstance(claims[0], dict) else None
            if (
                user_response.status_code != 200
                or not isinstance(user_token, str)
                or not isinstance(user_hash, str)
                or not user_token
                or not user_hash
            ):
                raise XboxIntegrationError("Xbox could not create a user token for this account")

            xsts_response = await client.post(
                XSTS_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "x-xbl-contract-version": "1",
                },
                json={
                    "Properties": {"SandboxId": "RETAIL", "UserTokens": [user_token]},
                    "RelyingParty": "http://xboxlive.com",
                    "TokenType": "JWT",
                },
            )
            xsts_payload = _safe_json(xsts_response)
            if xsts_response.status_code != 200:
                try:
                    code = int(xsts_payload.get("XErr", 0))
                except (TypeError, ValueError):
                    code = 0
                raise XboxIntegrationError(
                    _XSTS_ERRORS.get(code, "Xbox did not authorize profile access")
                )

            xsts_token = xsts_payload.get("Token")
            xui = xsts_payload.get("DisplayClaims", {}).get("xui", [])
            xui_claim = xui[0] if xui and isinstance(xui[0], dict) else {}
            # The XSTS response is authoritative for the user hash paired with
            # its token. It normally equals the User Token claim, but using the
            # matching XSTS claim avoids constructing a mismatched XBL3.0 pair.
            xsts_user_hash = xui_claim.get("uhs") or user_hash
            if (
                not isinstance(xsts_token, str)
                or not isinstance(xsts_user_hash, str)
                or not xsts_token
                or not xsts_user_hash
            ):
                raise XboxIntegrationError("Xbox returned an incomplete authorization response")

            profile_response = await client.get(
                XBOX_PROFILE_URL,
                headers={
                    "Authorization": f"XBL3.0 x={xsts_user_hash};{xsts_token}",
                    "Accept": "application/json",
                    "x-xbl-contract-version": "2",
                },
            )
            profile_payload = _safe_json(profile_response)
            if profile_response.status_code != 200:
                raise XboxIntegrationError("Xbox profile data is temporarily unavailable")
    except XboxIntegrationError:
        raise
    except httpx.TimeoutException as exc:
        raise XboxIntegrationError("Xbox profile request timed out; please try again") from exc
    except httpx.HTTPError as exc:
        raise XboxIntegrationError("Xbox profile service is temporarily unavailable") from exc

    profile_users = profile_payload.get("profileUsers", [])
    profile_user = profile_users[0] if profile_users and isinstance(profile_users[0], dict) else {}
    settings = profile_user.get("settings", []) if isinstance(profile_user, dict) else []
    values = {
        item.get("id"): item.get("value")
        for item in settings
        if isinstance(item, dict) and item.get("id")
    }

    gamerscore = 0
    try:
        gamerscore = max(0, min(int(values.get("Gamerscore", 0) or 0), 2**63 - 1))
    except (TypeError, ValueError):
        pass

    gamertag = str(values.get("Gamertag") or xui_claim.get("gtg") or "").strip()
    xuid = str(profile_user.get("id") or xui_claim.get("xid") or "").strip()
    if xuid and not xuid.isdigit():
        xuid = ""
    if not gamertag:
        raise XboxIntegrationError("Xbox returned a profile without a gamertag")

    return {
        "gamertag": gamertag[:64],
        "gamerscore": gamerscore,
        "xuid": xuid[:32] or None,
        "account_tier": str(values.get("AccountTier") or "")[:64] or None,
    }
