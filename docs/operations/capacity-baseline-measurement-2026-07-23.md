# Capacity Baseline Measurement

> Measurement time: 2026-07-23 21:18 JST
> Baseline commit: `d946631` plus current working-tree implementation
> Status: incomplete; this report does not satisfy `CHK-0110`.

The repeatable collector is now `scripts/measure_capacity_baseline.py`; its
versioned approval input template is
`docs/operations/capacity-baseline-input.v1.example.json`. The collector always
uses a read-only transaction, UTC and half-open intervals, records no DSN/raw row,
and emits a fingerprinted `capacity-baseline-report.v1`.

## Measurement Boundary

The configured operational PostgreSQL endpoint is `127.0.0.1:55432`. Two
consecutive readiness checks returned no response. The running backend health
endpoint on port `8000` returned HTTP 200, but a representative data endpoint
returned HTTP 500. Docker metadata and volumes cannot be inspected by the current
user because the Docker socket is restricted. No database password, token or raw
event payload was read or written during this measurement.

The isolated PostgreSQL databases on port `55433` contain migration and automated
test fixtures. They are valid schema/test evidence but are explicitly excluded
from operational asset, event, workflow and throughput counts. Synthetic fixture
counts must never be copied into a capacity forecast.

The collector was exercised against the isolated database for the half-open
window `[2026-07-01T00:00:00Z, 2026-07-24T00:00:00Z)`. The retained report is
`docs/evidence/phase-0-capacity-baseline-integration-2026-07-23.json`, fingerprint
`32d49c59e163cbd011dc21b58fb306e5f7dd9d351cb6d22f73c71f24becf24f2`.
Collection succeeded, but the report is hard-coded by its evidence gates to
`qualifies_for_chk_0110=false`: it is not operational data, has no operational
snapshot reference, has no approved capacity input and did not reconcile object
storage.

## Measured Local Values

| Signal | Measured value | Meaning / limitation |
| --- | ---: | --- |
| Logical CPUs | 64 | Current development host only. |
| Physical memory | 270,132,334,592 bytes | Current development host only; not an application reservation. |
| Root filesystem available | 83,467,808,768 bytes | Snapshot at measurement time. |
| `/DATA` available | 1,400,455,979,008 bytes | Shared filesystem, not an AssetGraph quota. |
| Repository working tree | 26,915,287,118 bytes | Includes local dependencies/build outputs. |
| `/DATA/Downloads/AssetGraph` | 20,008,446,765 bytes | Includes runtimes, models, caches and business artifacts. |
| Local material candidate files | 63 files / 13,521,513,713 bytes | Files under `素材`; not authoritative `asset_count` and may include duplicates/unregistered files. |
| Raw recordings | 0 files / 4,096 directory bytes | Local directory only; remote/object storage and expired rows unknown. |
| Raw event files | 0 files / 4,096 directory bytes | Local directory only; database and remote batches unknown. |
| Permanent clips | 0 files / 4,096 directory bytes | Local directory only. |
| Video production outputs | 4 job directories, 136 files / 318,577,187 bytes | Existing local outputs; job rows, dates and failures unavailable. |
| Material-analysis outputs | 19 files / 12,845,742 bytes | Local analysis artifacts only. |
| Maitu mirror | 1 file / 69,174 bytes | Local observation mirror only. |
| Running video worker processes | 1 | Single-process loop claims at most one job at a time; operational DB connection was unavailable. |
| Running Browser-use workers | 0 observed | Process snapshot only; account/room concurrency cap remains unknown. |
| Running live-research schedulers | 0 observed | Code enforces one active target per scheduler instance; total allowed instances remains unknown. |

## Required Values Still Unknown

- authoritative active/archived asset count and daily additions;
- recording hours per day and peak concurrent capture;
- raw and standardized event peak per second, backlog and watermark lag;
- concurrent live sessions and platform/account limits;
- render jobs per day, p50/p95 duration and proven concurrent render capacity;
- ArtifactRef daily byte/object growth by retention class and object-store copies;
- WorkflowRun count, queue depth, p50/p95 duration and worker saturation;
- Browser-use account/room concurrency, lock contention and safe upper bound;
- 12-month forecasts, peak factors and unit costs for every preceding signal.

## Completion Procedure

1. Restore read-only access to the configured operational PostgreSQL and provide
   ephemeral read/list-only object-store credentials without changing application
   state.
2. Record the exact source/database snapshot, measurement window and whether
   deleted/expired/quarantined rows are included for each query.
3. Derive per-second peaks from event time and processing time separately; derive
   concurrency using half-open start/end intervals rather than status counts.
4. Reconcile ArtifactRef bytes with object metadata and local/remote versions;
   report unmatched rows and objects instead of dropping them.
5. Count configured worker/account limits independently from currently running
   processes and observed workload.
6. Add 12-month forecast assumptions, peak factors, unit-cost sources, warning
   and stop thresholds, owner and approval references.
7. Run the queries twice from the same snapshot, archive outputs with redacted
   connection information, and only then update `CHK-0110` and its execution log.

Execute the first retained operational measurement with an approved, non-example
capacity input:

```bash
ASSETGRAPH_DATABASE_URL="$OPERATIONAL_READ_ONLY_DATABASE_URL" \
ASSETGRAPH_MINIO_ACCESS_KEY="$EPHEMERAL_READ_ONLY_ACCESS_KEY" \
ASSETGRAPH_MINIO_SECRET_KEY="$EPHEMERAL_READ_ONLY_SECRET_KEY" \
  uv run --project backend python scripts/measure_capacity_baseline.py \
  --expected-database assetgraph \
  --classification operational_read_only_snapshot \
  --source-snapshot-ref SNAPSHOT-... \
  --window-days 30 \
  --capacity-input /approved/capacity-baseline-input.v1.json \
  --object-store-endpoint minio.internal:9000 \
  --object-store-bucket assetgraph \
  --output /approved/evidence/capacity-baseline-YYYYMMDD.json
```

Acceptance requires every `qualification_gates` value and
`qualifies_for_chk_0110` to be `true`. The example JSON intentionally contains
null/pending values and is rejected; it must never be edited into apparent
approval evidence inside the repository.

Until these steps complete, Phase 0 cannot exit and later production workload
budgets remain `blocked_unbudgeted`.
