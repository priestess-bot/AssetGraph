# Phase 0 Foundation Validation Evidence

> Date: 2026-07-23
> Owner: `coderdailyone`
> Baseline commit: `d946631`
> Evidence scope: working-tree implementation; repository commit is intentionally
> not fabricated by this report.

## Environment

- PostgreSQL 14 isolated cluster: `127.0.0.1:55433`
- Clean validation database: `assetgraph_phase0_validation_20260723_034`
- Python package environment: backend `uv` environment, Python 3.14
- Database migrations: every migration from `001` through `034` applied in
  lexical order with `ON_ERROR_STOP=1`; migrations `035` through `037` were then
  applied incrementally to the same isolated validation database.

## Baseline Regression

The pre-change repository baseline was run before implementation:

| Suite | Result |
| --- | --- |
| Backend | 482 passed, 24 skipped |
| Browser-use worker | 385 passed |
| Live-research worker | 28 passed |
| Frontend tests | 18 passed |
| Frontend Vite builds | both applications succeeded |

## Foundation Verification

Command:

```bash
ASSETGRAPH_TEST_DATABASE_URL=postgresql://assetgraph@127.0.0.1:55433/assetgraph_phase0_validation_20260723 \
uv run pytest -q \
  tests/test_closed_loop_contracts.py \
  tests/test_closed_loop_migrations.py \
  tests/test_content_core_postgres.py \
  tests/test_artifact_services.py \
  tests/test_evidence_postgres.py \
  tests/test_control_plane_postgres.py \
  tests/test_control_plane_routes.py \
  tests/test_policy_postgres.py \
  tests/test_release_postgres.py \
  tests/test_data_governance_postgres.py
```

Result: `34 passed in 2.61s`.

The verified behaviors include:

- canonical fingerprints, explicit time domains and immutable revision guards;
- optimistic revision conflicts, idempotent confirmation, cycle rejection and
  transitive stale propagation;
- content-addressed artifacts, versioned object storage contract, checksum
  verification, classification-aware access and encryption requirements;
- sealed RunManifest fingerprints/signatures/hash chain, durable lineage,
  transactional outbox retry/replay and monotonic projection checkpoints;
- durable WorkflowRun DAG, leases/fencing, HumanTask release/resume and unknown
  external side-effect reconciliation;
- persisted policy decisions, target/hash/site/capability-bound single-use
  authorization, commit-time registry/kill-switch recheck and hard-disabled
  `go_live`;
- signed immutable ReleaseManifest, validation gates, separation of duties,
  idempotent DeliveryAttempt with authoritative readback, and append-only actual
  exposure;
- versioned metric/data contracts, JSON Schema validation, late-event quarantine,
  tombstones, source-event conflict detection and evidence-level anti-promotion.

## Static Checks

All added and modified Python foundation modules and tests passed `ruff check`.
Migration parse assertions remain in `tests/test_closed_loop_migrations.py`; the
clean PostgreSQL application above is the authoritative executable check.

An additional trace/authority/provider regression batch passed 46 tests after
OpenTelemetry was connected to FastAPI, WorkflowRun/Worker claims, provider
evidence and explicit external-adapter W3C propagation.

The commit-time authorization path was then bound to the external-effect state
transition in one database transaction. A focused PostgreSQL security batch
passed 9 tests, including rollback of token consumption when the effect revision
conflicts, atomic token consumption on success, single-use replay rejection and
denial when the active policy revision changes between issuance and commit.

The carrier-independent content aggregate was completed in migration `034`.
On a new database, migrations `001` through `034` applied in lexical order and
a focused 17-test batch passed. Coverage includes StoryBrief/Script/Program/Shot
lifecycles, explicit ScriptBlock adoption and Shot source links, append-only Shot
projections, mutable-locator rejection, live-room/rendered-video branch isolation,
legacy WorkbenchRun/VideoProductionJob bindings and transitive freshness marking.

Migration `035` adds append-only hash chains for authorization lifecycle events
and external operation results, plus durable integrity alerts, check runs and a
projection consumption ledger. Regression batches passed 19 tests on the main
validation cluster and 7 tests after applying the migration over populated
foundation data. The tests exercise artifact damage, outbox replay, duplicate
and conflicting consumption, projection lag, bad signatures and chain continuity.

