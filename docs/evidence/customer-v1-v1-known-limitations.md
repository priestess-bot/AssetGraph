# Customer Experience v1 Known Limitations

Date: 2026-07-26
Updated: 2026-07-31

This list is ordered by customer impact. Security or enterprise-readiness work
does not displace P0/P1 customer workflow issues in this v1.

## P0: Blocks A Claimed External Outcome

| Limitation | Customer impact | Current fallback | Exit evidence |
| --- | --- | --- | --- |
| No approved real external recording has been supplied for this release | Upload and analysis contracts are tested, but current provider quality on customer media is unknown | Local upload remains available; operator can retry failed analysis stages | `V1-0308` |
| No approved real business brief/fact set has been supplied for this release | Generated copy quality for the customer's actual product has not been accepted | Use approved facts and review every generated revision | `V1-0412` |

## P1: Affects First-Use Experience Or Confidence

| Limitation | Customer impact | Current fallback | Exit evidence |
| --- | --- | --- | --- |
| A new operations user has not completed the five-task usability run | Discoverability, task time and engineering intervention are not yet measured | Automated interaction and responsive checks cover mechanics, not human comprehension | `V1-0803`, `V1-0804`, `V1-0808` |
| The successful three-scene Maitu draft run took about 9 minutes 17 seconds | Customers may think execution has stalled, especially when the stage label returns from readback to scene building for the next scene | The page shows real stage events and the job remains resumable through reconciliation | Cache verified material resolution, reduce full-room reads, and show monotonic scene-aware progress |
| Maitu-native digital-human resources do not yet have a local proxy preview | The Console canvas can show a placeholder even though the final Maitu binding and readback are valid | The material row identifies the native binding and final working-room readback is authoritative | Generate a low-resolution local proxy preview with explicit source labelling |
| The acceptance dataset has no multi-session qualified effect signal | Recommendations correctly show zero effect contribution, so customers cannot yet assess useful effect-driven ranking | Constraint/content ranking and descriptive hints remain available | Import at least three comparable linked sessions with an approved metric definition |
| Historical asset records include incomplete classification or rights state | Operators may need to classify/approve older assets before BuildPlan generation | Filters, batch classification, explicit rights status and gap remediation are available; the four-role acceptance sample is complete | Complete legacy backfill before onboarding customer history |
| The Console entry bundle is about 933 kB before gzip | First load may be slower on weak clients | All routes load and remain usable | Route-level code splitting and measured load budget |
| Long detail workspaces require substantial vertical scrolling on mobile | Review is possible but slower than desktop | Desktop is the recommended authoring surface; mobile remains usable for inspection | Usability baseline and targeted mobile workflow redesign |

## P2: Deliberate V1 Boundaries

- Platform unattended watching is an optional adapter enhancement, not a v1
  availability promise. The guaranteed template input is an uploaded recording.
- Recording-derived layouts remain `approximate/reference_only`; they do not
  contain real Maitu material IDs, layer IDs, z-index, or replacement semantics.
- The video editor is a structured deterministic timeline, not an interactive
  nonlinear editing suite.
- Attribution is descriptive or associational and never presented as causal.
- Effect-aware recommendations are advisory and require explicit operator choice.
- PostgreSQL is the local lineage projection and source of rebuildable queries;
  Neo4j and Milvus are optional local enhancements, not prerequisites.
- Asset rights use a small trusted-operator status model. V1 does not implement
  organization RBAC, grants by geography/channel, object ACLs, or dual approval.
- Operations imports are optimized for local CSV/XLSX files up to 5 MB and 5000
  rows, with the source file stored in PostgreSQL for this deployment profile.
- AssetGraph does not create a Maitu room, create a digital human or voice,
  configure products/interactions, schedule, authorize go-live, or click go-live.

## Release Interpretation

Release A is demonstrable through a reviewable BuildPlan, a rendered vertical
video, and a Console-requested real Maitu test-room rebuild. The product path
completed content generation, room inspection, explicit reset, queue claim,
three-scene write, authoritative readback and Console refresh with `go_live=false`.
This does not authorize customer-room replacement, publishing or go-live;
rights remain pending and automatic replacement stays limited to the allowlisted
offline test room. Release B is locally demonstrable
for file import, descriptive attribution, lineage, advisory recommendations and
draft reproduction; its business usefulness still needs the true-user run.
