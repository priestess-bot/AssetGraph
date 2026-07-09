# 真实素材入库 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将 `D:/AssetGraph/素材` 中已扫描出的 131 个真实麦兔素材，从 inventory 安全、可重跑地导入 AssetGraph：写入 PostgreSQL `assets` / `asset_files` / `tags`，上传原始文件到 MinIO，并为后续 Milvus 向量检索与 Qwen3 rerank 打基础。

**Architecture:** 采用 API-first 入库链路：`scripts/scan_assets.py` 继续只读生成 inventory；新增 importer 通过 AssetGraph 后端 API 写入数据库和上传文件，不直接绕过后端写库。入库分为 metadata、file storage、tags、embedding 四层，每层都有 dry-run、limit、小批量验证和幂等重跑保护。

**Tech Stack:** FastAPI, PostgreSQL/psycopg, MinIO, Qwen3 shared retrieval service (`D:/AI-Models/qwen3-service`), Milvus/pymilvus, pytest, existing `scripts/scan_assets.py` inventory.

---

## Current Context

### 已具备

- 本地真实素材目录：`D:/AssetGraph/素材`
- 当前 inventory：`docs/asset-numbering/asset_inventory_20260709.json`
- 扫描摘要：
  - 素材文件数：131
  - 解析异常数：0
  - 重复素材组：8
  - 重复素材文件数：20
  - AUD: 4, IMG: 71, VID: 56
  - `background_image`: 5
  - `digital_human_video`: 68
  - `floating_sticker`: 26
  - `product_video`: 28
  - `voice_audio`: 4
- 每条 inventory asset 已带 `asset_create_payload`，可作为 `POST /api/assets` 基础。
- 后端已有：
  - `POST /api/assets`
  - `GET /api/assets`
  - `GET /api/assets/{asset_code}`
  - `AssetRepository.create()` 自动生成全局 `AG-*` 编号
  - 本地编号字段：`display_code` / `local_file_code` / `entity_code`
- Qwen3 已接入：
  - `GET /api/rag/qwen3/health`
  - `POST /api/rag/embeddings`
  - `POST /api/rag/rerank`
  - 默认服务：`http://127.0.0.1:8010`

### 仍需补齐

- 真实批量 importer：`scripts/import_assets.py`
- 幂等保护：按 `source_system + local_file_code` 避免重复生成 `AG-*`
- MinIO 上传：原始文件进入对象存储
- `asset_files` 写入：记录 bucket/object key/checksum/size/mime
- tags 入库：inventory 的 tags 进入 `tags` / `asset_tags`
- embedding 入库：素材检索文本 -> Qwen3 embedding -> Milvus
- 真实基础设施验证：Docker/PostgreSQL/MinIO/Milvus 当前可能未启动，实施时必须先检查

---

## Non-goals for First Pass

第一轮不要做这些，避免范围失控：

- 不做视频抽帧、ASR、OCR、转码。
- 不做 Neo4j 图谱写入。
- 不让 Browser-use 操作麦兔。
- 不直接全量写入 131 条；必须先 dry-run 和 limit 小批量。
- 不把重复文件物理去重为单个 asset；第一轮导入全部 131 条，保留 duplicate metadata，保证每个 `MT-*` / `DH-*` 本地编号都可被 Agent 和 Browser-use 精确引用。

---

## Acceptance Criteria

完成后必须满足：

1. `python scripts/scan_assets.py --assets-root 素材 --expected-count 131 --quiet` 通过。
2. `python scripts/import_assets.py --inventory docs/asset-numbering/asset_inventory_20260709.json --dry-run --expected-count 131` 输出 131 条 planned、0 条 invalid。
3. 小批量真实导入：`--limit 5 --upload-files --write-tags` 成功创建 5 条 `assets`、5 条 `asset_files`，并上传 5 个 MinIO object。
4. 重新运行同一小批量 import，默认 `--skip-existing`，创建数为 0，不生成新的 `AG-*`。
5. 可以用以下 API 查到导入素材：
   - `GET /api/assets?local_file_code=MT-VID-0024`
   - `GET /api/assets?q=品酒大师`
   - `GET /api/assets?maitu_category=product_video`
6. 全量 metadata + file + tags 导入后：
   - created/skipped/failed 报告写入 `docs/asset-numbering/import_report_YYYYMMDD.json`
   - 131 个本地素材编号都有 AssetGraph 记录或明确 skipped reason
   - 解析异常为 0
