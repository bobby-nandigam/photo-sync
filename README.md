# Multi-Gmail Photo Sync Router

A resumable, storage-aware photo sync router across **1–3 Google accounts**. It
remembers exactly what has already been synced and **continues from where it
stopped** instead of restarting — so connecting a second or third account never
re-processes or duplicates the earlier work.

The **application database is the single source of truth** for progress. Sync
state is *never* inferred from Google.

---

## Contents

- [What it does](#what-it-does)
- [Important: the Google Photos reality](#important-the-google-photos-reality)
- [Architecture](#architecture)
- [How it satisfies each sync rule](#how-it-satisfies-each-sync-rule)
- [Prerequisites](#prerequisites)
- [1. Google Cloud setup](#1-google-cloud-setup)
- [2. Configure environment](#2-configure-environment)
- [3. Run locally (Docker)](#3-run-locally-docker)
- [4. Run locally (without Docker)](#4-run-locally-without-docker)
- [5. Deploy to Render](#5-deploy-to-render)
- [API reference](#api-reference)
- [Security](#security)
- [Deviations from the original spec](#deviations-from-the-original-spec)

---

## What it does

- Connect up to **3 Google accounts** via OAuth 2.0 (tokens encrypted at rest,
  never exposed to the frontend).
- For each account show **email, connection status, storage limit, used
  storage, free space, and a fill warning** when it gets near full.
- Pick photos to migrate from a source account (via the Google Photos Picker),
  and the app builds a **persistent, resumable queue**.
- A background worker uploads each photo to a destination account, choosing the
  account with room and **auto-switching** to the next account when one fills.
- **Duplicate detection** (content checksum + name/size/time) so the same photo
  is never uploaded twice — duplicates are marked `SKIPPED_DUPLICATE`.
- **Pause / resume**, **retry failed**, crash-safe resume, and a live dashboard.
- Optional one-line **AI notes** per photo (off by default, never blocks sync).

---

## Important: the Google Photos reality

Since **March 2025**, Google no longer lets any third-party app automatically
read a user's *existing* Google Photos library (the broad read scope was
removed). This is a Google policy limit, not a limit of this app. What Google
still allows, and what this app uses:

| Capability | Allowed? | How this app uses it |
|---|---|---|
| Upload photos **into** an account's library | ✅ | destination uploads (`photoslibrary.appendonly`) |
| Read photos **this app** uploaded | ✅ | confirm uploads |
| Read each account's **storage quota** | ✅ | the storage limit + fill warnings (`drive.metadata.readonly`) |
| Read a user's **existing** library automatically | ❌ | not possible — use the **Picker** |
| Let the user **pick** photos to share with the app | ✅ | source selection (`photospicker.mediaitems.readonly`) |

So the **source** side works by the user selecting photos in Google's Photos
**Picker** (opened from each account card). Everything downstream — the queue,
dedupe, routing, storage-aware switching, resume — is fully automatic.

> If you instead export a library via [Google Takeout](https://takeout.google.com)
> and want to ingest those files directly, the data model already supports it;
> add a small ingest endpoint that inserts `File` rows the same way the Picker
> import does.

---

## Architecture

```
                         ┌──────────────────────────────────────────┐
  React + TS + Tailwind  │  FastAPI backend (one service)            │
  (dashboard, polling) ──┤   /api/auth    OAuth connect              │
                         │   /api/accounts  storage + status         │
                         │   /api/picker    pick source photos       │
                         │   /api/sync      start/pause/resume/retry │
                         │                                           │
                         │   Background sync worker (daemon thread)  │
                         │     loop: next PENDING → route → upload   │
                         │           → confirm → mark SYNCED         │
                         └───────────────┬───────────────────────────┘
                                         │
                            SQLite (source of truth)
                          files · accounts · sync_control
                                         │
                      ┌──────────────────┼──────────────────┐
                   Account 1          Account 2          Account 3
                 (Google Photos)    (Google Photos)    (Google Photos)
```

- **Backend:** Python 3.12 · FastAPI · SQLAlchemy 2 · a daemon-thread worker.
- **Frontend:** React 18 · TypeScript · Tailwind · Vite.
- **State:** SQLite file by default (no server). Set `DATABASE_URL` to use
  Postgres instead — zero code changes.
- **Storage/API:** Google OAuth 2.0 · Photos Picker API · Photos Library API ·
  Drive `about.get` (quota only).

### The resume cursor

Every photo is one row in `files` with a `status`
(`PENDING → PROCESSING → SYNCED` / `SKIPPED_DUPLICATE` / `FAILED`) and a
`queue_seq`. The worker always picks the next `PENDING` row ordered by
`queue_seq, id`. There is **no `for file in all_files`** anywhere — "resume"
is simply "the next PENDING row," so it continues at 7,501, never at 1.
Connecting a new account only inserts a destination row; it never touches
existing progress.

---

## How it satisfies each sync rule

| Rule | Implementation |
|---|---|
| 1. Never restart a completed sync | Worker only ever selects `PENDING` rows. |
| 2. Never re-upload a `SYNCED` file | `SYNCED`/`SKIPPED` rows are never selected. |
| 3. Resume after a crash | On boot, `PROCESSING` rows reset to `PENDING`; a file is marked `SYNCED` **only after** the destination upload is confirmed. |
| 4. Account full → next account | `router.select_destination` skips accounts without room (free ≥ size + buffer) and picks the next by priority. |
| 5. Account disconnected → skip it | `_next_pending` skips files whose source account isn't `CONNECTED`; broken destinations are marked `ERROR`. |
| 6. All accounts full → pause | Router returns none → state becomes `PAUSED` with a reason, queue position kept. |
| 7. Duplicate → `SKIPPED_DUPLICATE` | `dedupe.find_synced_duplicate` matches by checksum, then name+size+time. |

---

## Prerequisites

- A Google account (or up to 3) with photos.
- [Docker](https://docs.docker.com/get-docker/) **or** Python 3.12 + Node 20.
- A Google Cloud project (free).

---

## 1. Google Cloud setup

1. **Create a project** → <https://console.cloud.google.com/projectcreate>
2. **Enable APIs** (click Enable on each):
   - Photos Library API → <https://console.cloud.google.com/apis/library/photoslibrary.googleapis.com>
   - Photos Picker API → <https://console.cloud.google.com/apis/library/photospicker.googleapis.com>
   - Google Drive API (quota reads) → <https://console.cloud.google.com/apis/library/drive.googleapis.com>
3. **OAuth consent screen** → <https://console.cloud.google.com/apis/credentials/consent>
   - User type: **External**.
   - Add scopes: `openid`, `userinfo.email`, `drive.metadata.readonly`,
     `photoslibrary.appendonly`, `photoslibrary.readonly.appcreateddata`,
     `photospicker.mediaitems.readonly`.
   - **Add every Gmail address you'll connect as a Test user** (an unverified
     app only works for listed test users — up to 100). Leave the app in
     **Testing**.
4. **Create credentials** → <https://console.cloud.google.com/apis/credentials>
   → **Create Credentials → OAuth client ID → Web application**.
   - **Authorized redirect URI** (must match exactly):
     - local: `http://localhost:8000/api/auth/google/callback`
     - Render: `https://<your-service>.onrender.com/api/auth/google/callback`
   - Copy the **Client ID** and **Client secret**.

> The Google APIs are free. You only pay if *you* choose to buy more Google
> storage, or if you enable the optional AI notes (OpenAI/Gemini).

---

## 2. Configure environment

```bash
cp .env.example .env
```

Fill in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and generate a key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste into FERNET_KEY
```

---

## 3. Run locally (Docker)

```bash
docker compose up --build
```

- Frontend: <http://localhost:5173>
- Backend:  <http://localhost:8000> (docs at `/docs`)

The SQLite sync state lives in the `sync_data` volume and survives restarts.

---

## 4. Run locally (without Docker)

**Backend**

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (new terminal)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The frontend proxies `/api` to `http://localhost:8000`.

---

## 5. Deploy to Render

1. Push this repo to GitHub.
2. Render → **New → Blueprint** → pick the repo. It reads `render.yaml` and
   builds the combined Docker image (frontend + backend in one service).
3. In the service's **Environment**, set `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `FERNET_KEY`, and after the first deploy set:
   - `OAUTH_REDIRECT_URI=https://<service>.onrender.com/api/auth/google/callback`
   - `FRONTEND_URL=https://<service>.onrender.com`
   - `CORS_ORIGINS=https://<service>.onrender.com`
4. Add that same redirect URI in the Google console (step 1.4).

> **Free-tier persistence note:** `render.yaml` uses the **free** plan, which has
> no persistent disk — the SQLite file resets on restart/redeploy. To keep sync
> state permanently *and* stay free, create a free Postgres at
> [neon.tech](https://neon.tech) (no credit card) and add its URL as
> `DATABASE_URL` (`postgresql+psycopg2://…?sslmode=require`) in the Render
> dashboard. The app picks it up automatically — no code changes.

---

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/auth/google/connect` | Begin OAuth; returns `authorization_url` |
| GET  | `/api/auth/google/callback` | OAuth redirect target |
| GET  | `/api/accounts` | List accounts + storage |
| POST | `/api/accounts/{id}/refresh` | Refresh one account's storage |
| PATCH| `/api/accounts/{id}` | Set `priority` / `can_be_destination` |
| DELETE | `/api/accounts/{id}` | Revoke tokens + disconnect |
| POST | `/api/picker/sessions?account_id=` | Start a Photos Picker session |
| GET  | `/api/picker/sessions/{id}?account_id=` | Poll selection status |
| POST | `/api/picker/import?account_id=&session_id=` | Import picked photos into the queue |
| POST | `/api/sync/start` · `/pause` · `/resume` | Control the worker |
| POST | `/api/sync/retry-failed` | Re-queue `FAILED` files |
| GET  | `/api/sync/status` | State, totals, current file, accounts |
| GET  | `/api/sync/queue` | Paginated queue (filter by `status`) |
| GET  | `/api/files` · `/api/files/{id}` | Browse tracked files |

---

## Security

- **OAuth 2.0 only — no Gmail passwords are ever handled or stored.**
- Tokens are **encrypted at rest** (Fernet / `FERNET_KEY`) and **never sent to
  the frontend**.
- **Minimal scopes** (append + quota + picker; no broad read).
- **Token refresh** is automatic; refreshed tokens are re-encrypted and saved.
- **Disconnect** revokes the token at Google and deletes it locally.
- Secrets come from environment variables; `.env` is gitignored.

---

## Deviations from the original spec

Small, deliberate changes — all to match your later constraints ("no new
database", keep it simple, host on Render) while keeping every core behavior:

- **No Celery/Redis.** Replaced by an in-process daemon-thread worker. It is
  fully crash-safe because the DB (not memory) holds every file's status. This
  keeps the deploy to a single free/cheap service with no Redis add-on.
- **SQLite instead of a Postgres server** by default (a file, not a server), per
  "don't use any new database." `DATABASE_URL` switches to Postgres with no code
  change.
- **Source = Photos Picker** (and optionally Takeout ingest) instead of an
  automatic library read, because Google disallows the latter (see above).
```
