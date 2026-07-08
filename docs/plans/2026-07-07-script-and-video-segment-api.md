# Script and Video Segment API Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add the first digital-human livestream business APIs: scripts with script blocks, and video segments linked to live sessions, assets, products, digital humans, voices, and script blocks.

**Architecture:** Keep script and segment routes thin and backed by dedicated repositories. Reuse the existing business-code generator and `business_sequences`. Route tests use dependency overrides with fakes so the API contract stays fast and independent from a running PostgreSQL instance.

**Tech Stack:** FastAPI, Pydantic v2, psycopg v3, pytest, Starlette/FastAPI TestClient.

---

### Task 1: Add failing route tests

**Objective:** Define the desired API behavior before implementation.

**Files:**
- Create: `backend/tests/test_script_and_segment_routes.py`

**Tests:**
- `POST /api/scripts` creates a script and nested script blocks.
- `GET /api/scripts/{script_code}` returns script with blocks.
- `GET /api/scripts` lists scripts.
- `POST /api/video-segments` creates a segment with `live_code`, start/end seconds, transcript, product/digital-human/voice/script-block references.
- `GET /api/video-segments?live_code=...` lists segments for one live session.
- `GET /api/video-segments/{segment_code}` returns one segment.

**Verification:**
Run `cd backend && .venv/Scripts/python.exe -I -m pytest tests/test_script_and_segment_routes.py -q`.
Expected RED: imports or route registration fail because schemas/routes do not exist yet.

### Task 2: Add Pydantic schemas

**Objective:** Define request/response contracts.

**Files:**
- Create: `backend/app/schemas/scripts.py`
- Create: `backend/app/schemas/video_segments.py`

**Models:**
- `ScriptBlockCreate`, `ScriptBlockRead`
- `ScriptCreate`, `ScriptRead`
- `VideoSegmentCreate`, `VideoSegmentRead`

### Task 3: Add repositories

**Objective:** Encapsulate database writes and reads.

**Files:**
- Create: `backend/app/repositories/scripts.py`
- Create: `backend/app/repositories/video_segments.py`

**Behavior:**
- Script repository generates `AG-SCRIPT-*`, inserts `scripts`, inserts nested `script_blocks`, and returns the full row with blocks.
- Segment repository generates `AG-SEG-*`, inserts `video_segments`, supports list by `live_code`, and get by `segment_code`.

### Task 4: Add routes and register them

**Objective:** Expose APIs.

**Files:**
- Create: `backend/app/api/routes/scripts.py`
- Create: `backend/app/api/routes/video_segments.py`
- Modify: `backend/app/api/router.py`

**Endpoints:**
- `POST /api/scripts`
- `GET /api/scripts`
- `GET /api/scripts/{script_code}`
- `POST /api/video-segments`
- `GET /api/video-segments`
- `GET /api/video-segments/{segment_code}`

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
