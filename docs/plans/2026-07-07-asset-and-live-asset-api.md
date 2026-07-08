# Asset Registration and Live Asset Link API Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the asset upload placeholder with real asset registration and add live-to-asset linking so a digital-human livestream can index recordings, clips, covers, transcripts, comments, and review documents.

**Architecture:** Add an asset repository backed by `assets` and `asset_sequences`. Extend the live-session repository to create and read `live_assets` links. Tests use dependency overrides with fakes so the API contract is fast and does not require a running PostgreSQL instance.

**Tech Stack:** FastAPI, Pydantic v2, psycopg v3, pytest, Starlette/FastAPI TestClient.

---

### Task 1: Add failing route tests

**Objective:** Define the desired API behavior before implementation.

**Files:**
- Create: `backend/tests/test_asset_and_live_asset_routes.py`

**Tests:**
- `POST /api/assets` creates an asset and returns `asset_code`.
- `GET /api/assets/{asset_code}` returns one asset.
- `POST /api/lives/{live_code}/assets` links a known asset to a known live session.
- `GET /api/lives/{live_code}/assets` returns the linked asset summary.
- linking to a missing live session returns 404.

### Task 2: Add asset schemas

**Objective:** Define asset create/read models and live-asset link create model.

**Files:**
- Create: `backend/app/schemas/assets.py`
- Extend: `backend/app/schemas/lives.py`

**Models:**
- `AssetCreate`
- `AssetRead`
- `LiveAssetLinkCreate`
- keep `LiveAssetSummary` and `LiveAssetsResponse`.

### Task 3: Add asset repository

**Objective:** Encapsulate asset code generation and asset table access.

**Files:**
- Create: `backend/app/repositories/assets.py`

**Behavior:**
- Generate `AG-{TYPE}-{YYYYMMDD}-{SEQ}` through `asset_sequences`.
- Insert `assets` record.
- Get by `asset_code` excluding deleted rows.

### Task 4: Replace asset route and extend live route

**Objective:** Expose real API endpoints.

**Files:**
- Modify: `backend/app/api/routes/assets.py`
- Modify: `backend/app/api/routes/lives.py`
- Modify: `backend/app/repositories/lives.py`

**Endpoints:**
- `POST /api/assets`
- `GET /api/assets/{asset_code}`
- `POST /api/lives/{live_code}/assets`
- existing `GET /api/lives/{live_code}/assets` returns real links.

### Task 5: Verify

Run:

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest -q
.venv/Scripts/python.exe -I -m compileall -q app
.venv/Scripts/python.exe -I - <<'PY'
from pathlib import Path
from pglast import parse_sql
for path in sorted(Path('migrations').glob('*.sql')):
    parse_sql(path.read_text(encoding='utf-8'))
    print(f'{path}: PostgreSQL parse OK')
PY
```

Expected: tests pass, app compiles, migrations parse.
