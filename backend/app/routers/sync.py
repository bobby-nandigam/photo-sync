"""Sync control + status: start / pause / resume / status / queue / retry."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..logging_conf import get_logger
from ..models import Account, AccountStatus, File, FileStatus, SyncState
from ..schemas import FileOut, MessageOut, QueueOut, SyncStatusOut
from ..worker import get_control
from .accounts import serialize as serialize_account

log = get_logger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])


def _counts(db: Session) -> dict:
    rows = db.execute(select(File.status, func.count()).group_by(File.status)).all()
    by = {status: n for status, n in rows}
    total = sum(by.values())
    synced = by.get(FileStatus.SYNCED, 0)
    pending = by.get(FileStatus.PENDING, 0)
    processing = by.get(FileStatus.PROCESSING, 0)
    skipped = by.get(FileStatus.SKIPPED_DUPLICATE, 0)
    failed = by.get(FileStatus.FAILED, 0)
    done = synced + skipped
    remaining = pending + processing
    progress = round((done / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "synced": synced,
        "pending": pending,
        "processing": processing,
        "skipped_duplicate": skipped,
        "failed": failed,
        "remaining": remaining,
        "progress_pct": progress,
    }


def _connected_count(db: Session) -> int:
    return len(
        db.scalars(select(Account.id).where(Account.status == AccountStatus.CONNECTED)).all()
    )


@router.post("/start", response_model=MessageOut)
def start(db: Session = Depends(get_db)) -> MessageOut:
    if _connected_count(db) == 0:
        return MessageOut(ok=False, message="Connect at least one account first.")
    # Refresh quotas so routing starts from real numbers.
    from ..account_ops import refresh_storage

    for acc in db.scalars(select(Account).where(Account.status == AccountStatus.CONNECTED)).all():
        refresh_storage(db, acc)

    ctrl = get_control(db)
    ctrl.state = SyncState.RUNNING
    ctrl.paused_reason = None
    db.commit()
    return MessageOut(message="Sync started.")


@router.post("/pause", response_model=MessageOut)
def pause(db: Session = Depends(get_db)) -> MessageOut:
    ctrl = get_control(db)
    ctrl.state = SyncState.PAUSED
    ctrl.paused_reason = "Paused by user."
    db.commit()
    return MessageOut(message="Sync paused.")


@router.post("/resume", response_model=MessageOut)
def resume(db: Session = Depends(get_db)) -> MessageOut:
    from ..account_ops import refresh_storage

    for acc in db.scalars(select(Account).where(Account.status == AccountStatus.CONNECTED)).all():
        refresh_storage(db, acc)
    ctrl = get_control(db)
    ctrl.state = SyncState.RUNNING
    ctrl.paused_reason = None
    db.commit()
    return MessageOut(message="Sync resumed.")


@router.post("/retry-failed", response_model=MessageOut)
def retry_failed(db: Session = Depends(get_db)) -> MessageOut:
    failed = db.scalars(select(File).where(File.status == FileStatus.FAILED)).all()
    for f in failed:
        f.status = FileStatus.PENDING
        f.attempts = 0
        f.last_error = None
    db.commit()
    return MessageOut(message=f"Re-queued {len(failed)} failed file(s).")


@router.get("/status", response_model=SyncStatusOut)
def status(db: Session = Depends(get_db)) -> SyncStatusOut:
    ctrl = get_control(db)
    current = db.get(File, ctrl.current_file_id) if ctrl.current_file_id else None
    accounts = db.scalars(select(Account).order_by(Account.priority, Account.id)).all()
    return SyncStatusOut(
        state=ctrl.state,
        paused_reason=ctrl.paused_reason,
        current_file=FileOut.model_validate(current) if current else None,
        current_destination_account_id=ctrl.current_destination_account_id,
        totals=_counts(db),
        accounts=[serialize_account(a) for a in accounts],
    )


@router.get("/queue", response_model=QueueOut)
def queue(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
) -> QueueOut:
    stmt = select(File)
    count_stmt = select(func.count()).select_from(File)
    if status:
        stmt = stmt.where(File.status == status)
        count_stmt = count_stmt.where(File.status == status)
    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(File.queue_seq.asc(), File.id.asc()).offset(offset).limit(limit)
    ).all()
    return QueueOut(items=[FileOut.model_validate(i) for i in items], total=total)
