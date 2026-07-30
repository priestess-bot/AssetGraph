# ADR-0003: Customer-experience-first v1 scope

- Status: accepted
- Date: 2026-07-26
- Owners: product and engineering
- Checklist: `V1-0001` through `V1-0808`
- Supersedes: the 577-item production-grade checklist as the active v1 delivery denominator; it does not supersede ADR-0001 invariants

## Context

The production-grade closed-loop design is intentionally broad. Its implementation
checklist contains 577 product, governance, reliability and enterprise-readiness
items. Treating all of them as the shortest path to usable workflows has delayed
customer-visible results and obscured the actual Maitu automation boundary.

The first customer is a trusted content-operations team using a private,
single-team deployment. They need usable material, template, content, Maitu-draft,
local-video and feedback workflows before they need multi-tenant authorization,
formal go-live, causal experimentation or enterprise operations controls.

The repository contains a browser adapter for Maitu's web application. Maitu's
public product information does not provide a stable public automation contract
for these mutations. Adapter code and mocked tests are therefore not sufficient
evidence that a mutation is currently executable in a real account.

## Decision

AssetGraph v1 is delivered in two customer releases:

1. Release A: material library and constraints, uploaded-recording templates,
   facts-to-story-to-script, live-room configuration, an editable rectangular
   `MaituSceneBlueprint`, Maitu draft handoff/readback, and local vertical video.
2. Release B: operations-file import, content attribution, knowledge projection,
   effect-informed retrieval and assisted reproduction.

The active v1 checklist is
`docs/plans/2026-07-26-customer-experience-v1-implementation-checklist.md`.
The former 577-item checklist remains an append-only production-readiness roadmap
and evidence archive, but is not the v1 completion denominator.

The deployment model is one trusted team. Existing authentication, audit,
revision, provenance and immutable-release foundations remain in place. V1 does
not add tenant isolation, fine-grained RBAC, object ACLs, dual approval or a
permission-management UI. Only three customer-facing hard gates are required:

- facts used in generated claims must be approved or explicitly marked absent;
- selected materials must have an acceptable rights/usage state;
- a Maitu target must be the exact customer-supplied room and be confirmed blank,
  non-live and title-matched before any mutation.

The customer creates the blank Maitu room and supplies its ID and title. AssetGraph
does not create rooms, train digital humans or voices, configure commerce/live
interaction, schedule, authorize go-live or click go-live. It may use existing
Maitu materials, digital humans and voices, and may upload ordinary image/video
files after those capabilities pass a real-account canary.

Maitu layout output promises editable rectangular layers and reload/readback
evidence, not pixel-perfect reconstruction from a recording. Uploaded recordings
are the guaranteed template input; external-platform capture is an optional
adapter enhancement.

Every Maitu capability is exposed through a versioned capability matrix. A
mutation stays `manual_only` until a real-account canary proves target preflight,
mutation and reload/readback against the current adapter contract. Unsupported
capabilities remain visible as `unsupported`. The UI must not offer automatic
draft execution unless every required mutation is `verified`; plan generation and
manual handoff remain available.

Each completed v1 implementation point is checked immediately in the active
checklist with its test or artifact evidence. Documentation-only preparation does
not count as completion of customer behavior.

## Alternatives

- Completing all 577 production-grade items first was rejected because governance
  and reliability work dominated the critical path to customer-visible value.
- Deleting the production roadmap was rejected because its invariants and future
  readiness work remain useful and its completed evidence must stay traceable.
- Treating browser-adapter code as proof of Maitu support was rejected because
  private web endpoints and UI behavior are version-sensitive.
- A fully manual Maitu flow was rejected as the permanent target, but is retained
  as an honest fallback until each mutation passes a canary.

## Consequences

Release A can be evaluated without formal go-live or enterprise authorization.
Some already-implemented production controls remain present but are frozen rather
than expanded. Product status language must distinguish customer outcomes from
internal workflow states.

Automatic Maitu draft writing may initially be unavailable. This is an explicit
product state, not a hidden failure. The interface still generates the blueprint,
operation plan and a manual handoff that an operator can execute.

V1 does not claim pixel-perfect layout, autonomous platform capture, formal
causal attribution, unattended production operations or readiness for multiple
organizations.

## Evolution

No schema or API is removed by this decision. Existing production-grade objects
and endpoints remain backward compatible. Deferred controls can be reactivated
through a later ADR when a concrete customer, risk or scale threshold requires
them.

The Maitu capability contract is append-only within schema version 1. Capability
keys and meanings do not change in place; a breaking change uses a new schema
version. A capability can move to `verified` only with a dated canary artifact and
contract fingerprint, and returns to `manual_only` when the contract changes or
readback fails. `create_live_room`, `schedule` and `go_live` require a separate
scope ADR before implementation.

Rollback consists of hiding the v1 capability presentation and returning to
manual handoff; it never reinterprets an unverified mutation as successful.

## Evidence

- `docs/plans/2026-07-22-live-content-production-operations-closed-loop-design.md`
- `docs/plans/2026-07-23-live-content-production-operations-implementation-checklist.md`
- `workers/browser-use/src/browser_use_worker/browser_cli_session.py`
- `docs/maitu-live-room-runs/40147-after-background-script.png`
- `docs/maitu-live-room-runs/38336-zhangyu-summer-readonly-entry.png`
- `docs/plans/2026-07-26-customer-experience-v1-implementation-checklist.md`
