# AssetGraph Browser-use Worker

This worker lives in the same repository as AssetGraph so the API, RAG ingestion code, local asset inventory, and Maitu browser automation protocol can be deployed or migrated together.

Current status: scaffold only. It implements the queue/claim/release/result protocol boundary without binding to a concrete browser-use runtime yet.

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
python -m browser_use_worker --once --dry-run
```

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
