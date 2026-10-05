"""Account management: list, inspect storage, update routing prefs, disconnect."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..account_ops import refresh_storage
from ..config import settings
from ..db import get_db
from ..logging_conf import get_logger
from ..models import Account, AccountStatus
from ..schemas import AccountOut, MessageOut

log = get_logger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def serialize(acc: Account) -> AccountOut:
    limit_known = acc.storage_limit > 0
    return AccountOut(
        id=acc.id,
        email=acc.email,
        display_name=acc.display_name,
        status=acc.status,
        priority=acc.priority,
        can_be_destination=acc.can_be_destination,
        storage_limit=acc.storage_limit,
        storage_usage=acc.storage_usage,
        storage_free=acc.storage_free,
        storage_fraction=acc.storage_fraction,
        near_full=limit_known and acc.storage_fraction >= settings.near_full_threshold,
        is_full=limit_known and acc.storage_free <= settings.safety_buffer_bytes,
        storage_checked_at=acc.storage_checked_at,
    )


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[AccountOut]:
    accounts = db.scalars(select(Account).order_by(Account.priority, Account.id)).all()
    return [serialize(a) for a in accounts]


@router.post("/{account_id}/refresh", response_model=AccountOut)
def refresh_account(account_id: int, db: Session = Depends(get_db)) -> AccountOut:
    acc = db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    refresh_storage(db, acc)
    return serialize(acc)


class AccountPatch(BaseModel):
    priority: int | None = None
    can_be_destination: bool | None = None


@router.patch("/{account_id}", response_model=AccountOut)
def patch_account(account_id: int, patch: AccountPatch, db: Session = Depends(get_db)) -> AccountOut:
    acc = db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    if patch.priority is not None:
        acc.priority = patch.priority
    if patch.can_be_destination is not None:
        acc.can_be_destination = patch.can_be_destination
    db.commit()
    db.refresh(acc)
    return serialize(acc)


@router.delete("/{account_id}", response_model=MessageOut)
def disconnect(account_id: int, db: Session = Depends(get_db)) -> MessageOut:
    acc = db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    # Best-effort token revocation at Google.
    try:
        bundle = crypto.decrypt_dict(acc.enc_token)
        tok = bundle.get("refresh_token") or bundle.get("access_token")
        if tok:
            httpx.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": tok},
                headers={"Content-type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("Token revoke failed for %s: %s", acc.email, e)
    email = acc.email
    db.delete(acc)
    db.commit()
    return MessageOut(message=f"Disconnected {email}")
