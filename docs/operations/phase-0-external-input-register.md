# Phase 0 External Input Register

> Status: open. This register records only inputs that require an operator, an
> approved operational environment, or an accountable business decision. It is
> intentionally not a substitute for evidence and does not qualify any `CHK`.
> Updated: 2026-07-24

## How To Use This Register

Engineering continues with isolated spikes while these inputs are absent. A
spike must not move a Phase 1-8 production checkbox to done before Phase 0 has
passed. When an input is available, place the approved evidence outside the
repository or under the agreed evidence location, add its immutable reference
below, run the named command, and append the resulting fingerprinted report to
the implementation checklist execution log.

No credential, customer data, source database DSN, or signed personal data is
to be committed to this file.

## Required Inputs

| Register ID | Required for | What the accountable operator supplies | Evidence and command | Current state |
| --- | --- | --- | --- | --- |
| `EXT-P0-OWNERS` | `CHK-0002`, `CHK-0296` | Named product, engineering, data, security owners for every Phase; a design owner for UI work; appointment references and decision authority. | Populate an approved owner register, then run `uv run --project backend python scripts/assemble_phase0_acceptance.py ...`. | Open |
| `EXT-P0-CAPACITY` | `CHK-0110` | Read-only operational snapshot with at least seven days of history; immutable snapshot reference; approved limits, forecasts, unit costs, stop thresholds and engineering/data/operations approvals. | Use `docs/operations/capacity-baseline-measurement-2026-07-23.md` and `scripts/measure_capacity_baseline.py`. The output must set `qualifies_for_chk_0110=true`. | Open |
| `EXT-P0-OBJECTS` | `CHK-0110` | Read-only object-store endpoint/bucket credentials delivered through the secret manager, and permission to reconcile ArtifactRef objects. | Include object reconciliation in the capacity report. Object names and credentials must not be retained in Git. | Open |
| `EXT-P0-MIGRATION-COPY` | `CHK-0260` | A disposable, isolated sanitized or encrypted production copy that predates at least one pending migration; source snapshot reference; sanitization evidence where applicable. | Follow `docs/operations/database-migration-rehearsal.md`; run `scripts/rehearse_migrations.py --acknowledge-isolated-copy`. The report must set `qualifies_for_chk_0260=true`. | Open |
| `EXT-P0-SIGNOFF` | `CHK-0296` | Product, engineering, data and security acceptance decisions after reviewing the complete package, including known limits and rollback evidence. | Use `docs/operations/phase-0-acceptance-package.md`. The package is valid only when the owner register, capacity report and migration report qualify. | Open |
| `EXT-P1-MAITU-DRAFT` | `CHK-1162`, `CHK-1283` through `CHK-1285` | Authoritative Maitu staging/production credential through the approved secret channel; a designated empty, unlive draft room; target identity attestation; an operator authorized to inspect read-back. | No request is made until Phase 0 has passed. Use the existing fenced draft-execution workflow; never provide credentials in Git or chat. | Deferred |
| `EXT-P1-RELEASE-EVIDENCE` | `CHK-1220`, `CHK-1221`, `CHK-1290` through `CHK-1295` | Asset/template rights decision references, a short-lived draft-write authorization, and authoritative Maitu preflight/final readback evidence for one designated empty room. | Create the candidate locally first. Supply immutable evidence references through the agreed evidence store, then run the release validation and draft-delivery/readback workflow. No source credential or raw room data belongs in Git. | Deferred |
| `EXT-P1-RELEASE-SIGNING` | Deployment of `CHK-1220` candidate creation outside `app_env=local` | A secret-manager reference for a dedicated Release manifest HMAC key and its key ID, with the rotation owner and expiry policy. | Set `ASSETGRAPH_MANIFEST_SIGNING_KEY` and `ASSETGRAPH_MANIFEST_SIGNING_KEY_ID` only in deployment configuration. Local development uses a clearly identified local-only signing key and must not reuse it outside local. | Open for deployment |

## Handoff Package

For each supplied item, provide a short immutable reference, its owner, the
approval date, the data classification, and a contact for expiry/revocation.
The following placeholders are deliberately not values:

```text
register_id:
owner:
approved_reference:
data_classification:
secret_manager_reference:            # only for access material; never the secret
expires_at:
notes:
```

## Engineering Work That Continues Without These Inputs

- Versioned content, material, template, video, operations, learning and
  knowledge-domain contracts can be implemented and tested only against
  isolated integration databases.
- UI workflows, schema validation, content compilation and local deterministic
  fixtures can be developed as spikes.
- Any record or report produced from those fixtures is labelled
  `representative_integration_database`, `synthetic_fixture`, `plan_only`, or
  `deterministic_demo` as applicable. It cannot be promoted to an operational
  capacity, delivery, exposure, Maitu-write, or production acceptance claim.

## Completion Rule

When all five Phase 0 entries above are resolved, regenerate the acceptance
package and update only the corresponding `CHK-0002`, `CHK-0110`, `CHK-0260`,
and `CHK-0296` lines with their commit, report fingerprint, approval reference,
and completion time. Do not bulk-check dependent Phase items.
