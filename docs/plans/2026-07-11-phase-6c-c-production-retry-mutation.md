# Phase 6C-C Production Retry Mutation Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Safely connect the production retry queue to a draft-only, single-target Maitu layer replacement with authoritative readback, while preserving lease fencing, operation checkpoints, manual reconciliation, and the permanent go-live prohibition.

**Architecture:** AssetGraph remains the authority for immutable mutation intent. The Backend emits a complete canonical operation containing exact room/clip/layer/material identity plus before/after predicates; its SHA-256 fingerprint covers the complete intent. The exact built-in Worker/session may execute at most one draft mutation after checkpoint `begin=execute`, then must prove the post-state by authoritative readback before checkpoint completion. Ambiguity or uncertain completion always enters reconciliation rather than replay.

**Tech Stack:** FastAPI, psycopg/PostgreSQL, Pydantic, pytest, Browser-use CLI, Maitu page-context API, existing lease/checkpoint/reconciliation protocol.

---

## Non-negotiable safety constraints

- No automatic or generic go-live path. `正式开播` remains prohibited.
- No guessed room, clip, layer, material, or save semantics.
- No mutation on active-live or unknown-live state.
- No browser mutation when the feature flag is disabled or the target room is not allowlisted.
- No production queue mutation from dry-run.
- No external exactly-once claim. Uncertain external effects enter `reconcile_required`.
- `retry_asset_upload_and_replace`, generic mutation, automatic login mutation, and digital-human creation remain blocked in the first slice.
- Evidence and error responses must not persist or reflect credentials, cookies, claim tokens, or provider tokens.

---

## Task 1 — Freeze the canonical retry mutation contract

**Objective:** Make `retry_replace_layer_asset` executable only when every authoritative target and material field is present; ensure every mutation-relevant field changes the operation fingerprint.

**Files:**
- Modify: `backend/app/repositories/maitu.py`
- Modify: `backend/app/schemas/maitu.py` if a dedicated response model is needed
- Modify: `backend/tests/test_maitu_retry_lease_repository.py`
- Modify: `backend/tests/test_maitu_slot_routes.py`
- Modify: `backend/tests/test_maitu_retry_lease_postgres.py` if persisted intent is introduced
- Create/Modify: next migration only if a canonical intent snapshot must be persisted

**Canonical intent fields:**
- `target_live_room_id`
- `target_clip_id`
- `target_scene_name`
- `slot_code`
- exact target layer identity (`target_layer_id` preferred; unique layer name only as an explicit precondition)
- `asset_code`
- verified `maitu_material_id`
- verified `source_material_type`
- `replacement_policy`
- `expected_before_state`
- `desired_after_state`
- `primary_operation_type`
- `operation_key`

**TDD sequence:**
1. Add a failing test proving missing room/clip/layer/material context makes the operation `blocked` with a fixed reason.
2. Run the exact test and observe RED for current `status=ready` behavior.
3. Add the minimal builder validation to make it GREEN.
4. Add one failing test per canonical field proving changing that field changes `operation_fingerprint`.
5. Add a route test proving the complete secret-free canonical intent is returned unchanged.
6. Add a checkpoint test proving stale fingerprints conflict after any authoritative intent change.
7. Run repository and route subsets, then Backend full suite.

**Acceptance:** No `retry_replace_layer_asset` operation is `ready` without exact draft target and verified material binding; fingerprint sensitivity covers every canonical field.

### Task 1 implemented contract (2026-07-11)

- Contract version: `maitu-retry-mutation-v1`; operation responses use `extra="forbid"`.
- Migration `019_maitu_retry_mutation_intent.sql` stores room/clip/layer/before-state authoring fields, material-binding verification metadata, and immutable operation snapshots in `maitu_retry_operation_intents`.
- Retry-task creation freezes primary/save operations in the same transaction. A database trigger rejects snapshot `UPDATE` and `DELETE`; runtime reads snapshot-first.
- Legacy tasks without a snapshot stay visible but are always blocked with `missing_immutable_intent_snapshot`.
- `retry_replace_layer_asset` requires a present Maitu project, matching plan/slot room, a present target scene (and matching plan/slot scene when both exist), positive clip/layer IDs, finite exact canonical before-state, `keep_layout`, three-way Asset identity, Asset status `stored`, Slot asset-type compatibility, `IMG ↔ image` / `VID ↔ video`, and a `maitu_readback` binding scoped to `live_room:<target_live_room_id>`.
- Ordinary material-binding PATCH invalidates prior verification metadata. Binding mutation locks every related retry-task row before checking active leases, serializing pending→claim races; an active lease returns fixed 409.
- Canonical response includes a complete `authoritative_intent`, target project/room/clip/scene/layer, before/after state, Asset/material identity, binding verification metadata, readiness, and fixed blocked reasons. `source_material_url` is not execution identity and is not sent to the Worker.
- Fingerprints cover contract/task/operation identity, project, plan/slot room and scene, clip/layer, before/after state, task/selected/binding Asset identity, Asset status/type allowlist, material ID/type, binding source/time/scope, policy, Worker instruction, and operation key/type.
- Every snapshot insert and read validates the exact authoritative key set, recomputes the fingerprint, checks redundant columns/top-level execution fields, and rejects secrets. Operation-plan top-level project/scene derives from the validated snapshot, never mutable plan/slot state.
- `retry_save_project` remains blocked with `save_project_not_implemented` until Task 3 proves persistence semantics.
- Checkpoint begin/complete and successful execution-result admission re-read the immutable snapshot and reject non-ready operations. Persisted worker completion and execution receipts are independently re-fingerprinted; receipt payloads bind a one-way claim-token hash without storing the token.
- Snapshot, checkpoint, execution-result, and client-controlled `claimed_by` admission recursively reject credentials, provider tokens, claim-token forms, and the configured reconciliation operator secret. Retry conflict APIs return fixed 409 details without reflecting internal exceptions.

