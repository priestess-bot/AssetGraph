# Maitu Live-room Builder Next Phases Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 把当前已完成的 Observe → Profile/Blueprint → BuildPlan dry-run，推进到 Browser-use 只读 preflight、素材自动填充、可控小步执行、结果回写与复盘学习的完整闭环。

**Architecture:** AssetGraph 继续作为决策与计划层：保存参考直播间 Profile/Blueprint、生成 BuildPlan、调用素材检索/脚本生成、记录执行结果。Browser-use 作为现场层：读取麦兔真实页面、对 BuildPlan 做只读 preflight、执行小步 UI 动作、截图/状态回写。每个阶段都先做 API/文件/只读验证，再逐步放开非破坏性 UI 操作，最后才允许受控保存草稿；默认永远不点击“正式开播”。

**Tech Stack:** FastAPI + PostgreSQL + JSONB migrations + pytest；Browser-use worker Python package；Maitu live-room web UI；local Qwen3 embedding/reranker artifacts；existing AssetGraph asset/slot/candidate APIs。

---

## Current Baseline 已完成基线

截至 `e1d2592 feat: generate maitu build plans`，已经完成：

1. **Observe**
   - `python -m browser_use_worker --observe-maitu`
   - 输出真实麦兔当前页状态。
   - artifact: `docs/asset-numbering/current_maitu_state_39826_20260709.json`

2. **Profile / Blueprint artifact**
   - `scripts/extract_maitu_reference_room.py`
   - 输出：
     - `docs/asset-numbering/reference_room_profile_39826_20260709.json`
     - `docs/asset-numbering/live_room_blueprint_39826_20260709.json`
     - `docs/asset-numbering/live_room_blueprint_39826_20260709.md`

3. **Blueprint API ingestion**
   - `POST /api/maitu/live-room-blueprints/import-reference`
   - `GET /api/maitu/live-room-blueprints/{blueprint_code}`
   - DB tables:
     - `maitu_reference_room_profiles`
     - `maitu_live_room_blueprints`

4. **BuildPlan dry-run**
   - `POST /api/maitu/live-room-build-plans`
   - `GET /api/maitu/live-room-build-plans/{build_plan_code}`
   - `GET /api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations`
   - DB tables:
     - `maitu_live_room_build_plans`
     - `maitu_live_room_build_plan_operations`
   - 实测：`MT-BUILD-20260709-000001` 生成 17 个 operation。

---

# Phase 1 — BuildPlan 只读 Preflight 接入 Browser-use worker

## Goal

让 worker 能从后端拉取 `MT-BUILD-*` 的 Browser-use operations，并与当前麦兔真实页面状态对比，输出可审阅的 preflight 结果。

## Non-goals

- 不点击保存。
- 不替换素材。
- 不写入脚本。
- 不点击“正式开播”。

## Task 1.1: Worker client 支持 BuildPlan operations

**Objective:** 给 worker 的 AssetGraph client 增加读取 BuildPlan operation plan 的方法。

**Files:**
- Modify: `workers/browser-use/src/browser_use_worker/client.py`
- Test: `workers/browser-use/tests/test_client.py`

**Steps:**
1. 写失败测试：`AssetGraphClient.get_live_room_build_plan_operation_plan("MT-BUILD-...")` 请求 `/api/maitu/live-room-build-plans/{code}/browser-use-operations`。
2. 确认失败：方法不存在。
3. 实现方法。
4. 跑：
   ```bash
   cd workers/browser-use
   python -m pytest tests/test_client.py -q
   ```
5. 提交：
   ```bash
   git add workers/browser-use/src/browser_use_worker/client.py workers/browser-use/tests/test_client.py
   git commit -m "feat: fetch maitu build plan operations"
   ```

## Task 1.2: 新增 BuildPlan preflight 结果模型

**Objective:** 定义 BuildPlan preflight 的统一输出结构，区别于 replacement preflight。

**Files:**
- Create/Modify: `workers/browser-use/src/browser_use_worker/build_plan_preflight.py`
- Test: `workers/browser-use/tests/test_build_plan_preflight.py`

**Checks to implement:**
- operation list 非空。
- operation_type 在 allowlist：
  - `preflight_build_plan`
  - `select_scene`
  - `replace_layer_asset`
  - `add_script_block`
  - `save_live_room`
- `save_live_room` 必须是 `manual_review`，否则 fail。
- instruction 不能包含真实开播动作；如果包含 `正式开播` 但不是“默认不点击正式开播/不点击正式开播”的否定语境，则 fail。
- 对 `replace_layer_asset`，必须有 `scene_name`、`layer_name`、`replacement_policy`。
- 对 `add_script_block`，必须有 `scene_name`、`script_block_content`。

