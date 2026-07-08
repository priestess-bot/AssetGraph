# Reference Data CRUD Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add the first usable CRUD APIs for AssetGraph's digital-human livestream reference data: digital humans, voice profiles, and products.

**Architecture:** Keep the API thin: FastAPI routes depend on small repository objects. Repositories encapsulate PostgreSQL table access and business-code generation through `business_sequences`. Tests avoid a live database by overriding route dependencies with fakes, while repository SQL syntax is covered by migration parsing.

**Tech Stack:** FastAPI, Pydantic v2, psycopg v3, pytest, Starlette/FastAPI TestClient.

---

### Task 1: Add API route tests with dependency overrides

**Objective:** Prove the desired HTTP contract before implementation.

**Files:**
- Create: `backend/tests/test_reference_data_routes.py`
- Modify later: `backend/app/api/router.py`
- Modify later: `backend/app/api/routes/digital_humans.py`
- Modify later: `backend/app/api/routes/voice_profiles.py`
- Modify later: `backend/app/api/routes/products.py`

**Steps:**
1. Write failing tests for:
   - `POST /api/digital-humans`
   - `GET /api/digital-humans/{digital_human_code}`
   - `GET /api/digital-humans`
   - `PATCH /api/digital-humans/{digital_human_code}`
   - `DELETE /api/digital-humans/{digital_human_code}`
   - representative create routes for voice profiles and products.
2. Run `cd backend && .venv/Scripts/python.exe -m pytest tests/test_reference_data_routes.py -q`.
3. Expected RED: import errors or 404s because routes and dependencies do not exist yet.

### Task 2: Add Pydantic schemas

**Objective:** Define request and response models for digital humans, voice profiles, and products.

**Files:**
- Create: `backend/app/schemas/reference_data.py`

**Models:**
- `DigitalHumanCreate`, `DigitalHumanUpdate`, `DigitalHumanRead`
- `VoiceProfileCreate`, `VoiceProfileUpdate`, `VoiceProfileRead`
- `ProductCreate`, `ProductUpdate`, `ProductRead`

**Verification:**
Run route tests again. Expected RED moves from missing schemas to missing routes/repositories.

### Task 3: Add generic PostgreSQL reference repository

**Objective:** Implement reusable table CRUD and business code generation.

**Files:**
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/app/repositories/reference_data.py`

**Repository behavior:**
- `create(payload)` generates the proper code using `business_sequences` and inserts the row.
- `list(limit, offset)` excludes soft-deleted rows.
- `get_by_code(code)` returns one row or `None`.
- `update(code, payload)` updates allowed fields and returns updated row.
- `soft_delete(code)` sets `deleted_at = now()` and returns success.

**Verification:**
Run `cd backend && .venv/Scripts/python.exe -m compileall -q app`.

### Task 4: Add FastAPI routes

**Objective:** Expose real CRUD endpoints backed by the repository dependency.

**Files:**
- Create: `backend/app/api/routes/digital_humans.py`
- Create: `backend/app/api/routes/voice_profiles.py`
- Create: `backend/app/api/routes/products.py`
- Modify: `backend/app/api/router.py`

**Endpoints:**
- `POST /api/digital-humans`
- `GET /api/digital-humans`
- `GET /api/digital-humans/{digital_human_code}`
- `PATCH /api/digital-humans/{digital_human_code}`
- `DELETE /api/digital-humans/{digital_human_code}`
- equivalent endpoint sets for `/api/voice-profiles` and `/api/products`.

**Verification:**
Run route tests. Expected GREEN.

### Task 5: Add test dependencies and full verification

**Objective:** Make test tooling reproducible and run all checks.

**Files:**
- Modify: `backend/pyproject.toml`

**Steps:**
1. Add `httpx` to dev dependencies if TestClient requires it.
2. Reinstall editable dev deps via `uv pip install --python .venv/Scripts/python.exe -e '.[dev]'`.
3. Run:
   - `.venv/Scripts/python.exe -m pytest -q`
   - `.venv/Scripts/python.exe -m compileall -q app`
   - pglast parse check for migrations.

**Expected:** all tests pass, code compiles, SQL parses.
