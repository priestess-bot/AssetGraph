# ADR-0002: Defer Temporal Until Measured Thresholds

- Status: accepted
- Date: 2026-07-23
- Owners: engineering (`coderdailyone`); operations approval remains part of Phase 0 exit
- Checklist: `CHK-0170`
- Supersedes: none

## Context

The control plane now supports durable DAG steps, PostgreSQL leases and fencing,
timeouts, cancellation, HumanTask wait/resume, and the external-effect
`prepare -> authorize -> commit -> read-back/reconcile` protocol. The decision is
whether to add Temporal before production capacity evidence exists.

The 2026-07-23 validation database contained 61 WorkflowRuns across three
workflow types, 81 steps, 20 dependency edges, 17 HumanTasks and 23 external
effects. The largest observed run had two steps, dependency depth one, and the
oldest run sample was about 7,220 seconds. This is engineering-validation data,
not a production capacity claim. No measured cross-day timer/signal workload or
database queue bottleneck exists yet.

## Decision

Do not introduce Temporal in Phase 0. PostgreSQL remains the initial execution
engine behind engine-neutral WorkflowRun, StepRun, HumanTask and external-effect
contracts.

Re-evaluate with a new ADR and a representative benchmark when any trigger is
observed:

1. More than 50,000 accepted runs/day or 5,000 concurrently non-terminal runs
   for seven consecutive days.
2. A representative workflow exceeds 25 steps, dependency depth 10, or needs
   durable timers/signals beyond 24 hours across service deployments.
3. At the approved two-times peak workload, step claim p95 exceeds 100 ms,
   accepted-task loss is non-zero, or control-plane queries consume more than
   20% of primary database CPU for 30 minutes despite indexed query tuning.
4. Two or more severity-one/two incidents in a quarter are primarily caused by
   home-grown timer, retry, recovery, or worker-version coordination behavior.
5. Cross-region active execution, long-lived versioned worker compatibility, or
   operational replay requirements cannot meet their SLO with the current
   contract and PostgreSQL implementation.

Crossing a trigger starts a bake-off; it does not automatically select Temporal.
The benchmark must compare failure recovery, operator load, p95 claim/signal
latency, storage growth, cost and exit complexity on the same workload.

## Alternatives

- Introducing Temporal now was rejected because the measured workflow graph is
  small and current failures are contract/domain problems rather than durable
  timer limitations.
- Permanently standardizing on PostgreSQL was rejected because future cross-day
  orchestration and worker-version complexity are not yet known.
- Letting individual domains choose their own workflow engine was rejected
  because it would fragment run identity, authorization and lineage.

## Consequences

Engineering continues to own lease sweeps, retention, queue indexes, timeout and
reconciliation behavior. Phase 0 capacity work must measure these costs. No
Temporal SDK type, workflow ID or activity payload may enter domain APIs,
manifests or lineage.

The current engine fails closed for unknown external outcomes. A future engine
migration cannot reinterpret a successful WorkflowRun as delivery or exposure.

## Evolution

Metrics for active runs, claim latency, lease recovery, HumanTask age, external
reconciliation and database cost must be retained. If a trigger fires, the new
ADR must preserve domain `run_code`, step idempotency keys, authorization target
and hash binding, ArtifactRef, RunManifest and lineage identifiers.

Migration uses dual-read comparison followed by controlled queue draining; it
does not move already-committing external effects between engines. Rollback uses
the same domain contracts and resumes from persisted step/effect state after
authoritative reconciliation.

## Evidence

- PostgreSQL measurements executed on 2026-07-23 validation data:
  `61 runs / 3 workflow types / 81 steps / 20 dependency edges / max 2 steps / depth 1 / 17 HumanTasks / 23 effects`.
- `backend/tests/test_control_plane_postgres.py`
- `backend/tests/test_control_plane_external_effects_postgres.py`
- `backend/tests/test_closed_loop_properties.py`
- `docs/evidence/phase-0-foundation-validation-2026-07-23.md`
