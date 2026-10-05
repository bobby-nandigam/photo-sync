"""Smart destination router.

Given a file (with a known size), pick the destination account:
  1. must be CONNECTED and flagged as a destination
  2. must not be the file's own source account (we migrate OUT)
  3. must have room: free >= size + safety_buffer  (limit==0 => unlimited)
  4. prefer lower `priority`, then the account with the most free space

Returns (account | None, reason). None means "no account has room" -> caller
pauses the queue without losing position.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Account, AccountStatus, File


@dataclass
class RouteResult:
    account: Account | None
    reason: str


def _has_space(account: Account, size: int) -> bool:
    if account.storage_limit == 0:  # unlimited (e.g. Workspace)
        return True
    return account.storage_free >= size + settings.safety_buffer_bytes


def select_destination(db: Session, file: File) -> RouteResult:
    candidates = (
        db.scalars(
            select(Account)
            .where(
                Account.status == AccountStatus.CONNECTED,
                Account.can_be_destination.is_(True),
            )
        )
        .all()
    )
    # Exclude the source account; we don't copy a file back onto itself.
    candidates = [a for a in candidates if a.id != file.source_account_id]

    if not candidates:
        return RouteResult(None, "No connected destination accounts available.")

    # Preference: lowest priority number first, then most free space.
    candidates.sort(key=lambda a: (a.priority, -a.storage_free))

    for account in candidates:
        if _has_space(account, file.file_size):
            return RouteResult(account, f"Routed to {account.email}")

    return RouteResult(
        None,
        "All connected accounts are full (insufficient space for the next file).",
    )
