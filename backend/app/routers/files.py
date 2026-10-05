"""Read-only access to tracked files."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import File
from ..schemas import FileOut, QueueOut

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("", response_model=QueueOut)
def list_files(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="filename contains"),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
) -> QueueOut:
    stmt = select(File)
    count_stmt = select(func.count()).select_from(File)
    if status:
        stmt = stmt.where(File.status == status)
        count_stmt = count_stmt.where(File.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(File.file_name.ilike(like))
        count_stmt = count_stmt.where(File.file_name.ilike(like))
    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(File.queue_seq.asc(), File.id.asc()).offset(offset).limit(limit)
    ).all()
    return QueueOut(items=[FileOut.model_validate(i) for i in items], total=total)


@router.get("/{file_id}", response_model=FileOut)
def get_file(file_id: int, db: Session = Depends(get_db)) -> FileOut:
    f = db.get(File, file_id)
    if not f:
        raise HTTPException(404, "File not found")
    return FileOut.model_validate(f)
