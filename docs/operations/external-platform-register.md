# External Platform Register

> Owner: engineering, with security and data approval required before production use
> Review cadence: each Phase gate and whenever terms, region, model or endpoint changes

Locally deployable PostgreSQL, MinIO, Milvus, Neo4j, Qwen3, Kokoro and FFmpeg are
not external API dependencies. They still require version, capacity and recovery
records, but are outside this register.

## Non-blocking input queue

This table is the single collection point for inputs that cannot be manufactured
inside this repository.  It is deliberately **not** a request to stop
implementation: until an input is available, continue with the local domain
model, fake/contract adapter, UI, validation and deterministic test fixtures.
Only the stated production action is blocked.  When an owner provides an input,
attach a versioned evidence reference to the corresponding `EXT-*` entry and
the checklist execution log; do not paste credentials, cookies or raw personal
data into this document.

| Input code | Needed only for | Minimum material to collect | Blocked until supplied | Local work that continues |
| --- | --- | --- | --- | --- |
| `EXT-P1-FACT-SOURCES` | Approving production ProductFactCard facts | Approved source document/URL or export, quoted span, source owner, validity window, platform scope and classification/retention decision | Real fact approval based on external evidence | Fact/revision/lineage UI, validation and local draft fixtures |
| `EXT-P1-RELEASE-SIGNING` | Approving a live-room or rendered-video release | Named signing principal, key-reference mechanism, rotation/revocation owner and signing policy | Production release approval/signature | Candidate snapshots, deterministic manifests and approval-state UX |
| `EXT-P1-RELEASE-EVIDENCE` | Actual remote draft write and authoritative readback | Target account/room authorization, approved API or browser route, readback identity contract and evidence-retention owner | Draft delivery, authoritative readback and reconciliation | BuildPlan generation, local draft projection and fake adapter contract tests |
| `EXT-P2-RECORDING-SAMPLES` | Publishing a template derived from real recordings | Authorized recordings from one source room per CaptureSession, source-room IDs, capture interval/checksums, rights basis and deletion owner | Real CaptureSession import/template publication | Cleaning workflow, template provenance rules and synthetic/authorized fixture tests |
| `EXT-P3-RENDITION-METADATA` | Strict reproducibility for selectable visual media | Immutable rendition checksum, dimensions/aspect, duration, frame-rate/timebase, PTS bounds, probe evidence and availability semantics | Strict source-window/geometric/replay gates | Local asset selection, FFmpeg rendering and deterministic declared-boundary tests |
| `EXT-P3-AUDIO-ASSETS` | Production use of BGM/SFX assets | Approved rendition checksum, duration/timebase/PTS, rights scope, stable material binding and probe evidence | Rights-qualified audio release | Local BGM/SFX lanes, previews, mixing and local-media tests |
| `EXT-P3-VIDEO-DELIVERY-AUTHORIZATION` | Uploading a rendered video to any target channel | Target principal/account, upload scope, API capability, idempotency/rate/error contract, object/checksum readback and revoke/deletion procedure | Video delivery, channel readback and revoke propagation | Render, QC, candidate release and delivery-package sidecar generation |
| `EXT-P3-C2PA-SIGNING` | Issuing a verifiable C2PA Content Credential | Supported signer/certificate chain, timestamp policy, ingredient requirements, verifier and key custody owner | Signed C2PA credential only | Local XMP/IPTC sidecar and release-evidence model |
| `EXT-P4-EVENT-GRAIN-METRICS` | Measured platform attribution and production metric import | Source schema/mapping, immutable batch ID/checksum/watermark, event and processing time/timezone, primary keys, update/delete/refund/backfill rules, release/exposure keys, quality thresholds and data owner | Measured attribution, reconciliation and production metric SLOs | Local JSON import, quality validation, snapshots and descriptive attribution |
| `EXT-P5-OBSERVATION-DATA` | Associational/causal effect eligibility | Versioned immutable metric snapshots, exposure reconciliation IDs, freshness/alignment/sample thresholds, deletion/refund/backfill semantics and approved decision-use rule | Associational/causal estimates and automated learning decisions | Descriptive effect candidates, manual review and frozen-source reproduction |
| `EXT-P7-KNOWLEDGE-SOURCES` | SourceEvidence/FactClaim completion and governed knowledge ingestion | Approved documents/URLs, extraction rights, classification/retention, quoted spans, validity/platform scope and evidence-review owner | External-source ingestion and claim approval | Local knowledge drafts, exact-version usage projection and lineage UI |
| `EXT-PLATFORM-MAITU` | Any real Maitu read/write operation | Approved target-scoped credential, current API/UI contract, terms, quota/cost/region decision and kill-switch owner | Real Maitu delivery/readback | Fake adapter, BuildPlan, local preview and browser/API contract tests |
| `EXT-PLATFORM-DOUYIN` | Authorized recording capture, go-live or operations import | Authorized capture/delivery basis, target account scope, endpoint/export contract, quota/cost/region decision and deletion owner | Real capture, go-live and served-log ingestion | Local CaptureSession model, schedule prototype and import adapters |
| `EXT-PROVIDER-GENERATION` | Using a remote text/vision/ASR provider in production | Provider approval, backend-only credential reference, processor/region/retention decision, budget/quota and fallback owner | Remote provider execution | Local/provider-fake generation, schema validation and deterministic fallback fixtures |

