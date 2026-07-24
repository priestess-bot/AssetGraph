# Least-Privilege Capability Matrix

> Version: `baseline-least-privilege@1`
> Date: 2026-07-23
> Source of truth: `capability_policy_versions`; this document is its reviewed projection.

| Role | Capability | Scope | Mandatory separation |
| --- | --- | --- | --- |
| `production_editor` | `edit_production` | Content and production drafts only | Cannot publish facts/templates by implication |
| `fact_publisher` | `publish_fact` | Reviewed FactCard revision | One explicit approval |
| `template_publisher` | `publish_template` | Reviewed template revision | One explicit approval |
| `effect_approver` | `approve_effect` | Effect estimate revision | Producer cannot approve own effect |
| `draft_writer` | `write_draft` | Bound blank Maitu draft room and plan hash | Commit-time authorization and readback |
| `asset_uploader` | `upload_asset` | Bound asset/rendition and target account | Does not grant draft writing |
| `release_deliverer` | `deliver_release` | Approved ReleaseManifest and target | Release creator cannot self-deliver |
| `graph_operator` | `rebuild_projection` | Rebuildable projection version | No fact-source mutation |
| `broadcast_operator` | `go_live` | Bound release, room and time window | Two approvals; globally hard-disabled |

Capabilities are non-transitive. A role listed in one row receives no other row.
Environment flags default to disabled; policy allowance does not override a flag,
ProtectedResource, rights, quality, approval or commit-time check.

Protected resources use these resource types: `maitu_room`, `live_room`,
`platform_account`, `production_object` and `external_resource`. `read_only` and
`deny_write` reject every write capability. `allowlisted_write` rejects all
capabilities not explicitly listed. Reference rooms `38336` and `38995` are
system-locked `maitu_room` records and cannot be removed through normal commands.

Every external write is checked independently at preflight, PDP decision and
Worker commit. A passed preflight is evidence only and never an authorization.
