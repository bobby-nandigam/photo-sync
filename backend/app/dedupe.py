"""Duplicate detection.

Strongest signal is the content checksum (sha256 of the downloaded bytes).
When a checksum isn't known yet we fall back to (file_name, file_size,
created_time). The source (account_id, source_file_id) pair is already unique
at ingest time, so re-ingesting the same library never creates a second row.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import File, FileStatus


def find_synced_duplicate(db: Session, file: File) -> File | None:
    """Return an already-SYNCED file that is the same content as `file`, or None.

    Used right before upload so we never upload the same photo twice across any
    connected account.
    """
    # 1) Strongest: identical content checksum already synced.
    if file.checksum:
        dup = db.scalar(
            select(File)
            .where(
                File.id != file.id,
                File.checksum == file.checksum,
                File.status == FileStatus.SYNCED,
            )
            .limit(1)
        )
        if dup:
            return dup

    # 2) Fallback heuristic: same name + size + original timestamp.
    if file.file_name and file.file_size:
        dup = db.scalar(
            select(File)
            .where(
                File.id != file.id,
                File.file_name == file.file_name,
                File.file_size == file.file_size,
                File.created_time == file.created_time,
                File.status == FileStatus.SYNCED,
            )
            .limit(1)
        )
        if dup:
            return dup

    return None