7. Embedding 阶段完成后：
   - 每个导入 asset 有 1024 维文本 embedding 写入 Milvus collection
   - 测试查询“品酒大师 商品讲解视频”能召回相关素材
   - Qwen3 rerank 能把相关素材排在不相关素材前面
8. 所有后端测试通过：`.venv/Scripts/python.exe -I -m pytest -q`
9. Worker 测试仍通过：`uv run --extra dev python -I -m pytest -q` in `workers/browser-use`

---

## Target Runtime Commands

### Infrastructure

```bash
cd D:/AssetGraph

docker compose -f infra/docker-compose.yml up -d postgres minio milvus etcd

docker compose -f infra/docker-compose.yml ps
```

### Qwen3 service

```bash
cd /d/AI-Models/qwen3-service
./start_qwen3_service.sh
curl http://127.0.0.1:8010/health
```

### Backend

```bash
cd D:/AssetGraph/backend
.venv/Scripts/python.exe -I -m uvicorn app.main:app --reload
```

### Inventory validation

```bash
cd D:/AssetGraph
python scripts/scan_assets.py --assets-root 素材 --expected-count 131 --quiet
```

---

## Implementation Tasks

### Task 1: Add ingestion hardening migration

**Objective:** Add database constraints/columns needed for idempotent file-backed import.

**Files:**
- Create: `backend/migrations/007_asset_ingestion_hardening.sql`
- Test: `backend/tests/test_migrations_parse.py` if exists; otherwise extend the existing migration parse test or add one.

**Step 1: Write failing SQL parse test**

If no migration parse test exists, create:

```python
from pathlib import Path

from pglast import parse_sql


def test_all_migrations_parse_as_postgresql() -> None:
    for path in sorted(Path('migrations').glob('*.sql')):
        parse_sql(path.read_text(encoding='utf-8'))
```

Run:

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest tests/test_migrations_parse.py -q
```

Expected before adding dependency/test wiring: FAIL if the test file is missing or migration does not exist yet.

**Step 2: Add migration**

Migration should include:

```sql
-- Idempotent local material import protection
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_source_local_code_active
ON assets(source_system, local_file_code)
WHERE local_file_code IS NOT NULL AND deleted_at IS NULL;

ALTER TABLE asset_files
    ADD COLUMN IF NOT EXISTS source_relative_path TEXT,
    ADD COLUMN IF NOT EXISTS local_file_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS storage_status VARCHAR(32) NOT NULL DEFAULT 'stored';