### Local environment conditions (not external inputs)

- `ASSETGRAPH_TEST_DATABASE_URL` is a local PostgreSQL integration-test target.
  It must be migrated to the required revision before PostgreSQL journey tests
  can run, but it never requires a third-party credential or API account.
- Locally deployed Qwen3, Kokoro, MinIO, Milvus, Neo4j and FFmpeg are operated
  as versioned local dependencies. Their availability can limit a local run, but
  does not block repository implementation or create an external-input request.
- A new external dependency must first be added to this queue and the table
  below, with an exit plan, before any production adapter starts using it.

| Dependency | Purpose and data sent | Credential and boundary | Timeout/rate/cost | Failure and fallback | Region/retention | Exit plan |
| --- | --- | --- | --- | --- | --- | --- |
| Maitu authoritative API | Verify room, draft/live state, inventory/material identity and readback; sends target IDs and typed queries | Backend-only bearer token; model/browser never receives it | 30s configured timeout; quota and commercial terms require owner confirmation | Hard fail closed; stable contract fake in tests; no cached approval fallback | Provider policy must be approved before production | Keep authority adapter; replace provider without changing domain attestation contract. |
| Maitu Web UI | Observe and execute allowlisted draft operations in a visible logged-in Chrome session | Browser session stays on controlled host; no cookie in payload, log, screenshot metadata or model prompt | Account/room serialized; UI latency budget measured per workflow | Stop on login, URL, target, fingerprint or readback mismatch; reconcile unknown writes | Screenshots follow restricted evidence retention | Prefer authoritative API when it exposes equivalent writes; retain Browser-use adapter only for missing operations. |
| DeepSeek API | Structured DesignBrief/script/scene generation; sends approved facts, user goal and minimal structural context | Backend provider adapter and API key; no platform credential or raw personal event | 180s and 3 attempts by default; token budget recorded per run | Retry 429/5xx within budget; invalid schema or exhaustion blocks the step | Provider processor/region/retention approval pending | Provider-neutral generation contract supports alternate local/remote model. |
| OpenAI API | Image/video analysis and ASR; sends selected media or audio only after rights/privacy checks | Backend provider adapter and API key; source data classification gate required | 180s and 3 attempts by default; media/token cost recorded | Retry bounded transient errors; invalid/partial output is not canonical; manual/local analysis may replace it | Provider processor/region/retention approval pending | Replace through vision/ASR adapter while retaining AnalysisRun schema and artifacts. |
| Douyin capture endpoints | Authorized source livestream media and interaction capture through pinned StreamCap/douyinLive | Target-specific access basis and kill switch; no generalized credential export | Platform limits and recorder backpressure measured per WatchTarget | Pause/stop on revoked basis, endpoint failure or kill switch; retain received source chunks according to policy | 30-day raw default pending approved policy | Platform adapter boundary permits authorized export or another recorder. |
| JD/Maitu/Douyin operations data | Metrics, actual exposure and external session identity from official API, authorized export or controlled browser | Source-specific credential and DataContract; only minimal fields accepted | Unknown until source contract is approved; budget and polling limits are mandatory | Quarantine unknown schema/time/identity; manual versioned import is the initial fallback | Personal events require restricted classification and deletion propagation | Replace source adapter; immutable standard events and metric revisions remain stable. |
| Platform scheduling and go-live APIs | Validate target account/room availability, platform schedule rules, promotion and inventory state; a future separately authorized flow may submit an approved schedule or open a live session | Backend-only target-scoped credential and GoLiveAuthorization; current local schedule prototype sends nothing externally | Unknown until each platform contract, quota and commercial rule is approved; no polling or submission is enabled now | Keep local plan validation available; fail closed on unavailable target/rule facts and never infer approval from a local plan | Provider account, regional rules and retention of schedule/readback evidence require owner approval | Retain the versioned local schedule/release contract; replace only the platform adapter after contract tests and go-live review. |
| Knowledge source systems and controlled documents | Supply approved documents, webpages, exports or human confirmations as SourceEvidence; current Console accepts manually supplied excerpts and does not fetch any source | Source owner must approve access scope, extraction rights and, when applicable, a backend-only source credential; raw restricted content is excluded from model prompts by default | No crawler, polling or provider spend is enabled now; each future connector needs source-specific limits and cost ownership | Keep a local source-evidence draft; source failure never creates an approved fact or inferred citation | Source owner defines classification, retention, validity/platform scope and evidence-review responsibility before ingestion | Preserve evidence code/checksum/citation contract and replace only the connector. |

## Mandatory controls

- Each production adapter has a named owner, approved terms/legal basis, processor
  record, data-region decision, quota/cost alert, kill switch and credential
  rotation runbook.
- Provider-specific model names and response shapes remain inside adapter and
  invocation evidence. Domain requests refer to a versioned strategy/capability.
- Fakes reproduce authentication failure, timeout, 429, 5xx, bad schema, partial
  response and unknown side effects. A permissive success-only mock is forbidden.
- No external dependency may weaken fact, rights, authorization, quality,
  evidence or release gates.
