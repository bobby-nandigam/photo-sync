"""Google OAuth 2.0 flow (server-side authorization-code).

Minimal scopes only:
  - userinfo.email            : identify the connected account
  - drive.metadata.readonly   : read the account's storage quota (limit/usage)
  - photoslibrary.appendonly  : upload photos INTO a destination account
  - photoslibrary.readonly.appcreateddata : confirm our own uploads
  - photospicker.mediaitems.readonly      : read user-picked source photos

Refresh tokens are requested (access_type=offline, prompt=consent) so sync
can continue without the user re-logging in.
"""
from __future__ import annotations

from typing import Any

import httpx
from google_auth_oauthlib.flow import Flow

from .config import settings

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    "https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata",
    "https://www.googleapis.com/auth/photospicker.mediaitems.readonly",
]

_CLIENT_CONFIG = {
    "web": {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [settings.oauth_redirect_uri],
    }
}


def _flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(_CLIENT_CONFIG, scopes=SCOPES, state=state)
    flow.redirect_uri = settings.oauth_redirect_uri
    return flow


def authorization_url(state: str) -> str:
    flow = _flow(state=state)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(code: str, state: str | None = None) -> dict[str, Any]:
    """Exchange an auth code for tokens. Returns a serializable token bundle."""
    flow = _flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def fetch_email(access_token: str) -> str:
    resp = httpx.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("email", "")
