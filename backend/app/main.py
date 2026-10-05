"""FastAPI application entrypoint.

Starts the API, initializes the SQLite (or Postgres) schema, performs crash
recovery, and launches the in-process background sync worker. Optionally serves
the built React frontend so the whole thing runs as ONE Render service.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .logging_conf import configure_logging, get_logger
from .routers import accounts, auth, files, picker, sync
from .worker import recover_on_startup, worker

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    recover_on_startup()
    worker.start()
    log.info("Backend ready.")
    yield
    worker.stop()


app = FastAPI(title="Multi-Gmail Photo Sync Router", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(sync.router)
app.include_router(files.router)
app.include_router(picker.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --- Serve the built frontend (single-service deploy) ----------------------
# FRONTEND_DIST env wins (used by the combined Docker image on Render);
# otherwise fall back to ../../frontend/dist for a local `npm run build`.
_FRONTEND_DIST = Path(
    os.getenv("FRONTEND_DIST")
    or (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist")
)
if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):  # noqa: ANN201
        # Let the API 404s stand; everything else serves the SPA shell.
        if full_path.startswith("api/"):
            return FileResponse(_FRONTEND_DIST / "index.html", status_code=404)
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
