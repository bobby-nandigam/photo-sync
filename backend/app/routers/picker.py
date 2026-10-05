"""Google Photos Picker flow — the sanctioned way to read a user's existing
photos. The user opens `pickerUri`, selects photos, then we import the
selection into the persistent queue (deduped on source id).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import account_ops
from ..db import get_db
from ..google_client import GoogleAuthError
from ..logging_conf import get_logger
from ..models import Account, AccountStatus, File, FileStatus

log = get_logger(__name__)
router = APIRouter(prefix="/api/picker", tags=["picker"])


def _require_account(db: Session, account_id: int) -> Account:
    acc = db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    if acc.status != AccountStatus.CONNECTED:
        raise HTTPException(400, "Account is not connected")
    return acc


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/sessions")
def create_session(account_id: int, db: Session = Depends(get_db)) -> dict:
    acc = _require_account(db, account_id)
    try:
        client = account_ops.build_client(acc)
        session = client.create_picker_session()
        account_ops.persist_refreshed(db, acc, client)
    except GoogleAuthError as e:
        raise HTTPException(401, str(e)) from e
    polling = session.get("pollingConfig", {})
    return {
        "session_id": session.get("id"),
        "picker_uri": session.get("pickerUri"),
        "poll_interval_seconds": _poll_seconds(polling.get("pollInterval")),
        "media_items_set": session.get("mediaItemsSet", False),
    }


@router.get("/sessions/{session_id}")
def poll_session(session_id: str, account_id: int, db: Session = Depends(get_db)) -> dict:
    acc = _require_account(db, account_id)
    try:
        client = account_ops.build_client(acc)
        session = client.get_picker_session(session_id)
        account_ops.persist_refreshed(db, acc, client)
    except GoogleAuthError as e:
        raise HTTPException(401, str(e)) from e
    return {
        "session_id": session.get("id"),
        "media_items_set": session.get("mediaItemsSet", False),
    }


@router.post("/import")
def import_picked(account_id: int, session_id: str, db: Session = Depends(get_db)) -> dict:
    """Pull the user's picked items into the queue. Idempotent: items already
    tracked (same source id) are skipped, so re-importing never duplicates."""
    acc = _require_account(db, account_id)
    try:
        client = account_ops.build_client(acc)
        items = client.list_picked_items(session_id)
        account_ops.persist_refreshed(db, acc, client)
    except GoogleAuthError as e:
        raise HTTPException(401, str(e)) from e

    next_seq = (db.scalar(select(func.max(File.queue_seq))) or 0) + 1
    imported = 0
    skipped_existing = 0

    for item in items:
        source_file_id = item.get("id")
        if not source_file_id:
            continue
        exists = db.scalar(
            select(File.id).where(
                File.source_account_id == acc.id,
                File.source_file_id == source_file_id,
            )
        )
        if exists:
            skipped_existing += 1
            continue
        media_file = item.get("mediaFile", {})
        db.add(
            File(
                source_account_id=acc.id,
                source_file_id=source_file_id,
                file_name=media_file.get("filename", ""),
                mime_type=media_file.get("mimeType", ""),
                file_size=0,  # learned on download
                created_time=_parse_time(item.get("createTime")),
                base_url=media_file.get("baseUrl"),
                status=FileStatus.PENDING,
                queue_seq=next_seq,
            )
        )
        next_seq += 1
        imported += 1

    db.commit()
    # Free the picker session; we've captured what we need.
    try:
        account_ops.build_client(acc).delete_picker_session(session_id)
    except Exception:  # noqa: BLE001
        pass

    log.info("Picker import for %s: +%d new, %d already tracked", acc.email, imported, skipped_existing)
    return {
        "imported": imported,
        "already_tracked": skipped_existing,
        "total_selected": len(items),
    }


def _poll_seconds(value) -> float:  # noqa: ANN001
    """pollInterval comes as a protobuf duration string like '2.5s'."""
    if not value:
        return 2.0
    try:
        return float(str(value).rstrip("s"))
    except ValueError:
        return 2.0
