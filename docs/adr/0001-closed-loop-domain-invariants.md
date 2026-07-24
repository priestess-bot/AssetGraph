# ADR-0001: Closed-loop Domain Invariants

- Status: accepted
- Date: 2026-07-23
- Owners: product (design authority), engineering (`coderdailyone`), data/security approval pending Phase 0 exit
- Checklist: `CHK-0102`, `CHK-0104` through `CHK-0108`, `CHK-0170`
- Supersedes: none

## Context

The current repository has working Maitu, capture and video pipelines, but their
run, scene, artifact and completion meanings differ. Building more pages on these
meanings would make release, exposure and attribution ambiguous.

## Decision

1. `ContentProject` is the cross-carrier aggregate root. Live-room and rendered-
   video state belong to independent ProductionVariant revisions.
2. Confirmed, published, approved and released revisions are immutable. Changes
   create a new revision and propagate `stale` to derived objects.
3. ProgramSegment, Shot, MaituSceneBlueprint and TimelineSegment remain distinct
   types joined by explicit projection links.
4. Artifact, WorkflowRun, Release, DeliveryAttempt and ContentExposureEvent are
   different facts. Success in one state machine cannot advance another by
   implication.
5. Edit frames, media PTS, session milliseconds, event time and processing time
   remain separate and use explicit versioned mappings.
6. External side effects require allowlisted operations, current target state and
   a short-lived, single-use, target/capability/hash-bound authorization checked
   again at commit time. Unknown results reconcile before retry.
7. Evidence levels are descriptive, associational, quasi-experimental and
   randomized. Humans may approve an estimate but cannot manually raise its
   evidence level.
8. PostgreSQL and immutable artifacts are authoritative. Vector and graph stores
   are rebuildable projections.
9. Infrastructure adapters may change without changing public domain contracts.
   PostgreSQL leases remain the initial workflow implementation; Temporal is
   reconsidered only after measured complexity exceeds the design threshold.

## Alternatives

- Extending WorkbenchRun as the root was rejected because it couples shared
  content to one live-room carrier.
- Treating workflow completion as publication was rejected because it destroys
  approval, delivery and exposure provenance.
- Introducing Temporal/Neo4j before a measured need was rejected because it adds
  operational state without fixing domain ambiguity.

## Consequences

Legacy APIs remain compatibility projections. Migrations must label uncertainty
instead of inferring provenance. More explicit objects and transitions are
required, but each can be tested, reconstructed and audited independently.

## Evolution

All schema changes are additive. A conflicting future decision requires a new
ADR, migration and historical interpretation. Kill switches preserve fail-closed
behavior during rollback; immutable records are superseded, never rewritten.

## Evidence

- `docs/architecture/phase-0-baseline.md`
- `docs/plans/2026-07-22-live-content-production-operations-closed-loop-design.md`
- Phase 0 contract and migration tests

