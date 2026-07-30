# Customer Experience v1 Fault-Injection Matrix

Date: 2026-07-26

## Result

| State | Injected condition | Customer-visible result | Verification |
| --- | --- | --- | --- |
| `loading` | Queries remain unresolved | Named loading block is rendered; workspace is not blank | `components.test.tsx`: explicit loading/empty state |
| `empty` | Collection resolves with no records | Named empty state and recovery detail replace the loader | `components.test.tsx`; Knowledge empty-state tests |
| `error` | React render throws or local renderer reports a failed stage | Stable error rule hides stack/secrets; video page names the failed stage and repair actions | `ConsoleApp.test.tsx`; `VideoProductionPage.test.tsx` |
| `partial` | One operation session lacks the selected metric; one analysis DAG step fails | All sessions remain visible, the missing metric is named, and the successful analysis steps are retained while only the failed step is retryable | `OperationsPage.test.tsx`; `live-research/api.test.ts` |
| `stale` | Draft save returns `STALE_REVISION` | Local text remains in the editor, no false saved receipt appears, and the operator gets an explicit reload action | `EntityDraftEditor.test.tsx` |
| `conflict` | TimeMapping or timeline revision changes after load | API returns a stable conflict and does not commit the stale request | PostgreSQL operation conflict and video restore route tests |
| `manual downgrade` | Maitu login, capability or material binding is unavailable | UI exposes the full manual handoff; Worker performs no retry/mutation and records `manual_required` | `LiveRoomPlannerPage.test.tsx`; browser-use focused tests |

## Focused Run

- Frontend customer-visible state suite: 7 files, 45 passed.
- Backend conflict contracts: 2 passed, including PostgreSQL planning conflict.
- Browser-use manual downgrade: 3 passed.

The full release test matrix remains in
`docs/evidence/customer-v1-v1-test-matrix.md`. Fault states are not mapped to a
success badge, and no simulated provider response is recorded as an external
canary.
