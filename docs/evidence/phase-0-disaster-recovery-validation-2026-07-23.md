# Phase 0 Disaster-Recovery Validation

- Date: 2026-07-23
- Checklist item: `CHK-0295`
- Result: local PostgreSQL PITR and versioned ArtifactRef restore baseline passed
- Successful run: `DR-20260723-A914107BBC29`
- Authoritative report:
  `phase-0-disaster-recovery-baseline-2026-07-23-attempt-4.json`

## Exercise

The drill created a separate PostgreSQL 14 cluster with WAL archiving, full-page
writes, and data page checksums enabled. It applied all 44 repository migrations,
registered a confidential ArtifactRef, took and verified a physical base backup,
then committed two marker transactions around a UTC recovery target. After the
later marker's WAL was archived, the source database was stopped immediately.

A new cluster was restored from the base backup and WAL archive with
`recovery_target_time` and `recovery_target_action=promote`. Acceptance required:

- the base-backup and before-target markers to exist;
- the after-target marker to be absent;
- the restored server to finish promotion;
- all 44 migration receipts to exist;
- all 12 Phase 0 migration/business invariants to pass;
- `pg_verifybackup`, `pg_amcheck`, and offline `pg_checksums --check` to pass; and
- the recovered ArtifactRef identity, URI, byte size, and checksum to remain exact.

In parallel, a local MinIO RELEASE.2025-04-22 server stored the ArtifactRef payload
in a versioned bucket. The drill overwrote the content-addressed key, created a
delete marker, fetched the original immutable version ID, restored it as the
current version, and verified both content and metadata checksum against the
recovered PostgreSQL ArtifactRef.

## Measured result

| Measurement | Result |
| --- | --- |
| Physical base backup | 62,935,669 bytes in 605 ms |
| PostgreSQL measured RPO | 1 ms from target to latest retained committed marker |
| PostgreSQL measured RTO | 820 ms from disaster declaration through promoted, validated database |
| Object measured RPO | 0 bytes; exact retained version restored |
| Object measured RTO | 842 ms from disaster declaration through checksum validation |
| Composite measured RTO | 842 ms |
| Migration and business validation | 44/44 migrations and 12/12 invariants passed |
| Cross-store validation | recovered ArtifactRef matched restored object |

The report is canonical-JSON fingerprinted, contains no DSN or generated
credentials, and records exact version/checksum evidence.

## Failure reflection

Three failed reports are intentionally retained and tested as non-qualifying:

1. The first attempt failed because the isolated PostgreSQL cluster inherited the
   system Unix-socket directory, where the current user could not create a lock
   file. The script now binds sockets to its isolated workspace.
2. The second attempt performed a redundant second `pg_switch_wal` with no new WAL
   payload. Its archive-count wait timed out correctly. One forced switch after the
   later marker is sufficient and is now the contract.
3. The third attempt restored the exact target and passed object/checksum/invariant
   checks, but `pg_ctl -w` returned at the intermediate read-only-ready state. The
   script observed `pg_is_in_recovery=true` milliseconds before automatic promote
   and correctly refused qualification. It now explicitly waits for promotion.

No failed run was overwritten or counted as completion. Automated tests assert
that all three remain `status=failed` and `qualifies_for_chk_0295=false`.

## Scope boundary

This is the Phase 0 recovery baseline requested by `CHK-0295`, not a production
SLO claim. The dataset contains the full schema plus deterministic drill records,
not production volume. It does not cover multi-node failure, remote backup loss,
or the production RPO <= 5 minutes / RTO <= 4 hours gate in `CHK-7230`. Those later
checks require operational topology, production-scale data, approved retention,
off-site copies, and owner acceptance.

## Reproduction

```bash
uv run --project backend python scripts/rehearse_disaster_recovery.py \
  --workspace /isolated/assetgraph-dr-attempt \
  --output /approved/evidence/disaster-recovery-report.json \
  --cleanup-workspace-on-success
```

The script refuses existing workspaces or occupied ports, creates new random local
credentials without persisting them, stops all spawned services in `finally`, and
only removes the workspace after a successful report is written.