**Verification:**
```bash
cd workers/browser-use
python -m pytest tests/test_build_plan_preflight.py -q
```

## Task 1.3: BuildPlan preflight 对比真实麦兔 Observe 状态

**Objective:** 使用 `BrowserUseCliSession.read_current_state()` 读取当前页面，并与 BuildPlan operation context 对齐。

**Files:**
- Modify: `workers/browser-use/src/browser_use_worker/build_plan_preflight.py`
- Test: `workers/browser-use/tests/test_build_plan_preflight.py`

**Checks:**
- 当前页已登录：`logged_in=true` 且 `login_required=false`。
- 当前 `live_room_id` 与 BuildPlan/Blueprint 目标一致。当前 operation payload 还没有顶层 `reference_room_id`，可先从 select_scene / details / future field 获取；若缺失则 warning。
- BuildPlan 中涉及的 `scene_name` 均在 observed `scenes[]` 中存在。
- 当前激活场景中的 `layer_name` 可在 observed `layers[]` 中找到；对非激活场景图层先 warning，不 fail。
- `active_workbench_tab` / `workbench_tabs` 中存在 `直播脚本`，否则 `add_script_block` warning/fail。

**Verification:**
- fake session 测试 pass/warning/fail 三类结果。
- 真实 smoke：
  ```bash
  cd D:/AssetGraph/workers/browser-use
  python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build
  ```

## Task 1.4: CLI 接入

**Objective:** 支持命令行只读预检 BuildPlan。

**Files:**
- Modify: `workers/browser-use/src/browser_use_worker/__main__.py`
- Test: `workers/browser-use/tests/test_cli.py`

**CLI:**
```bash
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build --skip-browser-probe
```

**Expected output:**
```json
{
  "status": "passed|warning|failed",
  "ready_to_execute": false,
  "build_plan_code": "MT-BUILD-20260709-000001",
  "operation_count": 17,
  "checks": []
}
```

`--skip-browser-probe` 必须输出 warning 且 `ready_to_execute=false`，避免 CI 冒充真实 UI readiness。

---

# Phase 2 — BuildPlan 素材自动填充与 operation enrichment

## Goal

让 `replace_layer_asset` 不再只是“规划图层”，而是能基于 LayerBlueprint 自动选择素材，并把 Browser-use 需要的 UI 友好字段写入 operation。

## Task 2.1: 后端 BuildPlan operation 增加选材状态字段

**Files:**
- Modify migration or new migration: `backend/migrations/010_maitu_build_plan_asset_selection.sql`
- Modify: `backend/app/schemas/maitu.py`
- Modify: `backend/app/repositories/maitu.py`
- Test: `backend/tests/test_maitu_slot_routes.py`

**Fields:**
- `asset_code`
- `asset_title`
- `asset_display_code`
- `asset_local_file_code`
- `asset_original_filename`
- `asset_local_relative_path`
- `asset_browser_use_hint`
- `match_score`
- `match_reasons JSONB`
- `selection_status`: `selected|missing|manual_required`

## Task 2.2: LayerBlueprint → candidate query

**Approach:**
For each layer operation:

```text
required_category + accepted_asset_types + layer_role + scene_name + layer_name
  -> /api/assets/candidates or internal AssetRetrievalIndex service
  -> Top-1 selected asset
```

Start with deterministic rule/semantic artifact endpoint; keep missing assets explicit.

**Acceptance:**
- 背景层 `微信图片_20260618221607_11_15` 能选中类似 `MT-BG-0004`。
- 数字人层暂时可标为 `manual_required`，避免误选主播。
- 未选中素材不阻断 BuildPlan 生成，但 operation status 应是 `missing_asset` 或 `manual_required`。

## Task 2.3: Browser-use operation payload enrichment

**Output example:**
```json
{
  "operation_type": "replace_layer_asset",
  "scene_name": "场景01",
  "layer_name": "微信图片_20260618221607_11_15",
  "asset_code": "AG-IMG-...",
  "asset_display_code": "MT-BG-0004",
  "asset_local_file_code": "MT-BG-0004",
  "asset_original_filename": "...png",
  "asset_local_relative_path": "背景/MT-BG-0004.png",
  "asset_browser_use_hint": "用于麦兔背景素材选择...",
  "replacement_policy": "keep_layout"
}
```

