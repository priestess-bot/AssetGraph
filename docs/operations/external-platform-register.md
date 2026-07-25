# External Platform Register

> Owner: engineering, with security and data approval required before production use
> Review cadence: each Phase gate and whenever terms, region, model or endpoint changes

Locally deployable PostgreSQL, MinIO, Milvus, Neo4j, Qwen3, Kokoro and FFmpeg are
not external API dependencies. They still require version, capacity and recovery
records, but are outside this register.

| Dependency | Purpose and data sent | Credential and boundary | Timeout/rate/cost | Failure and fallback | Region/retention | Exit plan |
| --- | --- | --- | --- | --- | --- | --- |
| Maitu authoritative API | Verify room, draft/live state, inventory/material identity and readback; sends target IDs and typed queries | Backend-only bearer token; model/browser never receives it | 30s configured timeout; quota and commercial terms require owner confirmation | Hard fail closed; stable contract fake in tests; no cached approval fallback | Provider policy must be approved before production | Keep authority adapter; replace provider without changing domain attestation contract. |
| Maitu Web UI | Observe and execute allowlisted draft operations in a visible logged-in Chrome session | Browser session stays on controlled host; no cookie in payload, log, screenshot metadata or model prompt | Account/room serialized; UI latency budget measured per workflow | Stop on login, URL, target, fingerprint or readback mismatch; reconcile unknown writes | Screenshots follow restricted evidence retention | Prefer authoritative API when it exposes equivalent writes; retain Browser-use adapter only for missing operations. |
| DeepSeek API | Structured DesignBrief/script/scene generation; sends approved facts, user goal and minimal structural context | Backend provider adapter and API key; no platform credential or raw personal event | 180s and 3 attempts by default; token budget recorded per run | Retry 429/5xx within budget; invalid schema or exhaustion blocks the step | Provider processor/region/retention approval pending | Provider-neutral generation contract supports alternate local/remote model. |
| OpenAI API | Image/video analysis and ASR; sends selected media or audio only after rights/privacy checks | Backend provider adapter and API key; source data classification gate required | 180s and 3 attempts by default; media/token cost recorded | Retry bounded transient errors; invalid/partial output is not canonical; manual/local analysis may replace it | Provider processor/region/retention approval pending | Replace through vision/ASR adapter while retaining AnalysisRun schema and artifacts. |
| Douyin capture endpoints | Authorized source livestream media and interaction capture through pinned StreamCap/douyinLive | Target-specific access basis and kill switch; no generalized credential export | Platform limits and recorder backpressure measured per WatchTarget | Pause/stop on revoked basis, endpoint failure or kill switch; retain received source chunks according to policy | 30-day raw default pending approved policy | Platform adapter boundary permits authorized export or another recorder. |
| JD/Maitu/Douyin operations data | Metrics, actual exposure and external session identity from official API, authorized export or controlled browser | Source-specific credential and DataContract; only minimal fields accepted | Unknown until source contract is approved; budget and polling limits are mandatory | Quarantine unknown schema/time/identity; manual versioned import is the initial fallback | Personal events require restricted classification and deletion propagation | Replace source adapter; immutable standard events and metric revisions remain stable. |
| Platform scheduling and go-live APIs | Validate target account/room availability, platform schedule rules, promotion and inventory state; a future separately authorized flow may submit an approved schedule or open a live session | Backend-only target-scoped credential and GoLiveAuthorization; current local schedule prototype sends nothing externally | Unknown until each platform contract, quota and commercial rule is approved; no polling or submission is enabled now | Keep local plan validation available; fail closed on unavailable target/rule facts and never infer approval from a local plan | Provider account, regional rules and retention of schedule/readback evidence require owner approval | Retain the versioned local schedule/release contract; replace only the platform adapter after contract tests and go-live review. |

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
