"""Pydantic response/request models. NOTE: tokens are never included here —
nothing token-related is ever serialized to the frontend.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    status: str
    priority: int
    can_be_destination: bool
    storage_limit: int
    storage_usage: int
    storage_free: int
    storage_fraction: float
    near_full: bool
    is_full: bool
    storage_checked_at: datetime | None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_account_id: int | None
    source_file_id: str
    file_name: str
    mime_type: str
    file_size: int
    created_time: datetime | None
    checksum: str | None
    status: str
    destination_account_id: int | None
    destination_file_id: str | None
    synced_at: datetime | None
    ai_note: str | None
    attempts: int
    last_error: str | None
    queue_seq: int


class SyncStatusOut(BaseModel):
    state: str
    paused_reason: str | None
    current_file: FileOut | None
    current_destination_account_id: int | None
    totals: dict
    accounts: list[AccountOut]


class QueueOut(BaseModel):
    items: list[FileOut]
    total: int


class MessageOut(BaseModel):
    ok: bool = True
    message: str = ""
