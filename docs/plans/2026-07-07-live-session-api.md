# Live Session Real API Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the placeholder live session API with real database-backed APIs that generate `AG-LIVE-*` codes and link live sessions to digital humans, voices, and scripts.

**Architecture:** Add dedicated live-session schemas and a repository. The repository owns `live_sequences` based code generation and `live_sessions` CRUD reads. The FastAPI route keeps the existing `/api/lives` path but switches from placeholder responses to repository-backed responses. Tests use dependency overrides with a fake repository.

**Tech Stack:** FastAPI, Pydantic v2, psycopg v3, pytest, Starlette/FastAPI TestClient.

---

### Task 1: Add failing API tests

**Objective:** Define the live-session API contract before implementation.

**Files:**
- Create: `backend/tests/test_live_session_routes.py`

**Tests:**
- `POST /api/lives` creates a live session with title, platform, streamer, digital_human_id, voice_profile_id, script_id.
- `GET /api/lives` lists live sessions.
- `GET /api/lives/{live_code}` returns one live session.
- `GET /api/lives/{live_code}/assets` preserves the existing asset index endpoint shape.
- `GET /api/lives/{missing}` returns 404.

### Task 2: Add schema models

**Objective:** Define request and response shapes.

**Files:**
- Create: `backend/app/schemas/lives.py`
- Keep `backend/app/schemas/asset.py` compatibility if needed.

**Models:**
- `LiveSessionCreate`
- `LiveSessionRead`
- `LiveAssetSummary`
- `LiveAssetsResponse`

### Task 3: Add repository

**Objective:** Encapsulate database logic.

**Files:**
- Create: `backend/app/repositories/lives.py`

**Behavior:**
- Generate `AG-LIVE-{YYYYMMDD}-{SEQ}` via `live_sequences`.
- Insert `live_sessions` with optional digital-human/voice/script references.
- List non-deleted sessions.
- Get by `live_code`.
- List live asset summaries from `live_assets`.

### Task 4: Replace route implementation

**Objective:** Turn placeholder route into real API.

**Files:**
- Modify: `backend/app/api/routes/lives.py`

**Endpoints:**
- `POST /api/lives`
- `GET /api/lives`
- `GET /api/lives/{live_code}`
- `GET /api/lives/{live_code}/assets`

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
