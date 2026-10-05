"""Database models — the single source of truth for sync progress.

Progress is NEVER inferred from Google. A file's lifecycle lives entirely in
the `files` table, so connecting a new account adds a *destination* but never
resets or re-discovers already-recorded work.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Status constants -------------------------------------------------------
class FileStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SYNCED = "SYNCED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    FAILED = "FAILED"


class AccountStatus:
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


class SyncState:
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


# --- Models -----------------------------------------------------------------
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(320), default="")

    # Encrypted OAuth token bundle (access + refresh + expiry + scopes).
    enc_token: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default=AccountStatus.CONNECTED)

    # Router: lower priority number = preferred destination first.
    priority: Mapped[int] = mapped_column(Integer, default=100)
    # Whether the router may route uploads here.
    can_be_destination: Mapped[bool] = mapped_column(default=True)

    # Storage snapshot (bytes) refreshed from Google's quota endpoint.
    storage_limit: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_usage: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    @property
    def storage_free(self) -> int:
        return max(self.storage_limit - self.storage_usage, 0)

    @property
    def storage_fraction(self) -> float:
        if self.storage_limit <= 0:
            return 0.0
        return min(self.storage_usage / self.storage_limit, 1.0)


class File(Base):
    """One row per photo/file tracked. This IS the persistent, resumable queue."""

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("source_account_id", "source_file_id", name="uq_source_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Where it came from.
    source_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    source_file_id: Mapped[str] = mapped_column(String(512), index=True)

    file_name: Mapped[str] = mapped_column(String(1024), default="")
    mime_type: Mapped[str] = mapped_column(String(128), default="")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Strongest dedupe identifier when available (sha256 of bytes).
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)

    status: Mapped[str] = mapped_column(String(24), default=FileStatus.PENDING, index=True)

    # Where it went.
    destination_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL")
    )
    destination_file_id: Mapped[str | None] = mapped_column(String(512))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ai_note: Mapped[str | None] = mapped_column(String(512))

    # Operational.
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    # Transient Picker download URL (may expire; refreshed as needed).
    base_url: Mapped[str | None] = mapped_column(Text)
    # Deterministic queue ordering (resume = next PENDING by this, then id).
    queue_seq: Mapped[int] = mapped_column(Integer, index=True, default=0)

    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source_account = relationship("Account", foreign_keys=[source_account_id])
    destination_account = relationship("Account", foreign_keys=[destination_account_id])


class SyncControl(Base):
    """Singleton (id=1) holding the global run state and live cursor."""

    __tablename__ = "sync_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[str] = mapped_column(String(16), default=SyncState.IDLE)
    paused_reason: Mapped[str | None] = mapped_column(String(256))
    current_file_id: Mapped[int | None] = mapped_column(Integer)
    current_destination_account_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )
