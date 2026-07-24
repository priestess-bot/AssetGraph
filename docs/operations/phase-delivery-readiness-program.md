# Phase Delivery Readiness Program

> Date: 2026-07-23
> Authority: `docs/plans/2026-07-23-live-content-production-operations-implementation-checklist.md`
> Scheduling rule: every milestone is a 2-6 week acceptance slice only after its
> named owner roles, dependency evidence and numeric capacity/cost caps exist.
> This document defines scope and gates, not calendar dates or staffing promises.

## Operating Rule

1. The phase sequence is strictly `0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8`.
2. A later phase may run an isolated spike, but cannot enable production or claim
   milestone acceptance before the preceding phase exits.
3. At phase kickoff, replace every `blocked_unbudgeted` value for that phase with
   a measured baseline, numeric cap, owner, approval reference and measurement
   window. Until then the phase is not ready to start.
4. Each milestone is independently accepted in 2-6 weeks. Scope is reduced when
   it cannot fit; the timebox is not silently extended and partial output is not
   marked complete.
5. Every accepted check immediately updates its checklist checkbox, execution
   log and immutable or content-addressed evidence. A milestone is only a view
   over those checks and cannot override them.

## Dependency Graph

```text
P0 contracts/control/compatibility
  -> P1 content-to-Maitu-draft vertical path
    -> P2 assets/constraints/external templates
      -> P3 rendered-video branch
        -> P4 release/exposure/manual attribution
          -> P5 automated collection/trustworthy estimates
            -> P6 randomized experiments/role strategies
              -> P7 graph/scheduling/high-risk production operations
                -> P8 system-wide verification/reflection/acceptance
```

Within every phase, milestone `A -> B -> C` is the default dependency. A later
milestone can begin only when the preceding acceptance objects and revisions are
fixed. Cross-cutting security, privacy, rights, evidence and rollback gates apply
to every milestone, not only Phase 7 or Phase 8.

## Milestone Register

| Phase / milestone | 2-6 week acceptance slice | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| `P0-A` contracts and control plane | Domain identities/revisions, time semantics, Artifact/Run/Workflow/HumanTask, policy, release/delivery/exposure, metric/data and governance contracts. | Current repository baseline | `CHK-0101` through `CHK-0245` contract, migration, property and integration evidence. |
| `P0-B` compatibility and Console | Legacy projections, stable errors, shared Console, entity revision inspection, drafts/commands and route migration. | `P0-A` | `CHK-0261` through `CHK-0268`, screenshots and compatibility reports. |
| `P0-C` operational exit | Measured capacity, provider migration, real-copy migration rehearsal, old-mainline report, PITR/object restore and human acceptance archive. | `P0-B` | All `CHK-0260`, `CHK-0294` through `CHK-0296` evidence and Phase 0 archive. |
| `P1-A` confirmed content root | ContentProject input, facts, DesignBrief review, StoryBrief, Script/Block, ProgramSegment and ShotList fixed revisions. | Phase 0 exit | `CHK-1100` through `CHK-1144`; content lineage and fact-safety report. |
| `P1-B` live-room projection | live_room variant, input snapshot, MaituSceneBlueprint/Layer and deterministic BuildPlan with explicit Shot projection. | `P1-A` | `CHK-1160` through `CHK-1189`; plan diff and source coverage. |
| `P1-C` safe draft release | Gates, authoritative preflight, HumanTask/authorization, draft write/readback/reconcile and immutable draft ReleaseManifest. | `P1-B` | `CHK-1200` through `CHK-1295`; isolated-room E2E and 100% evidence completeness. |
| `P2-A` asset truth and rights | Three-axis asset identity, AssetVersion/Rendition, inventory lifecycle, RightsGrant and revocation impact. | Phase 1 exit | `CHK-2100` through `CHK-2133`; migration quality and rights tests. |
| `P2-B` constraints and selection | Constraint profiles/regions/relations, solver contract, explainable ranking, groups, packages and AssetGap. | `P2-A` | `CHK-2140` through `CHK-2237`; infeasibility diagnostics and hard-whitelist tests. |
| `P2-C` external content templates | Single-source-room capture/cleaning, content-strategy.v2, publication and primary/secondary template contribution into production. | `P2-B` | `CHK-2240` through `CHK-2397`; provenance, de-facting and reference-only gates. |
| `P3-A` deterministic edit model | rendered_video variant, RationalTime/TimeRange and OTIO-compatible ProductionTimeline from fixed Shots. | Phase 2 exit | `CHK-3100` through `CHK-3134`; round-trip and branch-isolation tests. |
| `P3-B` render and QC | Content-addressed stages, RenderManifest, TTS/subtitle/FFmpeg execution and video/audio quality gates. | `P3-A` | `CHK-3140` through `CHK-3197`; deterministic manifests and failed-QC isolation. |
| `P3-C` video release and delivery | Signed provenance/rights sidecars, rendered-video ReleaseManifest, delivery/readback/reconcile and production UI. | `P3-B` | `CHK-3200` through `CHK-3290`; full rendered-video journey. |
| `P4-A` release and exposure operations | Release workspace, LiveSession, actual ContentExposureEvent, immutable content timeline and exposure correction. | Phase 3 exit | `CHK-4100` through `CHK-4134`; release/exposure non-equivalence tests. |
| `P4-B` governed metrics and manual attribution | Event ingestion, metric catalog/data contracts, watermark/quarantine and versioned descriptive/associational attribution. | `P4-A` | `CHK-4140` through `CHK-4294`; point-in-time and insufficient-data cases. |
| `P5-A` automated trustworthy inputs | Source adapters, backfill/delete, data-quality incidents, FeatureSnapshot and DecisionLog point-in-time correctness. | Phase 4 exit | `CHK-5100` through `CHK-5134`; source quality and leakage tests. |
| `P5-B` estimates and controlled reproduction | Effect eligibility, associational/quasi-experimental estimates, sensitivity analysis and capped ranking influence. | `P5-A` | `CHK-5140` through `CHK-5295`; non-promotion and rollback evidence. |
| `P6-A` role strategies and experiment design | Role/RoleStrategy revisions, treatment assignment, namespaces, propensity, SRM and exposure reconciliation. | Phase 5 exit | `CHK-6100` through `CHK-6135`; pre-registration and collision tests. |
| `P6-B` evaluation and staged rollout | RoleEvaluation across quality/latency/cost/safety/effect and shadow/advice/controlled-traffic promotion. | `P6-A` | `CHK-6140` through `CHK-6290`; guardrail rollback and evidence-grade enforcement. |
| `P7-A` knowledge and graph projection | Approved fact/lineage ontology, PostgreSQL fact source, graph/vector/search projections, watermarks and full rebuild. | Phase 6 exit | `CHK-7100` through `CHK-7137`; adoption-threshold and rebuild evidence. |
| `P7-B` scheduling and high-risk authorization | BroadcastSchedule, conflict checks, GoLiveAuthorization review boundary and emergency stop without implicit go-live paths. | `P7-A` | `CHK-7140` through `CHK-7175`; independent security review and drills. |
| `P7-C` production operations | Governance center, privacy/deletion/rights/supply chain, SLO/cost/DR, stable product routes and old-route retirement. | `P7-B` | `CHK-7180` through `CHK-7295`; operational acceptance and recovery results. |
| `P8-A` traceability and test audit | Requirement matrix, static/unit/property/contract coverage and migration/data-quality verification. | Phase 7 exit | `CHK-8100` through `CHK-8145`; no orphan requirements or hidden skips. |
| `P8-B` integrated journeys and abuse testing | Service/worker integration, browser E2E, security/privacy/abuse and representative UAT journeys. | `P8-A` | `CHK-8160` through `CHK-8247`; incident and counterexample evidence. |
| `P8-C` resilience, reflection and final audit | Performance/chaos/restore/reproducibility, design reflection, residual-risk disposition and final archive. | `P8-B` | `CHK-8220` through `CHK-8291`; signed acceptance package. |

## Capacity And Cost Budget Gate

`blocked_unbudgeted` is a blocking state, not a zero estimate. The kickoff record
for each phase must contain current/p50/peak values, 12-month forecast, peak
factor, hard concurrency and daily/monthly caps, unit cost source, warning and
stop thresholds, degradation order, kill switch, measurement query, owner and
approval reference.

| Phase | Required capacity units | Required cost units | Current budget state |
| --- | --- | --- | --- |
| 0 | asset/event/artifact/workflow counts, API/queue latency, migration lock/time, backup/restore throughput | CI/local compute, database/object storage, observability | Local validation only: paid model calls and production external writes capped at `0`; operational workload budget is `blocked_unbudgeted` pending `CHK-0110`. |
| 1 | content runs/day, concurrent generation, BuildPlan operations/run, Browser-use account/room concurrency | generation tokens, Browser-use minutes, Maitu calls, evidence bytes | `blocked_unbudgeted`; Phase 1 production enablement forbidden. |
| 2 | asset versions/renditions, solver variables/constraints/time, capture hours/day, ASR/OCR/vision jobs | storage/egress, ASR/OCR/vision, solver compute | `blocked_unbudgeted`; external processors require approved terms and caps. |
| 3 | renders/day, concurrent CPU/GPU renders, timeline/artifact growth, delivery bandwidth | TTS, CPU/GPU seconds, storage/egress, delivery calls | `blocked_unbudgeted`. |
| 4 | sessions/exposures/events per second, watermark lag, attribution runs and metric-query load | event storage/compute, analyst review, attribution compute | `blocked_unbudgeted`. |
| 5 | adapter event peaks/backfills, feature snapshots, estimate runs and reproduction candidates | source APIs, feature storage, statistical compute, controlled regeneration | `blocked_unbudgeted`. |
| 6 | concurrent experiments, assignments/events, strategy variants and evaluation windows | exploration traffic, model strategies, analyst/security review | `blocked_unbudgeted`; exploration must have a numeric risk budget. |
| 7 | graph nodes/edges/queries, schedules, authorization QPS, governance/delete jobs and restore volume | graph/search infrastructure, paging/on-call, backup/replication, high-risk drills | `blocked_unbudgeted`; no go-live capability before independent approval. |
| 8 | full-suite duration/concurrency, load level, fault-injection volume and retained evidence | test environments, load generation, restore drills and acceptance labor | `blocked_unbudgeted`; final acceptance cannot waive measured SLO/cost results. |

## Risk Register

| Phase | Primary risk | Preventive gate | Trigger / response |
| --- | --- | --- | --- |
| 0 | New contracts imply facts or permissions absent in legacy data. | Read-only compatibility projections and explicit uncertainty vocabulary. | Any fabricated provenance/permission blocks exit and requires forward fix. |
| 1 | Generated content or browser actions bypass fact and target identity. | Fixed facts, authoritative preflight, scoped single-use authorization and readback. | Any target/hash drift stops execution and opens reconcile. |
| 2 | File type or visual inference is treated as role, right or executable layout. | Three-axis asset model, RightsGrant and reference-only template gate. | Unknown classification/right creates HumanTask or AssetGap; never auto-promote. |
| 3 | Rounded time, mutable files or failed QC produce unreproducible releases. | Rational time, content addressing, fixed RenderManifest and branch-specific QC. | Mismatch invalidates candidate while preserving diagnostic artifact. |
| 4 | Delivery/recording inference is presented as actual exposure or causality. | Explicit exposure events, correction history and evidence levels. | Missing identity/time/metric contract downgrades or blocks attribution. |
| 5 | Leakage, drift or low-quality associations drive automatic feedback loops. | Point-in-time snapshots, eligibility policy, sensitivity checks and capped influence. | Quality/drift failure revokes estimate and dependent decisions become review-required. |
| 6 | Experiments collide, harm guardrails or over-credit one role. | Namespace, propensity/SRM, pre-registration, multidimensional evaluation and rollback. | Guardrail breach stops assignment and preserves exposure evidence. |
| 7 | Derived graph becomes truth or high-risk authorization becomes ambient permission. | PostgreSQL fact source, rebuild tests, independent GoLiveAuthorization and emergency stop. | Projection lag hides graph results; auth/site/window drift fails closed. |
| 8 | Green totals hide skips, flaky journeys or untested operational assumptions. | Requirement-to-test matrix, skip audit, counterexamples, chaos and human UAT. | Any orphan/high-risk residual prevents final sign-off. |

## Kickoff Record Template

```text
phase / milestone:
window: 2-6 weeks (calendar dates set only after approval)
product / engineering / data / security / design owners:
predecessor acceptance refs:
included check_ids:
excluded scope and follow-up check_ids:
measured baseline and window:
12-month forecast and peak factor:
capacity caps / warning / stop thresholds:
unit costs / daily cap / monthly cap:
degradation order / kill switches:
rollback and reconcile exercise:
acceptance artifacts and approvers:
```

No milestone may replace unknown fields with aspirational numbers. An incomplete
kickoff record keeps that milestone pending even when implementation code exists.
