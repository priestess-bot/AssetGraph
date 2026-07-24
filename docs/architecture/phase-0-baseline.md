# AssetGraph Phase 0 Baseline

> Baseline date: 2026-07-23
> Baseline commit: `d946631`
> Checklist owner: `coderdailyone`
> Authority: `docs/plans/2026-07-22-live-content-production-operations-closed-loop-design.md`

This document records the implementation state before the closed-loop domain
model is introduced. It is descriptive evidence, not a source of new business
semantics. When the legacy data does not prove a fact, migrations must preserve
that uncertainty.

## Capability inventory

| Capability | Current implementation | Decision | Target boundary |
| --- | --- | --- | --- |
| FastAPI API | One backend with route modules and PostgreSQL repositories | extend | Stable domain APIs under `/api`; legacy endpoints remain compatibility projections until their exit gates pass. |
| PostgreSQL | Migrations `001` through `026`; business state and execution receipts | reuse | Authoritative system of record with append-only migrations and immutable revisions. |
| `/maitu/` | React workbench for facts, inventory, plans, preflight and draft execution | migrate | Incrementally move to `/content/projects`, `/production/live-rooms`, `/assets/library` and governance routes. |
| `/live-research/` | React workbench for sources, capture sessions and template review | migrate | Move to `/research/live-sources` after feature parity and deep-link audit. |
| Browser-use worker | Observe, preflight, leased execution, checkpoint, reconcile and readback | extend | Consume typed BuildPlan operations and commit-time ExecutionAuthorization only. |
| Live-research worker | StreamCap/douyinLive adapters, capture, timeline, retention and analysis | extend | Produce versioned CaptureSession artifacts and `content-strategy.v2` inputs. |
| Video worker | Kokoro TTS, subtitles, FFmpeg render and persisted stage output | migrate | Consume ProductionTimeline and emit content-addressed render/QC artifacts. |
| Qwen3 service | Local embedding and reranking HTTP service | reuse | Provider adapter behind retrieval contracts; never an authoritative fact source. |
| MinIO | Object storage service and upload helpers | extend | Content-addressed ArtifactRef storage with checksum, classification and retention. |
| Milvus | Locally deployable vector service | retain as optional projection | Rebuild from PostgreSQL/outbox; never write business truth back. |
| Neo4j | Locally deployable graph service with no stable production projection | defer | Adopt only after the section 28.2 query and rebuild threshold is met. |
| Existing video pipeline | Topic-oriented `VideoProductionJob` with persisted stages | migrate | Compatibility execution aggregate under a rendered-video ProductionVariant. |
| Maitu authority API | Fail-closed authoritative room and material verification | reuse | Hard dependency for target identity and readback; unavailable means blocked. |

## Legacy object mapping

| Legacy object | Current source of truth | New object/projection | Migration quality | Owner | Exit condition |
| --- | --- | --- | --- | --- | --- |
| `maitu_workbench_runs` | PostgreSQL | live-room `ProductionVariantRevision` compatibility projection | topic, facts and inventory are usable; no independent ContentProject revision | engineering | All active runs have stable project/variant links and old reads are audited. |
| Workbench plan revision | PostgreSQL | BuildPlan/Workflow output | strong input/model fingerprints; old provider-specific fields remain descriptive | engineering | New plans use provider-neutral strategy/model references. |
| Product fact-card version | PostgreSQL | `FactCardRevision` | approved status and checksum are reusable; scope/validity require extension | product/data | Production confirmation revalidates approval, validity and scope. |
| `VideoProductionJob` | PostgreSQL | rendered-video ProductionVariant execution projection | stage/artifact evidence reusable; StoryBrief and Shot provenance is incomplete | engineering | New jobs bind fixed content/timeline revisions. |
| Live room blueprint/scene/layer | PostgreSQL JSON and indexed components | MaituSceneBlueprint/LayerBlueprint | geometry and Maitu identity may be reusable; no Shot may be inferred | engineering | Explicit ShotProjectionLink exists for newly generated objects. |
| `layout-hypothesis.v1` | PostgreSQL | read-only external visual reference | approximate and reference-only by contract | research | Remains readable; never converted into executable layout identity. |
| Live capture/template revisions | PostgreSQL | CaptureSession/content-strategy draft | media provenance is usable; older templates are not `content-strategy.v2` | research | New publication contract and single-source-room gate are active. |
| JD metric capture/sample | PostgreSQL | quarantined source event adapter | event-time, definition and exposure identity are not universally proven | data | Versioned DataContract maps qualified rows; other rows stay descriptive-only. |
| `live_sessions` | PostgreSQL | LiveSession compatibility projection | scheduled/actual time may be present; exact release/exposure generally absent | data | New sessions bind ReleaseManifest and actual ContentExposureEvent. |
| Historical delivery fields | Multiple execution/result tables | DeliveryAttempt or legacy delivery projection | exact target/artifact/readback varies | engineering/data | Only proven deliveries become DeliveryAttempt; all others remain unknown. |

