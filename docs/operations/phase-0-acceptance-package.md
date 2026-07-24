# Phase 0 Acceptance Package

## Purpose

`CHK-0296` and the Phase archive rule `CHK-0012` require evidence-bound human
acceptance. `scripts/assemble_phase0_acceptance.py` prevents a signature from
being applied to moving or incomplete evidence by calculating one technical
package fingerprint over:

- all Phase 0 and global prerequisite checkbox states;
- named owners for every Phase;
- qualifying capacity, production-copy migration, compatibility and disaster
  recovery reports;
- a fingerprinted full-regression report; and
- required design, architecture, security, runbook and validation artifacts.

The script then verifies product, engineering, data, security and operations
decisions against that exact fingerprint. It never creates or infers a human
approval.

## Two-stage execution

1. Copy the owner-register example to an approved records location and replace
   every null with an actual owner and appointment reference. Update `CHK-0002`
   only after that record is approved.
2. Complete `CHK-0110` and `CHK-0260` with qualifying operational reports.
3. Run and archive the complete regression suites in a fingerprinted
   `phase0-regression-report.v1`.
4. Assemble without `--signoff`. The output will be `ready_for_signoff` only if
   every technical gate passes; record its `technical_package_fingerprint`.
5. Have all five roles review that immutable package. Put their real decisions,
   evidence references and timezone-aware timestamps in an external approved
   copy of `phase-0-acceptance-signoff.v1.example.json`.
6. Reassemble with `--signoff`. Any evidence/checklist/owner change changes the
   technical fingerprint and invalidates the prior signatures.
7. Only when `qualifies_for_chk_0296=true`, archive the output and immediately
   update `CHK-0296` and `CHK-0012` with their execution-log rows.

```bash
uv run --project backend python scripts/assemble_phase0_acceptance.py \
  --owner-register /approved/phase-owner-register.v1.json \
  --capacity-report /approved/capacity-baseline.json \
  --migration-report /approved/migration-rehearsal.json \
  --compatibility-report docs/evidence/phase-0-legacy-compatibility-audit-2026-07-23.json \
  --disaster-recovery-report docs/evidence/phase-0-disaster-recovery-baseline-2026-07-23-attempt-4.json \
  --regression-report /approved/phase0-regression.json \
  --signoff /approved/phase0-signoff.json \
  --output /approved/phase0-acceptance-package.json
```

The repository examples are deliberately non-approvable. They are schemas and
operator aids, not evidence.
