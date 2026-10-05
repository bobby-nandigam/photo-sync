"""Helpers that bridge Account rows and the Google client: build a client from
stored (encrypted) tokens, persist refreshed tokens, and refresh the storage
snapshot used by the router and dashboard.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import crypto
from .google_client import GoogleAuthError, GoogleClient
from .logging_conf import get_logger
from .models import Account, AccountStatus, utcnow

log = get_logger(__name__)


def build_client(account: Account) -> GoogleClient:
    bundle = crypto.decrypt_dict(account.enc_token)
    return GoogleClient(bundle)


def persist_refreshed(db: Session, account: Account, client: GoogleClient) -> None:
    """If the client refreshed the access token, store the new bundle."""
    if client.refreshed_bundle:
        account.enc_token = crypto.encrypt_dict(client.refreshed_bundle)
        db.add(account)
        db.commit()


def refresh_storage(db: Session, account: Account) -> Account:
    """Update one account's storage snapshot. Marks ERROR if auth is broken."""
    try:
        client = build_client(account)
        quota = client.storage_quota()
        persist_refreshed(db, account, client)
        account.storage_limit = quota["limit"]
        account.storage_usage = quota["usage"]
        account.storage_checked_at = utcnow()
        if account.status == AccountStatus.ERROR:
            account.status = AccountStatus.CONNECTED
    except GoogleAuthError as e:
        log.warning("Account %s needs reconnect: %s", account.email, e)
        account.status = AccountStatus.ERROR
    except Exception as e:  # noqa: BLE001
        log.warning("Storage refresh failed for %s: %s", account.email, e)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account
