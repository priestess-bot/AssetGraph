# Disaster-Recovery Baseline Runbook

## Phase 0 use

Run `scripts/rehearse_disaster_recovery.py` to establish the local PITR and
versioned-object recovery baseline required by `CHK-0295`. It creates isolated
PostgreSQL and MinIO instances and never touches the configured application
database or object bucket.

Prerequisites:

- PostgreSQL server/client binaries of one supported major version, including
  `initdb`, `pg_ctl`, `pg_basebackup`, `pg_verifybackup`, `pg_amcheck`, and
  `pg_checksums`;
- the locked local MinIO binary or an explicitly supplied equivalent;
- four unused loopback ports; and
- enough local space for source data, WAL archive, base backup, recovery copy, and
  versioned object data.

Use a new workspace and output path for every attempt. Reports are create-only and
must not be overwritten.

```bash
uv run --project backend python scripts/rehearse_disaster_recovery.py \
  --workspace /tmp/assetgraph-dr-$(date +%Y%m%d%H%M%S) \
  --output /approved/evidence/assetgraph-dr-$(date +%Y%m%d%H%M%S).json \
  --cleanup-workspace-on-success
```

Accept only `status=passed`, `qualifies_for_chk_0295=true`, a valid report
fingerprint, database/object/cross-store `passed=true`, and non-empty measured
RPO/RTO values. A failed run is evidence for diagnosis, never permission to retry
silently or mark the checklist.

## Production extension

This local drill does not configure production backups. Before `CHK-7230`, adapt
the same marker, checksum, invariant, and cross-store checks to the actual topology:

1. verify scheduled base backups and continuous off-site WAL archive;
2. test loss of the primary site and of current object versions;
3. restore a production-scale sanitized copy into an isolated account/network;
4. measure from incident declaration through application-level validation;
5. test backup retention, encryption, access audit, and key recovery;
6. prove the approved RPO/RTO under realistic data and concurrency; and
7. document rollback, escalation, on-call ownership, and failed-drill remediation.

Service startup alone is never a successful restore. Marker boundaries, migration
ledger, business invariants, physical checks, ArtifactRef/object identity, and
checksum validation must all pass.
