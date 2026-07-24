# Phase 0 Legacy Compatibility Validation

> Date: 2026-07-23  
> Owner: `coderdailyone`  
> Checklist item: `CHK-0294`  
> Data classification: representative integration database, not production data

## Result

`docs/evidence/phase-0-legacy-compatibility-audit-2026-07-23.json` passed and
sets `qualifies_for_chk_0294=true`. Its canonical report fingerprint is
`2cbe5bcc6697773da3dacd6cfeb15f97ed33298428cd107c0d6bd91d3eeb5ec6`.

The audit used PostgreSQL 14 database
`assetgraph_phase0_provider_20260723_007` and the backend API at
`http://127.0.0.1:8002`. Credentials and raw business rows were not retained.

## Verified coverage

| Contract | Result |
| --- | --- |
| Compatibility migrations | `036` and `040` ledger checksums match the repository |
| Read-only boundary | 7/7 views have semantic comments and enabled mutation guards |
| Workflow source coverage | Workbench 8, video 5, capture 3, clip 1, analysis 1, retry 25 |
| Workflow cardinality | Every source count equals its run projection count |
| Step cardinality | Every owning step source count equals its step projection count |
| Domain coverage | Asset 5, content 13, variant 8, layout 5, delivery-unknown 3 |
| Semantic invariants | 8/8 passed with zero invalid rows |
| Authenticated API | 6/6 paginated list routes and all 6 workflow detail types passed |
| Stable missing error | HTTP 404 with `LEGACY_WORKFLOW_PROJECTION_NOT_FOUND` |
| No fabricated canonical facts | 6/6 canonical table counts unchanged before/after reads |

The focused PostgreSQL/API batch passed `6 tests` and explicitly exercises all
six legacy workflow source types. It also rejects compatibility-view mutation,
preserves old source records, and verifies that no matching canonical
WorkflowRun, project, variant or delivery row is created.

## Interpretation

This evidence closes the Phase 0 compatibility contract: old data remains
readable through typed read-only projections and the old repositories remain
executable. It does not claim that the representative counts describe production
volume or quality. Production-copy migration timing, locks, database growth and
approval remain separately blocked under `CHK-0260`.