**Verification:**
```bash
cd backend
python -m pytest tests/test_maitu_slot_routes.py -q
```

---

# Phase 3 — BuildPlan worker dry-run / preflight operation executor

## Goal

让 worker 能读取 BuildPlan operations 并做 dry-run 展示，不操作麦兔页面。

## Task 3.1: Worker dry-run 支持 BuildPlan ✅

**CLI:**
```bash
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --dry-run
```

**Implemented behavior:**
- 拉取 operations。
- 打印每个 operation 的 `safe_action` 摘要。
- 不调用 Browser-use click/input。
- 不打开浏览器。
- 不 claim retry queue。
- `replace_layer_asset` 输出为 `planned_layer_asset_replacement_not_executed`。
- `add_script_block` 输出为 `planned_script_block_not_executed`。
- `save_live_room(manual_review)` 输出为 `manual_review_save_not_executed`。
- 如果 `save_live_room.status != manual_review` 或 instruction 试图“正式开播”，返回 failed。

**Files:**
- Added: `workers/browser-use/src/browser_use_worker/build_plan_dry_run.py`
- Modified: `workers/browser-use/src/browser_use_worker/__main__.py`
- Test: `workers/browser-use/tests/test_build_plan_dry_run.py`, `workers/browser-use/tests/test_cli.py`

## Task 3.2: Preflight gate blocks mutating operations

Before any future real executor:

```text
if preflight.ready_to_execute is not true:
    refuse to execute mutating operation
```

For now, all mutating execution paths remain disabled.

---

# Phase 4 — 非破坏性 UI 动作放开

## Goal

开始验证 Browser-use 能稳定定位麦兔 UI，但不提交、不保存。

## Allowed actions

1. 打开/确认 live room URL。
2. 选择场景 tab/card。
3. 打开素材页签：背景、装饰、视频、文本。
4. 打开直播脚本 tab。
5. 截图/Observe 回读。

## Forbidden actions

- 上传素材。
- 替换素材。
- 写入脚本。
- 保存直播间。
- 点击正式开播。

## Deliverables

- `BuildPlanNonDestructiveRunner` ✅
- CLI `--build-plan-code MT-BUILD-* --non-destructive-build` ✅
- 每步执行后重新 Observe ✅
- 如果 preflight 不是全绿，直接 blocked 且不执行任何 UI 导航 ✅
- 截图路径 / DOM 状态记录（后续）。
- 如果 scene/layer 不存在，返回 failure_type：`missing_scene` / `missing_layer`（后续扩展为执行结果 taxonomy）。

---

# Phase 5 — 受控 mutation：只在草稿/测试房间执行一个小动作

## Goal

选择一个低风险动作，完成 Act → Verify → Learn 的第一条真实闭环。

## Candidate action

优先级：

1. 在复制/测试直播间中选择 `场景01` 并写入一段无害脚本文本，然后保存草稿。
2. 或替换背景图层为已存在背景素材，并保存草稿。

## Required safety gates

- 必须是测试/复制直播间，不直接改用户当前正式参考直播间。
- preflight 全绿。
- 操作前截图。
- 操作后 Observe。
- 保存后再次 Observe / 截图。
- 后端写入 `MT-EXEC-*` 执行结果。
- 不点击正式开播。

## Backend additions

- BuildPlan execution result endpoint：
  ```http
  POST /api/maitu/live-room-build-plans/{build_plan_code}/execution-results
  GET  /api/maitu/live-room-build-plans/{build_plan_code}/execution-results
  GET  /api/maitu/live-room-build-plans/{build_plan_code}/execution-results/{execution_code}
  ```
- Operation result fields mirror replacement execution results, but operation key is generic, not slot-only。
- Worker `--non-destructive-build --write-result` can now persist a blocked preflight gate or completed low-risk action evidence as `MT-EXEC-*`.

---

# Phase 6 — Learn / Retry / Template library

## Goal

把成功路径、失败类型、截图证据、可复用模板沉淀回 AssetGraph。

## Work items

1. BuildPlan retry tasks：
   - `MT-BUILD-RETRY-*` 或复用 `MT-RETRY-*`，但需区分 BuildPlan vs ReplacementPlan。
2. Failure taxonomy：
   - `missing_scene`
   - `missing_layer`
   - `script_panel_missing`
   - `asset_not_found`
   - `upload_failed`
   - `save_failed`
   - `login_expired`
   - `selector_changed`
   - `manual_required`
3. Successful template extraction：
   - 将可复用的场景/图层/脚本组合写回 Template/Profile。
