# AssetGraph Architecture Decision Records

ADRs record changes to aggregate boundaries, immutable revisions, time semantics,
release/delivery/exposure, authorization, evidence levels and infrastructure
adoption. Accepted ADRs are append-only. Reversal creates a new ADR that links to
the superseded record.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-closed-loop-domain-invariants.md) | accepted | Closed-loop domain and evolution invariants |
| [0002](0002-defer-temporal-until-measured-thresholds.md) | accepted | Keep PostgreSQL workflow execution until measured adoption triggers |

Use [the template](template.md) for new decisions. Every ADR must include data
migration, compatibility, rollback/forward-fix, security, observability and exit
conditions. A checklist item that relies on an ADR links its exact revision.