Migration `036` projects legacy WorkbenchRun, VideoProductionJob/stages, live
capture/analysis jobs and the Maitu retry queue into read-only WorkflowRun/StepRun
views. Repository, API deep-link and PostgreSQL tests passed on both validation
databases and verify that source tables remain authoritative and no synthetic
rows are inserted into the new workflow control plane.

ADR-0002 records the measured workflow validation complexity and defers Temporal.
It defines numeric workload, DAG, latency, incident and cross-region triggers for
a future engine bake-off while preserving domain run codes and lineage contracts.

Migration `037` installs the reviewed least-privilege role/capability baseline,
seeds Maitu reference rooms `38336` and `38995` as system-locked read-only
resources, and adds append-only protected-resource events. The registry supports
version-checked registration, update and revocation through a typed API. Separate
Preflight, PDP and Worker persistence reads share only the deterministic denial
semantics; no passed preflight substitutes for commit authorization. HTTP tests
passed 6 cases, the combined main security/service batch passed 46 cases, and a
13-case PostgreSQL batch passed after applying `037` to the validation database.

Migration `038` begins the privacy/governance control plane. Its purpose-bound
access policy requires one role grant to jointly match purpose, action and data
classification for export, decrypt, batch query, model call, graph query and
deletion. Both allow and deny outcomes are persisted as append-only decisions;
the focused access/artifact batch passed 6 tests, including prevention of
cross-role grant composition.

The same migration installs a versioned field-redaction baseline. A shared
recursive redactor removes credential-bearing keys, raw personal identifiers,
bearer/provider tokens, email addresses and phone numbers from logs, screenshot
metadata/OCR, prompts and model responses. ProviderRouter now redacts before
provider invocation and before output fingerprint/schema release, and records
the policy reference and counts without persisting raw values. The focused
redaction/provider/access batch passed 8 tests.

Six versioned retention baselines now cover raw external capture, raw personal
events, de-identified standard events, published aggregates, critical audit
evidence and intermediate artifacts. Resolution reads the active revision,
enforces contract/purpose ranges, and represents long-term retention with an
explicit null expiry rather than a fabricated date. The focused retention and
privacy regression batch passed 6 tests.

Deletion governance uses the canonical requested/validating/legal-hold/approved/
executing/verifying/completed-or-partial-failed state machine with expected
revisions and requester/approver separation. Migration `039` fixes the legacy
single-receipt constraint by making immutable receipts attempt-scoped. Legal
hold snapshots, release history, downstream processor/target completeness,
tombstones, retry backoff and escalation are all persisted. Migrations `038`
and `039` applied successfully to the independent validation database, where
the combined privacy/governance/provider batch passed 12 tests.

External processor records are versioned by purpose, accepted classification,
region, retention terms, credential owner, rotation policy, minimum-field
projection and exit plan. Every allowed or denied call writes an append-only
audit; ProviderRouter refuses external bindings without this guard. Credential
records persist only constrained Vault/Secret Manager/KMS references and support
due marking, expected-revision rotation and revocation with reference hashes in
append-only events. The main governance batch passed 15 tests and the same
processor/credential integration passed 7 tests on the validation database.

Migration `040` exposes old asset geometry and `duplicate_group` through the
read-only `legacy_asset_observations_v1` projection. Explicit semantics and
negative capability fields keep both values as imported observations rather
than constraints or user-managed groups. Source-row preservation and view
mutation rejection passed in both the main and independent validation databases.

Migrations `036` and `040` provide read-only legacy ContentProject, live-room
variant, WorkflowRun/StepRun and delivery-unknown projections through the
compatibility API. Missing revisions, provenance, release identity and readback
remain explicit instead of being inferred. Tests prove that reading these views
does not create canonical projects, variants or delivery attempts.

The legacy layout projection selects only `layout-hypothesis.v1` revisions and
fixes their semantics to `layout_fidelity=approximate`,
`buildability=reference_only` and `conversion_allowed=false`. Attempts to
mutate the projection fail, while the original revision keeps its contract
version unchanged; no implicit `content-strategy.v2` conversion exists.

The global API problem contract preserves the legacy `detail` field and adds a
stable rule code, operational state, impact, evidence references, safe next
step, retry policy and trace ID. The shared frontend parser and presentation
keep `warning`, `stale`, `insufficient_data` and `reconcile_required` distinct
from both success and ordinary failure. After upgrading legacy error assertions
and retiring test-only queue fixtures, a fresh database applied migrations
`001`-`040` and the full backend suite passed 598 tests; the frontend suite
passed 22 tests.

