"""Background sync worker — the resumable, crash-safe engine.

It is a single daemon thread. The DATABASE is the source of truth; the worker
holds no progress in memory. It implements the loop from the spec:

    load_sync_state()
    while files_remaining:
        file = get_next_unsynced_file()      # resume point, never restarts at #1
        destination = router.select_account(file)
        if destination.has_space(file):
            upload(file); mark_as_synced(file)
        else:
            move_to_next_account()           # or pause if none

Guarantees:
  * A file is marked SYNCED only AFTER the destination upload is confirmed.
  * On startup, any PROCESSING row (an interrupted upload) is reset to PENDING.
  * Duplicates are marked SKIPPED_DUPLICATE, never re-uploaded.
  * When every account is full it PAUSES without losing queue position.
  * A disconnected/errored source account's files are skipped, not failed.
"""
from __future__ import annotations

import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import account_ops, ai_notes
from .config import settings
from .db import SessionLocal
from .dedupe import find_synced_duplicate
from .google_client import GoogleAuthError
from .logging_conf import get_logger
from .models import Account, AccountStatus, File, FileStatus, SyncControl, SyncState, utcnow
from .router import select_destination

log = get_logger(__name__)


def get_control(db: Session) -> SyncControl:
    ctrl = db.get(SyncControl, 1)
    if ctrl is None:
        ctrl = SyncControl(id=1, state=SyncState.IDLE)
        db.add(ctrl)
        db.commit()
        db.refresh(ctrl)
    return ctrl


def recover_on_startup() -> None:
    """Reset interrupted work so a crash resumes cleanly (Rule 3)."""
    with SessionLocal() as db:
        stuck = db.scalars(select(File).where(File.status == FileStatus.PROCESSING)).all()
        for f in stuck:
            f.status = FileStatus.PENDING
        ctrl = get_control(db)
        ctrl.current_file_id = None
        ctrl.current_destination_account_id = None
        if ctrl.state == SyncState.RUNNING:
            # Was running when it died; leave it RUNNING so it auto-resumes.
            pass
        db.commit()
        if stuck:
            log.info("Recovered %d interrupted file(s) back to PENDING.", len(stuck))


def _next_pending(db: Session) -> File | None:
    """Next file to process. Skips files whose source account is not CONNECTED
    (Rule 5). Deterministic order => resumes exactly where it stopped."""
    stmt = (
        select(File)
        .outerjoin(Account, File.source_account_id == Account.id)
        .where(
            File.status == FileStatus.PENDING,
            (File.source_account_id.is_(None)) | (Account.status == AccountStatus.CONNECTED),
        )
        .order_by(File.queue_seq.asc(), File.id.asc())
        .limit(1)
    )
    return db.scalar(stmt)


class SyncWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sync-worker", daemon=True)
        self._thread.start()
        log.info("Sync worker started.")

    def stop(self) -> None:
        self._stop.set()

    # -- main loop ----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                log.exception("Worker tick error: %s", e)
            time.sleep(settings.worker_poll_seconds)

    def _tick(self) -> None:
        with SessionLocal() as db:
            ctrl = get_control(db)
            if ctrl.state != SyncState.RUNNING:
                return

            file = _next_pending(db)
            if file is None:
                # Nothing left to do -> go idle.
                ctrl.state = SyncState.IDLE
                ctrl.current_file_id = None
                ctrl.paused_reason = None
                db.commit()
                return

            self._process(db, ctrl, file)

    # -- per-file -----------------------------------------------------------
    def _process(self, db: Session, ctrl: SyncControl, file: File) -> None:
        file.status = FileStatus.PROCESSING
        ctrl.current_file_id = file.id
        db.commit()

        source = db.get(Account, file.source_account_id) if file.source_account_id else None
        if source is None or source.status != AccountStatus.CONNECTED:
            # Source unusable -> leave PENDING, it'll be skipped next time.
            file.status = FileStatus.PENDING
            ctrl.current_file_id = None
            db.commit()
            return

        try:
            src_client = account_ops.build_client(source)
            if not file.base_url:
                raise RuntimeError("Missing picker download URL; re-pick this item.")
            data, checksum = src_client.download_picked(file.base_url)
            account_ops.persist_refreshed(db, source, src_client)

            file.checksum = checksum
            file.file_size = len(data)
            db.commit()

            # Duplicate across any connected account -> skip (Rule 7).
            dup = find_synced_duplicate(db, file)
            if dup:
                file.status = FileStatus.SKIPPED_DUPLICATE
                file.last_error = None
                ctrl.current_file_id = None
                db.commit()
                log.info("SKIPPED_DUPLICATE %s (matches file #%d)", file.file_name, dup.id)
                return

            # Route to a destination with room.
            route = select_destination(db, file)
            if route.account is None:
                # Refresh real quotas once before giving up (space may have changed).
                self._refresh_all_storage(db)
                route = select_destination(db, file)

            if route.account is None:
                # All full -> pause, keep position (Rule 6).
                file.status = FileStatus.PENDING
                ctrl.state = SyncState.PAUSED
                ctrl.paused_reason = route.reason
                ctrl.current_file_id = None
                db.commit()
                log.warning("PAUSED: %s", route.reason)
                return

            dest = route.account
            ctrl.current_destination_account_id = dest.id
            db.commit()

            dst_client = account_ops.build_client(dest)
            token = dst_client.upload_bytes(data, file.mime_type, file.file_name)
            media_id = dst_client.create_media_item(token, file.file_name)
            account_ops.persist_refreshed(db, dest, dst_client)

            # Confirmed uploaded -> NOW mark synced (Rule 2/3).
            file.destination_account_id = dest.id
            file.destination_file_id = media_id
            file.status = FileStatus.SYNCED
            file.synced_at = utcnow()
            file.last_error = None
            dest.storage_usage += file.file_size  # keep router accurate between refreshes
            ctrl.current_file_id = None
            ctrl.current_destination_account_id = None
            db.commit()
            log.info("SYNCED %s -> %s", file.file_name, dest.email)

            # Optional AI note, after sync, never blocks/fails the sync.
            if settings.ai_notes_enabled:
                note = ai_notes.generate_note(data, file.mime_type)
                if note:
                    file.ai_note = note
                    db.commit()

        except GoogleAuthError as e:
            # Auth broke on source or destination -> mark the broken account and
            # leave the file PENDING to retry later (Rule 5).
            log.warning("Auth error on %s: %s", file.file_name, e)
            file.status = FileStatus.PENDING
            db.commit()
        except Exception as e:  # noqa: BLE001
            file.attempts += 1
            file.last_error = str(e)[:1000]
            if file.attempts >= settings.max_upload_attempts:
                file.status = FileStatus.FAILED
                log.error("FAILED %s after %d attempts: %s", file.file_name, file.attempts, e)
            else:
                file.status = FileStatus.PENDING
                log.warning("Retry %s (attempt %d): %s", file.file_name, file.attempts, e)
            ctrl.current_file_id = None
            db.commit()

    def _refresh_all_storage(self, db: Session) -> None:
        accounts = db.scalars(
            select(Account).where(Account.status == AccountStatus.CONNECTED)
        ).all()
        for acc in accounts:
            account_ops.refresh_storage(db, acc)


worker = SyncWorker()