## Legacy uncertainty vocabulary

- `unknown`: the value is absent or cannot be established from retained evidence.
- `legacy_import`: a legacy source supplied the value, but it was not produced by the new contract.
- `legacy_delivery_unknown`: an old workflow may have completed, but exact artifact, target, approval or readback is not provable.
- `descriptive_only`: data may be displayed or summarized but cannot support causal claims or automated production decisions.

These labels are one-way classifications. No migration may infer Shot,
ReleaseManifest, DeliveryAttempt, ContentExposureEvent, approval, rights or an
execution capability merely because nearby legacy data exists.

## Naming and identity rules

- `ProgramSegment` is a semantic program interval; `Shot` is a director intent;
  `MaituSceneBlueprint` is a live-room projection; `TimelineSegment` is an edit
  interval. The legacy word `Scene` is never accepted as proof of another type.
- Logical entities have a stable public code and immutable integer revision.
  A reference always contains both; `latest` is forbidden in manifests.
- Schemas use a stable lowercase identifier plus a major version, for example
  `run-manifest.v1`. Breaking meaning requires a new major contract.
- Command idempotency keys are scoped to command type, principal and target.
  Event IDs are globally unique within their source adapter.
- Fingerprints use canonical UTF-8 JSON with sorted keys and SHA-256. Timestamps
  and mutable transport metadata are excluded unless the contract says they are
  semantically relevant.
- Audit timestamps are timezone-aware UTC. Source event time and processing time
  remain separate and are never silently substituted.

## Time domains

| Domain | Representation | Boundary rule |
| --- | --- | --- |
| Edit time | Rational frame value and rate | OTIO-compatible half-open TimeRange; never replace with rounded milliseconds. |
| Media time | Stream PTS/time base | Preserve original time base and discontinuities; map explicitly to edit/session time. |
| Session time | Integer milliseconds | Half-open `[start_ms,end_ms)` relative to CaptureSession/LiveSession origin. |
| Event time | UTC instant supplied or derived by a versioned adapter | Store derivation and confidence; use for windows and attribution. |
| Processing time | Server UTC instant | Used for watermarks, latency and replay, never as a silent event-time fallback. |

## Current capacity evidence

The repository host has 64 logical CPUs and 270,132,334,592 bytes of physical
memory. At the 2026-07-23 remeasurement, the root filesystem had 83,467,808,768
bytes free and `/DATA` had 1,400,455,979,008 bytes free;
`/DATA/Downloads/AssetGraph` occupied 20,008,446,765 bytes. The configured
operational PostgreSQL endpoint was not reachable, so row counts, daily
ingestion, concurrency, queue throughput, forecasts and unit costs remain
explicitly unknown. Local directory and process observations plus the exact
completion procedure are recorded in
`docs/operations/capacity-baseline-measurement-2026-07-23.md`. `CHK-0110`
remains open; these host figures and isolated test-database fixtures are not
production capacity targets.

## Compatibility policy

- Existing migrations and receipts are immutable. New schema is additive.
- Legacy geometry and `duplicate_group` retain their old descriptive meaning.
- Compatibility projections declare their source of truth and never manufacture
  missing provenance.
- Old routes remain until functional equivalence, deep links, audit and an owner-
  approved retirement checklist all pass.
