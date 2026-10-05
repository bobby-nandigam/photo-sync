"""Thin per-account Google client: token refresh + the REST calls we need.

Covers three Google surfaces:
  * Drive  about.get    -> storage quota (limit / usage) for monitoring
  * Photos Picker API   -> read user-selected SOURCE photos
  * Photos Library API  -> upload photos INTO a destination account

On refresh, the new token bundle is exposed via `.refreshed_bundle` so the
caller can persist it (re-encrypted) to the DB.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from .config import settings
from .logging_conf import get_logger

log = get_logger(__name__)

PICKER_BASE = "https://photospicker.googleapis.com/v1"
PHOTOS_BASE = "https://photoslibrary.googleapis.com/v1"
DRIVE_ABOUT = "https://www.googleapis.com/drive/v3/about"


class GoogleAuthError(Exception):
    """Raised when an account's tokens cannot be refreshed (needs reconnect)."""


class GoogleClient:
    def __init__(self, token_bundle: dict[str, Any]):
        expiry = None
        if token_bundle.get("expiry"):
            try:
                expiry = datetime.fromisoformat(token_bundle["expiry"])
                if expiry.tzinfo is not None:
                    expiry = expiry.replace(tzinfo=None)  # google-auth wants naive UTC
            except ValueError:
                expiry = None
        self._creds = Credentials(
            token=token_bundle.get("access_token"),
            refresh_token=token_bundle.get("refresh_token"),
            token_uri=token_bundle.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=token_bundle.get("scopes"),
            expiry=expiry,
        )
        self.refreshed_bundle: dict[str, Any] | None = None

    # -- auth ---------------------------------------------------------------
    def _token(self) -> str:
        if not self._creds.valid:
            if not self._creds.refresh_token:
                raise GoogleAuthError("No refresh token; account must reconnect.")
            try:
                self._creds.refresh(Request())
            except Exception as e:  # noqa: BLE001
                raise GoogleAuthError(f"Token refresh failed: {e}") from e
            self.refreshed_bundle = {
                "access_token": self._creds.token,
                "refresh_token": self._creds.refresh_token,
                "token_uri": self._creds.token_uri,
                "scopes": self._creds.scopes,
                "expiry": self._creds.expiry.isoformat() if self._creds.expiry else None,
            }
        return self._creds.token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    # -- storage monitoring -------------------------------------------------
    def storage_quota(self) -> dict[str, int]:
        """Returns {'limit': bytes, 'usage': bytes}. limit==0 means unlimited."""
        r = httpx.get(
            DRIVE_ABOUT,
            params={"fields": "storageQuota"},
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        q = r.json().get("storageQuota", {})
        return {
            "limit": int(q["limit"]) if q.get("limit") else 0,
            "usage": int(q.get("usage", 0)),
        }

    # -- source: Photos Picker ---------------------------------------------
    def create_picker_session(self) -> dict[str, Any]:
        r = httpx.post(f"{PICKER_BASE}/sessions", headers=self._headers(), json={}, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_picker_session(self, session_id: str) -> dict[str, Any]:
        r = httpx.get(f"{PICKER_BASE}/sessions/{session_id}", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def delete_picker_session(self, session_id: str) -> None:
        try:
            httpx.delete(f"{PICKER_BASE}/sessions/{session_id}", headers=self._headers(), timeout=30)
        except Exception:  # noqa: BLE001
            pass

    def list_picked_items(self, session_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"sessionId": session_id, "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            r = httpx.get(
                f"{PICKER_BASE}/mediaItems", params=params, headers=self._headers(), timeout=60
            )
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("mediaItems", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def download_picked(self, base_url: str) -> tuple[bytes, str]:
        """Download full bytes of a picked item. Returns (data, sha256hex)."""
        r = httpx.get(f"{base_url}=d", headers=self._headers(), timeout=300, follow_redirects=True)
        r.raise_for_status()
        data = r.content
        return data, hashlib.sha256(data).hexdigest()

    # -- destination: Photos Library upload --------------------------------
    def upload_bytes(self, data: bytes, mime_type: str, filename: str) -> str:
        r = httpx.post(
            f"{PHOTOS_BASE}/uploads",
            headers={
                **self._headers(),
                "Content-type": "application/octet-stream",
                "X-Goog-Upload-Content-Type": mime_type or "application/octet-stream",
                "X-Goog-Upload-Protocol": "raw",
                "X-Goog-Upload-File-Name": filename or "photo",
            },
            content=data,
            timeout=300,
        )
        r.raise_for_status()
        return r.text  # upload token

    def create_media_item(
        self, upload_token: str, filename: str, description: str | None = None
    ) -> str:
        body = {
            "newMediaItems": [
                {
                    "description": description or "",
                    "simpleMediaItem": {"fileName": filename or "photo", "uploadToken": upload_token},
                }
            ]
        }
        r = httpx.post(
            f"{PHOTOS_BASE}/mediaItems:batchCreate",
            headers={**self._headers(), "Content-type": "application/json"},
            json=body,
            timeout=120,
        )
        r.raise_for_status()
        results = r.json().get("newMediaItemResults", [])
        if not results:
            raise RuntimeError("batchCreate returned no results")
        result = results[0]
        status = result.get("status", {})
        # status.code 0 or absent with a mediaItem => success.
        if status.get("code", 0) not in (0, None):
            raise RuntimeError(f"Media item create failed: {status}")
        media_item = result.get("mediaItem")
        if not media_item or not media_item.get("id"):
            raise RuntimeError(f"Media item create returned no id: {result}")
        return media_item["id"]
