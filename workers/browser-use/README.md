# AssetGraph Browser-use Worker

This worker lives in the same repository as AssetGraph so the API, RAG ingestion code, local asset inventory, and Maitu browser automation protocol can be deployed or migrated together.

Current status: tested AssetGraph/Maitu execution worker with read-only probes, BuildPlan safety gates, content-driven draft execution, and Stage 5D material resolution. Before a real draft build it can reuse verified AssetGraph bindings, deduplicate against the authenticated Maitu material inventory, upload missing regular image/video assets through the visible 素材管理 UI, read back the newly created type-compatible record, and persist the verified binding. Ambiguous matches, missing files, unsupported digital-human uploads, and upload/readback failures remain manual-only and stop combined resolution/execution before draft mutations.

## Responsibilities

```text
AssetGraph backend:
  - owns data, RAG metadata, retry queue, operation plans
  - exposes /api/maitu/retry-worker/next
  - accepts retry execution result write-back

Browser-use worker:
  - claims retry tasks
  - executes operation_plan.operations in Maitu
  - writes success / release / manual_required results back to AssetGraph
```

## Local development

```bash
cd workers/browser-use
python -m browser_use_worker --check-config
python -m browser_use_worker --probe-maitu
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --dry-run
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight --skip-browser-probe
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --dry-run
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build --skip-browser-probe
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build --write-result
python -m browser_use_worker --script-layout-build-plan-file /tmp/script-layout-build-plan.json --script-layout-draft-execute --dry-run
python -m browser_use_worker --resolve-maitu-materials --script-layout-build-plan-file /tmp/script-layout-build-plan.json --resolved-plan-file /tmp/resolved-build-plan.json
python -m browser_use_worker --resolve-maitu-materials --script-layout-build-plan-file /tmp/script-layout-build-plan.json --resolved-plan-file /tmp/resolved-build-plan.json --script-layout-draft-execute --target-live-room-id 40173
```

`--preflight --plan-code ...` fetches the replacement plan operation plan and performs read-only safety checks before any mutating Browser-use execution. It validates operation support, Maitu project/scene context, AssetGraph asset lookup, Browser-use-friendly asset fields, local file availability under `--assets-root` (default `D:/AssetGraph/素材`), the current Maitu browser/login shell, and whether the target layer/slot name is visible on the current page. It exits with code `0` when there are no failures and code `2` when a blocking check fails. `ready_to_execute` is only `true` when there are no failures, warnings, or skipped checks.

`--skip-browser-probe` is useful in headless CI or API-only smoke tests: all AssetGraph/local-file checks still run, but the result is a warning and `ready_to_execute=false` because the Maitu browser session was not verified.

`--plan-code ... --dry-run` fetches `/api/maitu/replacement-plans/{plan_code}/browser-use-operations`, validates the operation plan shape, and prints the exact operations Browser-use would execute, including `asset_display_code`, local file code, original filename, and instruction text. It does not claim retry tasks, open Maitu, upload assets, replace layers, or save a project.

`--build-plan-code ... --dry-run` fetches `/api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations` and prints a safe-action summary for the whole BuildPlan. Read-only operations are rendered as read-only; mutating operations such as `replace_layer_asset` / `insert_template_component` and `add_script_block` are rendered as `planned_*_not_executed`; `create_scene_from_template` is planned only; `save_live_room` must stay `manual_review`. It does not claim retry tasks, open Maitu, click, upload, write scripts, save drafts, or start live streaming. If the BuildPlan was created with `strategy=script_context_best_match` / `auto_select_assets=true`, the dry-run output includes selected asset codes, display/local file codes, match score, and match reasons for review only. `MT-TPL-*` template preview assets are style/structure indexes only; direct layer operations should use the component assets behind the template, not the template preview image itself.

`--preflight-build --build-plan-code ...` fetches the same BuildPlan operation plan and performs read-only checks against the current Maitu state: login status, target live room id, scene names, active-scene layer names, script tab availability, operation allowlist, save/manual-review status, and unsafe go-live instructions. It also validates single-scene template operations (`preflight_scene_build_plan`, `create_scene_from_template`, `insert_template_component`) and requires template/component geometry before any future insertion step.

`--non-destructive-build --build-plan-code ...` requires that same real preflight to pass with no warnings/skips/failures. It then allows only low-risk UI navigation: select existing scenes, open inferred material tabs, open the `直播脚本` tab, and re-observe after each action. It still refuses scene creation, template component insertion, upload, insert/replace, typing script text, save, and go-live actions.

`--write-result` can be added to `--non-destructive-build` to POST `/api/maitu/live-room-build-plans/{build_plan_code}/execution-results`. A preflight-blocked run writes a `blocked` `MT-EXEC-*` record with a synthetic `preflight_gate` operation result; a completed low-risk run writes one operation result per action, including details and optional screenshot/DOM asset references.

