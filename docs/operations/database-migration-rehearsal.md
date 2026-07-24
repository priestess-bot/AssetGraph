# Database Migration Rehearsal Runbook

## Purpose

This runbook is the execution contract for `CHK-0260`. A clean or synthetic
database proves migration syntax and tooling only. The checklist item can be
completed only by a successful report from a traceable, isolated production data
copy with measured duration, locks, catalog health, business invariants, and an
additive forward fix.

## Safety prerequisites

1. Create a new disposable database from an approved production snapshot. Never
   connect the rehearsal tool to the production database.
2. Record the backup/snapshot identifier, capture time, source PostgreSQL major
   version, and responsible database owner.
3. Use `production_sanitized_copy` only when a separate sanitization report proves
   that secrets and restricted personal data were removed. Record that report as
   `sanitization_evidence_ref`.
4. Use `production_encrypted_copy` only inside the approved restricted
   environment. The report is confidential even though it stores no DSN.
5. Disable application/worker access to the copy. The tool refuses to start if any
   other database session exists.
6. Confirm storage headroom for the restored database, WAL, new indexes, and
   temporary files. Record the measured free-space evidence outside this report.
7. Assign an engineering owner and database operator. Data/security approval is
   also required for a production-derived copy.

## Execute

Use an exact database name and the explicit isolated-copy acknowledgement. Do not
put a password in shell history; the example expects `ASSETGRAPH_DATABASE_URL` to
come from an ephemeral secret injection.

```bash
uv run --project backend python scripts/rehearse_migrations.py \
  --expected-database assetgraph_migration_rehearsal_YYYYMMDD \
  --copy-classification production_sanitized_copy \
  --source-snapshot-ref SNAPSHOT-... \
  --sanitization-evidence-ref ART-SANITIZE-... \
  --acknowledge-isolated-copy \
  --lock-timeout-ms 5000 \
  --statement-timeout-ms 900000 \
  --output /approved/evidence/migration-rehearsal-YYYYMMDD.json
```

The runner:

- verifies every applied migration checksum against the repository;
- takes a global AssetGraph migration advisory lock;
- commits one append-only migration at a time and writes its receipt in the same
  transaction;
- applies per-migration lock and statement timeouts;
- samples granted/ungranted locks and blocking PID counts without persisting SQL,
  credentials, or row data;
- records database/table/index sizes and exact counts for critical source tables;
- validates index/constraint health and the versioned Phase 0 business invariant
  contract; and
- verifies that migration `044` is an additive forward fix after `043` and that
  its constraint is validated.

Additional large or risk-bearing tables must be named with repeated
`--exact-count-table TABLE` arguments. When any argument is supplied it replaces
the default table set, so include every required table explicitly.

## Acceptance gates

The generated `migration-rehearsal-report.v1` is acceptable only when all of the
following are true:

- `status = passed` and `qualifies_for_chk_0260 = true`;
- at least one repository migration was actually pending and applied;
- copy classification and source/sanitization evidence are valid;
- every repository migration and checksum matches the final ledger;
- every comparable critical-table count is stable;
- all versioned business invariants pass;
- there are zero invalid/unready indexes and zero unvalidated constraints;
- the `043 -> 044` forward-fix check passes;
- lock monitoring itself has no error; and
- the measured duration, maximum lock wait, database growth, and headroom are
  accepted by the engineering/database owners.

`synthetic_fixture` can validate tooling but is hard-coded as non-qualifying. The
current synthetic evidence is
`docs/evidence/phase-0-migration-rehearsal-synthetic-2026-07-23.json`; it must never
be cited as the real-copy rehearsal.

## Failure handling

### Lock timeout

Stop. Use the sampled relation and blocking PID count to locate the owning
transaction in the controlled environment. Do not kill a production transaction
from this rehearsal. Release or reschedule the blocker, restore a fresh copy when
needed, and rerun explicitly. A timed-out migration has no ledger receipt and its
transaction is rolled back.

### Statement timeout or migration error

Preserve the failed report. Confirm which earlier migration receipts committed.
Never edit or delete an applied migration or its ledger row. Fix an unapplied SQL
file only when its checksum was never recorded. If the defect is already committed,
create the next numbered additive migration.

### Post-commit semantic defect

1. Add a new numbered forward-fix migration; do not add a down migration and do
   not mutate the defective file.
2. Add a counterexample to `phase-0-migration-invariants.v1.json` and an automated
   regression test.
3. Restore a new copy from the same source snapshot, apply the original plus repair
   sequence, and compare reports.
4. Restore another current production copy and rerun before approval, because the
   source may have changed while the repair was developed.
5. Keep production enablement blocked until owners accept the new duration, locks,
   growth, invariant results, and repair behavior.

Migration `044_provider_neutral_analysis_identity.sql` is the current concrete
forward-fix example: it adds database enforcement after `043` introduced the
neutral columns and compatibility boundary. Tests also prove lock-timeout rollback,
explicit retry, concurrent-runner rejection, and checksum drift rejection.

### Invariant, count, index, or constraint failure

Do not waive it in the report. Classify whether the source copy is already
inconsistent, the migration changed facts, or the invariant contract is wrong.
Any contract change requires design/ADR review and a new contract revision. Run a
fresh rehearsal; never edit the prior report.

## Evidence and checklist update

The approved JSON report is immutable evidence. Store its SHA-256, snapshot and
sanitization references, database/headroom evidence, owner decisions, and exact
commit in the `CHK-0260` execution-log row. Only then change the checkbox to
`[x]`. Every later migration repeats this rehearsal under `CHK-8141`; prior Phase 0
evidence is not a permanent waiver.