---

## Task 2 — Implement authoritative single-target replacement

**Objective:** Implement `BrowserUseCliSession.replace_layer_asset()` for one draft layer, with pre-read, one mutation maximum, and post-read verification.

**Files:**
- Modify: `workers/browser-use/src/browser_use_worker/browser_cli_session.py`
- Modify: `workers/browser-use/src/browser_use_worker/maitu_executor.py`
- Modify: `workers/browser-use/tests/test_browser_cli_session.py`
- Modify: `workers/browser-use/tests/test_phase_6c_checkpoint.py`
- Modify: `workers/browser-use/tests/test_runner.py` if trust snapshots change

**TDD sequence:**
1. RED: reject wrong origin, missing auth, active-live, unknown-live, room mismatch, clip mismatch, zero/multiple matching layers, missing/wrong-type material, pre-state drift, and malformed operation.
2. RED: prove no mutation command occurs before the final execution guard.
3. GREEN: authoritative room/clip/layer/material pre-read.
4. RED: prove at most one mutation call occurs.
5. GREEN: perform the exact target update using the verified Maitu material binding while preserving geometry/layout.
6. RED: reject missing, ambiguous, malformed, or mismatching post-read.
7. GREEN: return minimal secret-free `verified=true` evidence containing exact room/clip/layer/material identity and before/after summaries.
8. Verify lease loss between side effects prevents additional mutation; response uncertainty remains unresolved and flows to reconciliation.

**Acceptance:** A fresh operation either performs one exact draft replacement and proves it, completes as an authoritative no-op when the desired state is already present under a fresh attempt, or fails before/after mutation without replay.

---

## Task 3 — Implement `save_project` as a persistence-proof barrier

**Objective:** Complete `save_project` only when persisted post-state can be authoritatively re-read; never treat HTTP 200/toast/button state alone as proof.

**Files:**
- Modify: `workers/browser-use/src/browser_use_worker/browser_cli_session.py`
- Modify: `workers/browser-use/src/browser_use_worker/maitu_executor.py`
- Modify: corresponding Worker tests and protocol documentation

**TDD sequence:**
1. RED: no authoritative persisted target state -> fail/manual reconciliation.
2. RED: active-live/unknown-live or room/clip drift -> zero save mutation.
3. Implement readback-only proof when Maitu mutation APIs already persist the target state.
4. Only if real inspection proves a separate draft-save action is required, add one exact save action followed by authoritative re-read.
5. RED: uncertain save response or failed readback must not complete the checkpoint.
6. Verify `正式开播` never appears in generated commands or clicked controls.

**Acceptance:** `save_project` is a proof barrier, not a blind click; inability to prove persistence enters reconciliation.

---

## Task 4 — Wire the guarded production runtime

**Objective:** Connect the exact built-in executor/session to an explicit canary Worker mode without opening continuous mutation by default.

**Files:**
- Modify: `workers/browser-use/src/browser_use_worker/config.py`
- Modify: `workers/browser-use/src/browser_use_worker/__main__.py`
- Modify: `workers/browser-use/src/browser_use_worker/runner.py`
- Modify: Worker CLI/config/runner tests and README

**Required gates:**
- `BROWSER_USE_ENABLE_RETRY_MUTATION=false` by default
- draft-room allowlist
- one-task canary mode such as `--retry-worker-once`
- exact `MaituBrowserUseExecutor` + exact `BrowserUseCliSession`
- incompatible CLI modes rejected before client/session construction
- feature disabled rejects before claim
- allowlist mismatch rejects before browser mutation
- dry-run remains claim-free

**Acceptance:** Production mutation requires explicit enablement and an allowlisted draft room; canary processes at most one task and exits; continuous mode remains unavailable until canary evidence is approved.

---

## Task 5 — Verification, real draft smoke, review, and commit

**Automated gates:**
- Worker full suite
- Backend full suite
- PostgreSQL 16 integration
- migration full apply and replay
- Ruff
- `compileall`
- `git diff --check`
- credential/token scan

**Real smoke:**
- visible/headed browser
- one dedicated draft room only
- one allowlisted task only
- before/after authoritative room/clip/layer snapshots
- reversible test material
- no save unless its semantics were proven
- no go-live action
- feature flag disabled immediately afterward
- no residual test containers, locks, or generated files

**Independent review:**
- spec compliance review first
- code/security review second
- P0/P1 must be zero; report `PASS`

**Commit:**
- `feat: wire verified retry mutations [verified]`

---

## Phase 6D — LiveRun orchestration (after Phase 6C-C)

Add a `LIVE-RUN-*` state machine and APIs binding BuildPlan, Maitu room, frontend execution, JD metric session, and scene schedule. First delivery only observes/manual-started live sessions and synchronizes scene events with JD samples; it does not click go-live.

## Phase 6E — Explicit go-live authorization (last)

Add a one-time authorization bound to exact `liveRoomId`, plan, LiveRun, operation fingerprint, expiry, nonce, and operator identity. Missing, expired, reused, or drifted authorization fails closed. Go-live must remain a dedicated path, never a generic operation or PATCH side effect.