The unified Console is built and served from `/console/` and the stable domain
routes. It validates the existing control-plane operator credential, retains it
only in page memory, and shares authenticated global search, Workflow/HumanTask
queues, integrity/reconciliation notifications, first-level navigation and a
stack-sanitizing error boundary. API and PostgreSQL tests verify stable entity
links and operator filtering. The backend suite passed 603 tests, the frontend
suite passed 27 tests, and all Console/Maitu/live-research builds succeeded.
Playwright screenshots under `docs/evidence/screenshots/phase0-console-*` verify
desktop and mobile layouts, drawers, navigation, login and the research deep
link without horizontal overflow or header/content overlap.

The Console entity inspector adds canonical deep-link projections for assets,
content projects, live-room templates, WorkflowRuns and Releases. Its typed API
returns immutable revision snapshots, a selected structured diff, and only
explicitly verified source and downstream run/release relationships; it does not
infer lineage from mutable locators or labels. Closing the inspector removes only
the entity query parameter, preserving the surrounding workspace state. The full
backend suite passed 606 tests, the frontend suite passed 28 tests, and all three
Vite entry points built successfully. Playwright checks at 1440x1000 and 390x844
found no document/inspector horizontal overflow or top-bar overlap, and verified
that timeline, diff, source and used-by content remained visible. Screenshots are
`phase0-console-entity-desktop.png` and `phase0-console-entity-mobile.png`; the
only browser console resource error was the pre-existing absent favicon request.

Migrations `041` and `042` add mutable, non-authoritative Console drafts while
keeping every save/reopen/consume event append-only, plus durable non-secret
receipts for the fixed `confirm`, `publish`, `approve`, `reject` and `authorize`
commands. Draft saves use expected revisions, reject silent rebases and generic
sensitive fields, and retain local edits when the server reports a conflict.
Commands bind their effect to the loaded entity/draft/manifest/HumanTask revision
and use idempotency keys; content confirmation and draft consumption share one
transaction. Execution authorization derives capability, target, hash, site,
TTL and approval chain only from one approved `authorize_execution` HumanTask,
never permits `go_live`, and returns the raw token only on the first response.
Validation-error paths explicitly roll back their advisory locks and transactions.
A fresh database applied migrations `001`-`042` in order and the full backend
suite passed 614 tests. The frontend suite passed 31 tests, type checking passed,
and all three Vite entry points built. Playwright at 1440x1000 and 390x844
verified autosave to `d1`, the fixed `r1` confirmation dialog and a durable demo
receipt without document/inspector/dialog horizontal overflow or top-bar overlap.
Screenshots are `phase0-console-draft-{desktop,mobile}.png` and
`phase0-console-command-{desktop,mobile}.png`; the only failed resource remains
the non-functional absent favicon. A lost or expired raw authorization token is
intentionally unrecoverable and requires a newly approved HumanTask.

Legacy browser roots now return exact permanent redirects before their retained
static mounts: Maitu production, resources and analysis map to
`/production/live-rooms`, `/assets/library` and `/assets/library?panel=analysis`;
live-research watch, sessions, drafts and published views map to
`/research/live-sources`. Routing keys are canonicalized while repeated and blank
non-routing parameters, run/session/template identifiers and immutable template
pins are preserved. The stable Console imports the same Production, Resources,
Gemini, Watch, Sessions and Templates components, and published-template handoff
links now directly use the stable production route. This migration affects only
browser roots; `/api/maitu/*` and `/api/live-research/*` are unchanged. Full
regression passed 616 backend and 32 frontend tests, type checking and all three
builds. Browser redirects at 1440x1000 and 390x844 reached HTTP 200 destinations
without failed requests or horizontal overflow; screenshots are
`phase0-console-legacy-redirect-{desktop,mobile}.png`. Legacy static assets remain
available for cached clients until the traffic, rollback and human approval gates
in `docs/operations/legacy-frontend-retirement-checklist.md` are completed.

## Open Gates

This evidence does not claim Phase 0 exit. The following remain open:

- production workload/cost capacity measurements and SLO targets;
- provider-neutral migration of all legacy provider-specific fields;
- measured legacy-route observation and approved static-mount retirement;
- alert rules, backup/PITR/object-restore exercise and measured RPO/RTO;
- product, data, security and operations approval.

No unchecked item depending on those gates is promoted by this report.