4. Evidence assets：
   - 截图入库，绑定 execution_code / operation index。

---

# Phase 7 — 从“参考重建”走向“从0搭建”

## Goal

基于商品资料和直播目标，生成新的 LiveRoomBlueprint，而不是只从参考直播间 rebuild。

## Inputs

- 商品资料。
- 直播目标。
- 参考直播间 profile。
- 素材库候选。
- 数字人/音色选择。
- 脚本模板。

## Outputs

- New `LiveRoomBlueprint` with:
  - scenes
  - layers
  - script blocks
  - selected assets
  - product refs
  - digital human / voice refs
- BuildPlan with create/configure operations:
  - `create_blank_live_room`
  - `rename_live_room`
  - `create_scene`
  - `insert_material_layer`
  - `set_layer_transform`
  - `add_script_block`
  - `save_live_room`

## Gate

Only after Phase 4/5 prove UI stability should create/configure operations be enabled.

---

# Recommended Execution Order

## Sprint 1: BuildPlan preflight

1. Worker client fetches BuildPlan operations.
2. BuildPlan preflight model and tests.
3. CLI `--build-plan-code --preflight-build`.
4. Real smoke against `MT-BUILD-20260709-000001`.
5. Docs + commit.

## Sprint 2: Asset selection enrichment

1. DB/API fields for selected assets on build operations.
2. Candidate selection from LayerBlueprint context.
3. Enriched Browser-use payload.
4. Real smoke: background layer gets a selected asset; digital human remains manual if uncertain.
5. Docs + commit.

## Sprint 3: Worker dry-run and non-destructive UI

1. `--build-plan-code --dry-run` ✅
2. Select scene / open tabs only ✅
3. Observe after each action ✅
4. Evidence report（blocked/completed execution result write-back）✅
5. Screenshot/DOM artifact upload（next）
6. Docs + commit ✅

## Sprint 4: Controlled first mutation

1. Create/choose test room.
2. Run full preflight.
3. Execute one safe operation.
4. Save draft only if explicitly approved.
5. Write execution result and screenshot evidence.
6. Docs + commit.

---

# Verification Commands

Backend:

```bash
cd D:/AssetGraph/backend
python -m pytest -q
python -m compileall -q app
```

Worker:

```bash
cd D:/AssetGraph/workers/browser-use
python -m pytest -q
python -m compileall -q src
```

Real API smoke:

```bash
curl "http://127.0.0.1:8000/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/browser-use-operations"
```

Real worker smoke, read-only / non-destructive:

```bash
cd D:/AssetGraph/workers/browser-use
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --dry-run
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build --write-result
```

---

# Success Criteria for the Next Milestone

The next milestone is complete when:

- `--build-plan-code MT-BUILD-20260709-000001 --preflight-build` exists.
- It fetches backend BuildPlan operations.
- It reads current Maitu state with Browser-use Observe.
- It compares live room / scene / active scene layers / script panel against the BuildPlan.
- It returns structured pass/warning/fail checks.
- It never clicks, saves, uploads, or goes live.
- Backend and worker tests pass.
- A real read-only smoke test against `39826` is documented.

---

# Added Track — Natural-language Layout Adjustment Loop

用户提出的关键问题是：素材按槽位放上去后，如果用户觉得位置不对，如何用自然语言精准调整。当前已新增第一步：

```http
POST /api/maitu/layout-adjustments
GET  /api/maitu/layout-adjustments/{adjustment_code}
```

已实现：

```text
用户自然语言 + before_geometry + canvas size
  -> MT-ADJ-* adjustment plan
  -> target_geometry
  -> set_layer_transform operation
  -> checks
```

已支持模式：

- `往右下挪一点，缩小一点`
- `往左50px，再往上30px`
- `水平居中`
- `放到右下角，留点边距`
- 模糊的 `调好看点` 返回 `manual_required`，不盲动

下一步要把它并入 Sprint 1/3 的 worker preflight/dry-run：

1. Browser-use Observe 必须读取/估计图层几何：`x/y/width/height/z_index/rotation`。
2. Worker 新增 `--adjustment-code MT-ADJ-* --dry-run`，只打印目标几何和 set_layer_transform。
3. Worker 新增 `--adjustment-code MT-ADJ-* --preflight-adjustment`：检查目标图层可见、未锁定、目标几何在画布内。
4. 后续真实执行时必须小步 set transform，然后重新 Observe，比较 `actual_geometry` 与 `target_geometry`，误差大于 5px 则补偿或回滚。