`--script-layout-draft-execute --script-layout-build-plan-file ...` runs the Stage 5A/5B content-driven draft executor against a `POST /api/maitu/script-layout-build-plans` JSON response. With `--dry-run` it uses an in-memory Maitu room for local smoke testing: ready operations are executed against the in-memory draft, `placeholder_required` remains manual-only, `save_draft` remains a review gate, and `ready_for_go_live=false` is always preserved. Simulation never writes production execution results; `--dry-run --write-result` is rejected. A real, non-dry-run draft execution must also pass `--resolve-maitu-materials`; raw plans are never sent directly to `ScriptLayoutDraftRunner`. After the Stage 5D whole-plan and material gate passes, the worker uses the Browser-use session boundary: it can map the first planned scene to the default clip, create later draft scenes, write scripts, and verify scenes through the Maitu API. Selected AssetGraph assets require a real Maitu material binding (`source_material_url` / `material_id` / digital-human ids); when that binding is missing the worker blocks before any draft operation instead of inserting a fake layer. It still must not click 正式开播.

The Stage 6A execution safety kernel rejects conflicting CLI modes before constructing API/browser clients, rejects `--live-scene-fill --dry-run`, and refuses dry-run queue claim/release, metric capture, real-browser navigation, resolver upload/write-back, or production execution-result write-back. A bare `--dry-run` is invalid; it must name an explicit read-only plan/preflight/probe/observe or the in-memory script-layout mode. Every direct Maitu API script requires exact `https://live2.maituai.com` origin plus a non-empty authenticated token. Script-layout and live-scene-fill execution are both bound to the BuildPlan target room; a single-scene BuildPlan intended for real fill must be created with `target_live_room_id`, and its first operation must carry the same target in a ready `safety_gate=true` preflight. Authoritative room-id mismatch, a non-working/draft read environment, active-live flags, or missing/unknown not-live evidence block mutation. Every operation type is validated for the complete plan before the first browser call; execution still stops after the first runtime failure and unknown generic operations fail closed. Script updates preserve audio, update/create text idempotently, remove only duplicate text entries, and require unique authoritative content readback. Warning, blocked, skipped, or manual-review outcomes return exit code `2` for unattended callers.

`--resolve-maitu-materials` adds the Stage 5D material gate before draft execution. It validates the complete operation plan and every unique `insert_asset_layer.asset_code` before side effects; unsupported/go-live operations and blocking placeholders fail closed. Regular bindings require a positive Maitu material ID, a type-compatible source type, and an authoritative HTTPS source URL; digital-human bindings require a digital-human source type plus positive speaker and image IDs. Stored material IDs are revalidated against the complete, schema-checked paginated Maitu inventory. A unique verified match is written back through `PATCH /api/assets/{asset_code}/maitu-material-binding`; missing regular images/videos are uploaded only through the unique compatible file input on the active tab at the exact `https://live2.maituai.com/MaterialManage` origin, and the target is reverified immediately before local-file upload. Only a newly created, type-compatible, filename-matching record is accepted. A local digital-human training video is never uploaded as a regular video substitute. Ambiguity, malformed inventory/plan/API responses, missing files, local file/layer type mismatch, unsupported digital-human creation, upload errors, or unverifiable readback/writeback set `manual_required` and make the combined resolver/draft command exit `2` before executing any draft operation.

`--probe-maitu` is read-only. It calls the local `D:/browser-use` CLI, inspects the current page, opens Maitu home when the active page is unrelated, and prints JSON with `url`, `logged_in`, `login_required`, and `opened_home`. It never uploads assets, replaces layers, or saves a Maitu project.

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `ASSETGRAPH_API_BASE_URL` | `http://127.0.0.1:8000` | AssetGraph backend base URL |
| `BROWSER_USE_WORKER_ID` | hostname/pid based | Claim owner sent to AssetGraph |
| `BROWSER_USE_LOCK_TTL_SECONDS` | `900` | Retry task lock TTL |
| `BROWSER_USE_POLL_INTERVAL_SECONDS` | `5` | Sleep interval when no task is available |
| `BROWSER_USE_MAX_ATTEMPTS` | `3` | Max retry attempts filter |

## Production note

The worker should run on a machine/session that can open the Maitu web UI and keep browser state/cookies. The backend and worker can be packaged together, but browser automation may still require a desktop-capable Windows runtime.

## Real browser-use integration point

Implemented visible Browser-use CLI session:

```text
BrowserUseCliSession
  -> uv run browser-use state / eval / open / upload
  -> falls back to browser-use eval for title/url/body text
  -> opens Maitu home or 素材管理 when the active page is unrelated
  -> detects logged-in dashboard vs login page
  -> can click existing scene/material/workbench tabs after safety checks
  -> can upload regular image/video materials only for Stage 5D resolution
  -> reads back Maitu inventory and accepts only a newly created compatible record
  -> does not click 正式开播
```

The tested execution boundary for future mutating automation is:

```text
MaituBrowserUseExecutor
  -> MaituBrowserSession.ensure_ready()
  -> MaituBrowserSession.upload_asset()
  -> MaituBrowserSession.replace_layer_asset()
  -> MaituBrowserSession.save_project()
  -> MaituBrowserSession.capture_screenshot()
```

A real implementation should provide `MaituBrowserSession` using browser-use / Playwright selectors. The executor already handles:

- loading AssetGraph asset metadata with `GET /api/assets/{asset_code}`
- dispatching `retry_replace_layer_asset`
- dispatching `retry_asset_upload_and_replace`
- dispatching `retry_save_project`
- dispatching `recover_login_then_retry`
- converting recoverable browser failures into queue releases
- converting missing assets/manual operations into `manual_required`
