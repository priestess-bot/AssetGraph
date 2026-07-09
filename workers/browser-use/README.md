# AssetGraph Browser-use Worker

This worker lives in the same repository as AssetGraph so the API, RAG ingestion code, local asset inventory, and Maitu browser automation protocol can be deployed or migrated together.

Current status: scaffold plus tested Maitu executor abstraction and a read-only Browser-use CLI session probe. It implements the queue/claim/release/result protocol boundary, dispatches AssetGraph operation plans to a thin browser session interface, and can verify the current Maitu page/login state without uploading, replacing, or saving anything. Mutating browser automation is still intentionally not bound.

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
python -m browser_use_worker --once --dry-run
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --dry-run
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight --skip-browser-probe
```

`--preflight --plan-code ...` fetches the replacement plan operation plan and performs read-only safety checks before any mutating Browser-use execution. It validates operation support, Maitu project/scene context, AssetGraph asset lookup, Browser-use-friendly asset fields, local file availability under `--assets-root` (default `D:/AssetGraph/素材`), the current Maitu browser/login shell, and whether the target layer/slot name is visible on the current page. It exits with code `0` when there are no failures and code `2` when a blocking check fails. `ready_to_execute` is only `true` when there are no failures, warnings, or skipped checks.

`--skip-browser-probe` is useful in headless CI or API-only smoke tests: all AssetGraph/local-file checks still run, but the result is a warning and `ready_to_execute=false` because the Maitu browser session was not verified.

`--plan-code ... --dry-run` fetches `/api/maitu/replacement-plans/{plan_code}/browser-use-operations`, validates the operation plan shape, and prints the exact operations Browser-use would execute, including `asset_display_code`, local file code, original filename, and instruction text. It does not claim retry tasks, open Maitu, upload assets, replace layers, or save a project.

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

Implemented read-only session:

```text
BrowserUseCliSession
  -> uv run browser-use state
  -> falls back to browser-use eval for title/url/body text
  -> opens Maitu home if the active page is unrelated
  -> detects logged-in dashboard vs login page
  -> refuses upload/replace/save operations
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
