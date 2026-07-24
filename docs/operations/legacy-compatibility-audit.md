# Legacy Compatibility Audit Runbook

## Purpose

This runbook is the repeatable acceptance contract for `CHK-0294`. It proves
that legacy workbench, video, capture, clip, analysis and retry records remain
readable through compatibility projections while their owning legacy paths stay
authoritative. It also proves that compatibility reads do not manufacture
ContentProject, ProductionVariant, WorkflowRun, Release, Delivery or Exposure
facts.

This gate is separate from the production-copy migration rehearsal in
`CHK-0260`. Representative integration data is sufficient for the compatibility
contract, but it is not evidence of production volume, migration duration or
production data quality.

## Safety prerequisites

1. Use an isolated migrated database. Do not run the representative fixture
   tests against production.
2. Apply every repository migration and verify the immutable migration ledger.
3. Start the backend against that exact database with a short-lived control-plane
   operator token. Pass the token to the audit only through an environment
   variable.
4. Populate at least one representative row for each legacy workflow source and
   each domain projection. The focused PostgreSQL compatibility test provides
   these fixtures in an integration database.
5. Do not enable application workers during the audit. Concurrent canonical
   writes would make the before/after non-fabrication check indeterminate.

## Execute

Run the focused repository and API contract tests first:

```bash
ASSETGRAPH_TEST_DATABASE_URL="$INTEGRATION_DATABASE_URL" \
  uv run --project backend pytest -q \
  backend/tests/test_workflow_compatibility_postgres.py \
  backend/tests/test_compatibility_routes.py
```

Then run the read-only audit. The example assumes the backend is already serving
the same integration database at `127.0.0.1:8002`.

```bash
ASSETGRAPH_DATABASE_URL="$INTEGRATION_DATABASE_URL" \
ASSETGRAPH_CONSOLE_OPERATOR_TOKEN="$EPHEMERAL_OPERATOR_TOKEN" \
  uv run --project backend python scripts/audit_legacy_compatibility.py \
  --expected-database assetgraph_phase0_compatibility_YYYYMMDD \
  --classification representative_integration_database \
  --api-base-url http://127.0.0.1:8002 \
  --output docs/evidence/phase-0-legacy-compatibility-audit-YYYY-MM-DD.json
```

The DSN and token are never retained. The report contains only schema identity,
counts, assertion outcomes, endpoint paths and a canonical SHA-256 fingerprint.

## Acceptance gates

The report qualifies for `CHK-0294` only when all of these conditions hold:

- migrations `036` and `040` exist in the immutable ledger with repository
  checksums;
- all seven expected relations are views with semantic comments and enabled
  read-only mutation triggers;
- every legacy source count exactly equals its workflow/step projection count;
- all six workflow source types and all five domain projection types have a
  representative sample;
- legacy geometry is observational, missing provenance remains explicit,
  variant verification requires explicit links, layout hypotheses remain
  approximate/reference-only, and completion never implies delivery/exposure;
- every paginated list and one detail from each workflow source type passes the
  authenticated API response contract;
- the missing detail response retains
  `LEGACY_WORKFLOW_PROJECTION_NOT_FOUND`; and
- canonical fact-table counts are identical before and after every API read.

Any failed gate sets `qualifies_for_chk_0294=false`. Never edit a failed report;
fix the compatibility projection or test fixture and write a new report.

## Production-derived audits

`production_sanitized_copy` and `production_encrypted_copy` classifications are
available for later migration audits. They may reveal source types that have zero
real rows; in that case keep the technical representative report alongside the
production-derived count report instead of inserting synthetic records into the
copy. Neither classification substitutes for `CHK-0260` timing, lock, growth and
owner approval evidence.
