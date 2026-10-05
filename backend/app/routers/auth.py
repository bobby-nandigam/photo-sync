"""OAuth connect endpoints. Tokens are encrypted before storage and never
returned to the client.
"""
from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto, oauth
from ..account_ops import refresh_storage
from ..config import settings
from ..db import get_db
from ..logging_conf import get_logger
from ..models import Account, AccountStatus

log = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Short-lived CSRF/state store (state -> created_at). In-memory is fine for a
# single-process MVP; entries expire after 10 minutes.
_pending_states: dict[str, float] = {}
_STATE_TTL = 600


def _clean_states() -> None:
    now = time.time()
    for s, t in list(_pending_states.items()):
        if now - t > _STATE_TTL:
            _pending_states.pop(s, None)


@router.get("/google/connect")
def connect() -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(500, "Google OAuth is not configured. Set GOOGLE_CLIENT_ID/SECRET.")
    _clean_states()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time()
    return {"authorization_url": oauth.authorization_url(state), "state": state}


@router.get("/google/callback")
def callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        return RedirectResponse(f"{settings.frontend_url}/?error={error}")
    if not code or state not in _pending_states:
        return RedirectResponse(f"{settings.frontend_url}/?error=invalid_state")
    _pending_states.pop(state, None)

    bundle = oauth.exchange_code(code, state=state)
    email = oauth.fetch_email(bundle["access_token"])
    if not email:
        return RedirectResponse(f"{settings.frontend_url}/?error=no_email")

    account = db.scalar(select(Account).where(Account.email == email))
    if account is None:
        existing = len(db.scalars(select(Account.id)).all())
        account = Account(
            email=email,
            display_name=email.split("@")[0],
            enc_token=crypto.encrypt_dict(bundle),
            status=AccountStatus.CONNECTED,
            priority=existing * 10,
        )
        db.add(account)
    else:
        # Reconnect: keep existing refresh_token if Google omitted a new one.
        if not bundle.get("refresh_token"):
            old = crypto.decrypt_dict(account.enc_token)
            bundle["refresh_token"] = old.get("refresh_token")
        account.enc_token = crypto.encrypt_dict(bundle)
        account.status = AccountStatus.CONNECTED
    db.commit()
    db.refresh(account)

    # Populate storage snapshot right away so the dashboard shows limits.
    refresh_storage(db, account)
    log.info("Connected account %s", email)
    return RedirectResponse(f"{settings.frontend_url}/?connected={email}")
