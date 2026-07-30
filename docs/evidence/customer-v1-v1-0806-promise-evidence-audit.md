# Customer Experience v1 Promise and Evidence Audit

Date: 2026-07-26

## Audit Rule

A route, adapter, schema, mocked test, or demo record is not evidence that an
external capability works. A customer-visible promise is retained only when it
has a repeatable local acceptance artifact or a current external canary. When
evidence is weaker, the product must say `manual_only`, `reference_only`,
`advisory_only`, optional, or unavailable.

## Result

| Customer-facing capability | Evidence | Verdict shown to customer | Audit action |
| --- | --- | --- | --- |
| Import and classify local image/video assets | Backend file-route tests, frontend interaction tests, object-storage preview | Available locally | Retained |
| Configure geometry, scale, layer and cross-asset constraints | Profile revisions, compiler tests, editable UI | Available locally | Retained |
| Build groups, packs, room selections and gap diagnostics | API/UI tests and frozen selection snapshots | Available locally | Retained |
| Upload a recording and create the analysis DAG | Upload/ffprobe/checksum tests and upload UI | Local upload is the v1 primary path | Retained |
| Automatically watch an external platform | Adapter/configuration code only; no current platform E2E canary | Optional and not yet validated | Reworded the workbench status, notice, empty state, action label and retention copy |
| Recover layout from an external flat recording | Timeline evidence exists, but layer identities cannot be recovered | `approximate` and `reference_only` | Already explicit in template review and publish projection |
| Create facts, story, script, program segments and scenes | Backend/frontend chain tests with citation and approval gates | Available for operator-approved facts | Retained; a real business sample remains an acceptance input |
| Read a Maitu room | Historical screenshots exist, but no artifact binds them to the current adapter contract fingerprint | `manual_only` until the current-account canary | Downgraded `read_room` from `verified`; historical date/evidence remains visible |
| Mutate a Maitu draft | Repository contracts and simulated readback tests only | `manual_only`; generate BuildPlan and use manual handoff | Retained fail-closed behavior; automatic draft request stays disabled |
| Create room, schedule or go live in Maitu | Explicitly outside v1 | `unsupported` | Retained; no product command can enable it |
| Produce a local vertical video | Repeatable dual-branch acceptance produced MP4, cover, subtitles and manifest | Available on the validated local toolchain | Retained |
| Import operating data and attribute content | Repeatable CSV acceptance and time-mapping/report tests | Descriptive/associational only | Retained; causal wording remains prohibited |
| Search lineage and use effect-aware recommendations | PostgreSQL projection/rebuild and recommendation tests | Local lineage; recommendations are `advisory_only` | Retained; low evidence contributes zero |
| Reproduce from an effect observation | Repeatable acceptance creates a new content chain and draft variant | Operator-confirmed draft, never automatic release | Retained |

## Code Changes Made By This Audit

- `backend/app/services/maitu_capabilities.py` now classifies `read_room` as
  `manual_only` because the historical screenshot has no current contract
  fingerprint.
- `frontend/src/live-research/LiveResearchApp.tsx` reports the proven local
  recording path instead of claiming research capture is running.
- `frontend/src/live-research/WatchPage.tsx` distinguishes saved watch targets
  from real adapter health and removes unconditional platform-start and retention
  promises.
- `frontend/src/maitu/MaituApp.tsx` states that draft capabilities open according
  to verification rather than implying that external draft execution is ready.
- `workers/browser-use/src/browser_use_worker/browser_cli_session.py` waits for
  a meaningful authenticated marker and no longer treats the transient Maitu SPA
  shell as logged in before its redirect to `/Login`.

## Verification

- `uv run pytest -q tests/test_maitu_capabilities.py --tb=short`: 2 passed.
- `npm test -- --run --maxWorkers=1 src/live-rooms/LiveRoomPlannerPage.test.tsx src/live-research/LiveResearchApp.test.tsx`: 12 passed.
- `npm run typecheck`: passed.
- `uv run pytest -q --tb=short` in `workers/browser-use`: 388 passed, including
  the transient-shell and login-redirect regressions.
- The current project profile read-only attempt reached `/Login`, returned
  `logged_in=false`, performed no mutation, and is recorded in
  `customer-v1-v1-0107-maitu-readonly-attempt.md`.

The open canaries and true-user acceptance tasks are intentionally not relabeled
as complete. They are listed in
`customer-v1-v1-external-acceptance-inputs.md` and the active checklist.