CREATE INDEX IF NOT EXISTS idx_asset_files_local_file_code ON asset_files(local_file_code);
CREATE INDEX IF NOT EXISTS idx_asset_files_object_key ON asset_files(object_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_files_asset_role_unique
ON asset_files(asset_id, file_role);
```

**Step 3: Verify**

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest tests/test_migrations_parse.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/migrations/007_asset_ingestion_hardening.sql backend/tests/test_migrations_parse.py
git commit -m "db: harden asset ingestion schema"
```

---

### Task 2: Add MinIO configuration and storage service protocol

**Objective:** Let backend upload files to MinIO through an injectable service, while tests use a fake storage service.

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/object_storage.py`
- Test: `backend/tests/test_object_storage.py`

**Step 1: Write failing tests**

Test the object key builder and fake upload shape:

```python
from pathlib import Path

from app.services.object_storage import build_asset_object_key


def test_build_asset_object_key_is_stable_and_namespaced() -> None:
    key = build_asset_object_key(
        asset_code='AG-VID-20260709-000001',
        filename='MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4',
    )

    assert key == 'assets/AG-VID-20260709-000001/original/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4'
```

Run:

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest tests/test_object_storage.py -q
```

Expected: FAIL because service does not exist.

**Step 2: Implement minimal service**

Add config fields:

```python
minio_endpoint: str = 'localhost:9000'
minio_access_key: str = 'assetgraph'
minio_secret_key: str = 'assetgraph-secret'
minio_bucket: str = 'assetgraph'
minio_secure: bool = False
```

Add dependency:

```toml
"minio>=7.2.0",
"python-multipart>=0.0.9",
```

Create `object_storage.py` with:

```python
def build_asset_object_key(*, asset_code: str, filename: str, file_role: str = 'original') -> str:
    safe_name = filename.replace('\\', '_').replace('/', '_')
    return f'assets/{asset_code}/{file_role}/{safe_name}'
```

Define protocol:

```python
class ObjectStorage(Protocol):
    def upload_file(self, *, bucket_name: str, object_key: str, path: Path, content_type: str | None) -> None: ...
```

Add `MinioObjectStorage` implementation, but keep it thin.

**Step 3: Verify**

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest tests/test_object_storage.py -q
.venv/Scripts/python.exe -I -m pytest -q
```

---

### Task 3: Add asset file repository methods

**Objective:** Backend can persist `asset_files` rows and update asset status after file storage.

**Files:**
- Modify: `backend/app/repositories/assets.py`
- Test: `backend/tests/test_asset_repository_files.py` or extend `test_asset_and_live_asset_routes.py` fake repository tests.

**Required repository methods:**

```python
def get_by_local_file_code(self, source_system: str, local_file_code: str) -> dict[str, Any] | None: ...

def create_file_record(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any] | None: ...

def list_file_records(self, asset_code: str) -> list[dict[str, Any]]: ...

def update_status(self, asset_code: str, status: str) -> dict[str, Any] | None: ...
```

**Step 1: Write failing route/repository tests**

Prefer contract tests against fake repository first:

- `get_by_local_file_code('maitu', 'MT-VID-0024')` returns existing asset.
- `create_file_record()` stores bucket/object key/checksum/local code.
- duplicate `asset_id + file_role` raises or returns existing depending chosen behavior.

**Step 2: Implement SQL**

Use `SELECT id FROM assets WHERE asset_code = %s AND deleted_at IS NULL` before inserting `asset_files`.

**Step 3: Verify**

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest tests/test_asset_and_live_asset_routes.py -q
.venv/Scripts/python.exe -I -m pytest -q
```

---

### Task 4: Add file upload/list API for assets

**Objective:** Importer can upload a real local file through backend API and receive an `asset_files` row.

**Files:**
- Modify: `backend/app/api/routes/assets.py`
- Modify: `backend/app/schemas/assets.py`
- Test: `backend/tests/test_asset_file_routes.py`

**API:**

```http
POST /api/assets/{asset_code}/files
GET  /api/assets/{asset_code}/files
```

**Multipart fields:**

- `file`: uploaded file
- `file_role`: default `original`
- `local_file_code`: optional
- `source_relative_path`: optional
- `checksum_sha256`: optional, must match if provided

**Step 1: Write failing test**

Use `TestClient` with fake repository and fake storage. Verify:

```python
response = client.post(
    '/api/assets/AG-VID-20260709-000001/files',
    files={'file': ('demo.mp4', b'video bytes', 'video/mp4')},
    data={'file_role': 'original', 'local_file_code': 'MT-VID-0024'},
)
assert response.status_code == 201
assert response.json()['object_key'] == 'assets/AG-VID-20260709-000001/original/demo.mp4'
```

**Step 2: Implement endpoint**

Endpoint flow:

```text
validate asset exists
write upload to temp file
verify sha256 if client provided checksum
storage.upload_file(bucket, object_key, temp_path, content_type)
repository.create_file_record(...)
repository.update_status(asset_code, 'stored')
return AssetFileRead
```

**Step 3: Verify**

```bash
cd backend
.venv/Scripts/python.exe -I -m pytest tests/test_asset_file_routes.py -q
.venv/Scripts/python.exe -I -m pytest -q
```

---

### Task 5: Add tags support during asset creation

**Objective:** Preserve inventory tags as first-class searchable tags instead of burying them in description.

**Files:**
- Modify: `backend/app/schemas/assets.py`
- Modify: `backend/app/repositories/assets.py`
- Test: `backend/tests/test_asset_tags.py`

**Schema addition:**

```python
class AssetCreate(BaseModel):
    tags: list[str] | None = None
```

`AssetRead` may include `tags: list[str] = []` if easy; otherwise file a follow-up and ensure repository writes tags.

**Repository behavior:**

Within the same transaction as asset create:

```text
INSERT INTO tags(name, tag_type='imported') ON CONFLICT DO NOTHING
INSERT INTO asset_tags(asset_id, tag_id, source='inventory') ON CONFLICT DO NOTHING
```

**Tests:**

- Create asset with `tags=['品酒大师', 'PRO']`.
- Verify tag rows and asset_tags rows are inserted.
- Verify duplicate tags do not duplicate rows.

---

### Task 6: Add importer dry-run validator

**Objective:** `scripts/import_assets.py` can validate inventory and show planned operations without touching backend.

**Files:**
- Create: `scripts/import_assets.py`
- Test: `backend/tests/test_import_assets_script.py`

**CLI shape:**

```bash
python scripts/import_assets.py \
  --inventory docs/asset-numbering/asset_inventory_20260709.json \
  --assets-root 素材 \
  --api-base-url http://127.0.0.1:8000 \
  --dry-run \
  --expected-count 131 \
  --report-output docs/asset-numbering/import_report_20260709_dry_run.json
```

**Required options:**

- `--inventory`
- `--assets-root`
- `--api-base-url`
- `--dry-run`
- `--limit N`
- `--local-file-code CODE` repeatable filter
- `--expected-count N`
- `--skip-existing` default true
- `--upload-files` default false
- `--write-tags` default true
- `--write-embeddings` default false
- `--report-output PATH`

**Dry-run validation:**

For each item:

- inventory has `asset_create_payload`
- `local_relative_path` exists under `--assets-root`
- file size matches inventory
- sha256 matches inventory, unless `--trust-inventory-checksum` is explicitly added later
- required payload fields exist: `asset_type`, `original_filename`, `checksum_sha256`, `local_file_code`, `source_system`, `local_relative_path`

**Expected dry-run report fields:**

```json
{
  "mode": "dry_run",
  "planned_count": 131,
  "invalid_count": 0,
  "create_count": 0,
  "skip_count": 0,
  "fail_count": 0,
  "items": []
}
```

**Tests:**

- tmp inventory with one real temp file passes.
- missing file is invalid.
- checksum mismatch is invalid.
- `--limit 1` only plans one.

---

### Task 7: Implement metadata import over API

**Objective:** Importer creates `assets` records through `POST /api/assets` and skips existing local codes.

**Files:**
- Modify: `scripts/import_assets.py`
- Test: `backend/tests/test_import_assets_script.py`

**API flow per item:**

```text
GET /api/assets?local_file_code=...&source_system=maitu  # source_system filter may need to be added; if not available, filter locally from result
if exists and --skip-existing: mark skipped
else POST /api/assets with asset_create_payload + tags
```

If `source_system` filter is not currently supported, add it to:

- `backend/app/api/routes/assets.py`
- `backend/app/repositories/assets.py`
- `FakeAssetRepository` in tests

**Report item shape:**

```json
{
  "local_file_code": "MT-VID-0024",
  "asset_code": "AG-VID-20260709-000001",
  "operation": "created|skipped|failed",
  "reason": "created|existing-local-file-code|api-error"
}
```

**Verification commands:**

```bash
cd D:/AssetGraph
python scripts/import_assets.py --inventory docs/asset-numbering/asset_inventory_20260709.json --assets-root 素材 --dry-run --limit 5
python scripts/import_assets.py --inventory docs/asset-numbering/asset_inventory_20260709.json --assets-root 素材 --api-base-url http://127.0.0.1:8000 --limit 5 --report-output docs/asset-numbering/import_report_20260709_limit5.json
```

---

### Task 8: Implement file upload from importer

**Objective:** `--upload-files` uploads original media to backend and writes `asset_files`.

**Files:**
- Modify: `scripts/import_assets.py`
- Test: `backend/tests/test_import_assets_script.py`

**Behavior:**

For each created or existing asset:

```text
POST /api/assets/{asset_code}/files
multipart file=actual local media
file_role=original
local_file_code=...
source_relative_path=...
checksum_sha256=...
```

If the file record already exists for `original`, skip upload unless `--replace-files` is explicitly passed. Do not default to replacing.

**Verification:**

Small batch:

```bash
python scripts/import_assets.py \
  --inventory docs/asset-numbering/asset_inventory_20260709.json \
  --assets-root 素材 \
  --api-base-url http://127.0.0.1:8000 \
  --limit 5 \
  --upload-files \
  --report-output docs/asset-numbering/import_report_20260709_limit5_files.json
```

Then:

```bash
curl 'http://127.0.0.1:8000/api/assets?local_file_code=MT-VID-0024'
curl 'http://127.0.0.1:8000/api/assets/{asset_code}/files'
```

---

### Task 9: Add asset retrieval text builder

**Objective:** Create stable textual representation for each asset before embedding.

**Files:**
- Create: `backend/app/services/asset_retrieval_text.py`
- Test: `backend/tests/test_asset_retrieval_text.py`

**Function:**

```python
def build_asset_retrieval_text(asset: dict[str, object]) -> str:
    ...
```

**Expected content order:**

```text
素材编号: AG-...
本地编号: MT-VID-0024
标题: 视频 - 商品讲解视频 - 品酒大师PRO
麦兔类型: 视频
麦兔分类: product_video
用途: 商品讲解视频
主体: 品酒大师PRO
角色: 商品讲解视频
Browser-use提示: 用于麦兔视频素材选择...
本地路径: 视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4
```

**Tests:**

- Includes `asset_code`, `local_file_code`, `title`, `maitu_category`, `usage`, `subject`, `browser_use_hint`.
- Omits `None` values cleanly.
- Deterministic output for same input.

---

### Task 10: Add Milvus vector store service

**Objective:** Prepare AssetGraph to persist Qwen3 embeddings to Milvus.

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/vector_store.py`
- Test: `backend/tests/test_vector_store.py`

**Dependencies:**

```toml
"pymilvus>=2.5.0"
```

**Config:**

```python
milvus_host: str = 'localhost'
milvus_port: int = 19530
milvus_asset_collection: str = 'asset_text_embeddings'
milvus_embedding_dim: int = 1024
```

**Service protocol:**

```python
class VectorStore(Protocol):
    def ensure_asset_collection(self) -> None: ...
    def upsert_asset_embedding(self, *, asset: dict[str, Any], vector: list[float], text: str) -> None: ...
```

**Collection fields:**

- `asset_code` VARCHAR primary key
- `local_file_code` VARCHAR
- `asset_type` VARCHAR
- `maitu_category` VARCHAR
- `maitu_type` VARCHAR
- `usage` VARCHAR
- `subject` VARCHAR
- `text` VARCHAR/TEXT-equivalent per Milvus limit strategy
- `embedding` FLOAT_VECTOR dim 1024

**Tests:**

Unit-test schema builder and fake upsert behavior without requiring live Milvus.

---

### Task 11: Add embedding import script mode

**Objective:** Importer can embed imported assets and write vectors after metadata/file import.

**Files:**
- Modify: `scripts/import_assets.py`
- Or create: `scripts/embed_assets.py` if it stays cleaner.
- Test: `backend/tests/test_import_assets_script.py` or `backend/tests/test_embed_assets_script.py`

**Recommended:** create separate script first:

```text
scripts/embed_assets.py
```

CLI:

```bash
python scripts/embed_assets.py \
  --api-base-url http://127.0.0.1:8000 \
  --qwen3-base-url http://127.0.0.1:8010 \
  --limit 10 \
  --q 'source_system:maitu' \
  --report-output docs/asset-numbering/embed_report_20260709_limit10.json
```

If backend already exposes asset list, script can fetch `GET /api/assets?source_system=maitu&limit=...`, build retrieval text client-side or call backend helper later.

**First implementation can be script-level with fakes**, then later move to background jobs.

---

### Task 12: End-to-end small batch smoke test

**Objective:** Prove the whole chain with 5 real files before full import.

**Prerequisites:**

- PostgreSQL running
- MinIO running
- AssetGraph backend running
- Qwen3 service running
- Migrations applied

**Commands:**

```bash
cd D:/AssetGraph

python scripts/import_assets.py \
  --inventory docs/asset-numbering/asset_inventory_20260709.json \
  --assets-root 素材 \
  --api-base-url http://127.0.0.1:8000 \
  --limit 5 \
  --upload-files \
  --write-tags \
  --report-output docs/asset-numbering/import_report_20260709_limit5.json
```

Then verify:

```bash
curl 'http://127.0.0.1:8000/api/assets?limit=5'
curl 'http://127.0.0.1:8000/api/assets?q=品酒大师'
curl 'http://127.0.0.1:8000/api/assets?maitu_category=product_video'
```

Re-run same command. Expected:

```text
created_count = 0
skipped_count = 5
fail_count = 0
```

---

### Task 13: Full metadata + file + tags import

**Objective:** Import all 131 scanned real assets.

**Command:**

```bash
cd D:/AssetGraph

python scripts/import_assets.py \
  --inventory docs/asset-numbering/asset_inventory_20260709.json \
  --assets-root 素材 \
  --api-base-url http://127.0.0.1:8000 \
  --expected-count 131 \
  --upload-files \
  --write-tags \
  --report-output docs/asset-numbering/import_report_20260709_full.json
```

**Verification:**

```bash
curl 'http://127.0.0.1:8000/api/assets?limit=1&local_file_code=MT-VID-0024'
curl 'http://127.0.0.1:8000/api/assets?maitu_category=digital_human_video&limit=5'
curl 'http://127.0.0.1:8000/api/assets?q=品酒大师&limit=10'
```

**Report review checklist:**

- `invalid_count == 0`
- `fail_count == 0`
- `created_count + skipped_count == 131`
- every failed item, if any, has local_file_code, relative_path, exception message

---

### Task 14: Full embedding pass

**Objective:** Generate and store embeddings for imported assets.

**Command:**

```bash
python scripts/embed_assets.py \
  --api-base-url http://127.0.0.1:8000 \
  --qwen3-base-url http://127.0.0.1:8010 \
  --source-system maitu \
  --limit 131 \
  --report-output docs/asset-numbering/embed_report_20260709_full.json
```

**Verification query:**

```bash
python scripts/search_assets.py \
  --query '品酒大师 商品讲解视频' \
  --top-k 10 \
  --rerank \
  --report-output docs/asset-numbering/search_smoke_20260709.json
```

Expected top results include product video assets with subject/title containing `品酒大师`.

---

### Task 15: Update docs after implementation

**Objective:** Make the import process repeatable for future素材目录 refreshes.

**Files:**
- Modify: `README.md`
- Modify: `docs/mvp-architecture.md`
- Create: `docs/asset-ingestion-runbook.md`

**Runbook must include:**

- prerequisite services
- migration command
- dry-run command
- small batch import command
- full import command
- rerun/idempotency behavior
- where reports are saved
- how to verify API lookup
- rollback / cleanup policy

**Rollback policy:**

Do not hard-delete imported `AG-*` records by default. If a bad import happens, mark records `archived` or `failed` with a report reference; keep codes non-reused.

---

## Migration / Deployment Notes

### Applying migrations

If no migration runner exists yet, implement a tiny script first:

```text
scripts/apply_migrations.py
```

Behavior:

- Connect to PostgreSQL using `backend/app/core/config.py` settings or env vars.
- Ensure `schema_migrations(version text primary key, applied_at timestamptz)` exists.
- Apply sorted `backend/migrations/*.sql` once.
- Print applied/skipped list.

Do this before Task 12 if migrations cannot be reliably applied manually.

### Docker is not optional for real import

Real file import requires at least:

- PostgreSQL
- MinIO

Embedding import additionally requires:

- Qwen3 service
- Milvus

If Docker Desktop is not running, stop before real import and report blocker.

---

## Risk Register

| Risk | Mitigation |
|---|---|
| Duplicate import generates multiple `AG-*` for same `MT-*` | Unique index on `(source_system, local_file_code)` + importer `--skip-existing` |
| Wrong file uploaded for metadata | Verify path exists, file size and sha256 match inventory before upload |
| Large videos make upload slow | Start with `--limit 5`, report per-file duration and size |
| MinIO unavailable | Fail fast on `/health` / bucket check before import |
| Qwen3 model switching is slow | Keep embedding pass separate from metadata/file import; batch embeddings |
| Milvus schema mismatch | Explicit `milvus_embedding_dim` config and fake + live smoke tests |
| Bad full import pollutes DB | Use small batch first; no hard deletes; status can be archived/failed |
| Tags explode into noisy keywords | Use existing scanner tags first; do not auto-tokenize more in importer |

---

## Recommended Execution Order

1. Task 1: ingestion hardening migration.
2. Task 2: MinIO config/storage abstraction.
3. Task 3: asset file repository methods.
4. Task 4: asset file upload/list API.
5. Task 5: tag support.
6. Task 6: importer dry-run validator.
7. Task 7: metadata import.
8. Task 8: file upload import.
9. Task 12: small batch smoke test.
10. Task 13: full metadata/file/tags import.
11. Task 9 + 10 + 11: embedding text, Milvus store, embedding scripts.
12. Task 14: full embedding pass.
13. Task 15: docs/runbook.

This order deliberately gets real素材 safely into PostgreSQL/MinIO first, then adds vector retrieval. Do not start with Milvus; file-backed asset truth must be stable first.

---

## Final Verification Suite

Run all before calling implementation complete:

```bash
cd D:/AssetGraph/backend
.venv/Scripts/python.exe -I -m pytest -q
.venv/Scripts/python.exe -I -m compileall -q app

cd D:/AssetGraph/workers/browser-use
uv run --extra dev python -I -m pytest -q

cd D:/AssetGraph
python scripts/scan_assets.py --assets-root 素材 --expected-count 131 --quiet
python scripts/import_assets.py --inventory docs/asset-numbering/asset_inventory_20260709.json --assets-root 素材 --dry-run --expected-count 131
```

For live import verification:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8010/health
curl 'http://127.0.0.1:8000/api/assets?q=品酒大师&limit=10'
```
