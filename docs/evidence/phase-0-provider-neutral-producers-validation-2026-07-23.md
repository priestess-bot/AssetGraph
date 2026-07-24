# Phase 0 Provider-Neutral Producers Validation

- Date: 2026-07-23
- Checklist item: `CHK-0113`
- Scope: online structured generation, material vision, live ASR/OCR/layout
  inference/template aggregation, provider evidence, and public producer contracts
- Result: technical contract complete; production processor approvals and
  deployment configuration are not claimed by this report

## Implemented boundary

All current online producers use a `ModelCapability` plus immutable
`strategy_revision`. Supplier adapter/model/response/usage details are absent from
domain requests, responses, workflow identities, and new producer rows. They are
kept inside a confidential `provider-invocation-evidence.v1` ArtifactRef payload.

| Producer | Strategy revision | Domain evidence field |
| --- | --- | --- |
| Maitu creative plan | `maitu.creative-plan.v2` | `generation_invocation_evidence_ref` |
| Material semantic observation | `material.semantic-observation.v2` | `invocation_evidence_ref` |
| Live frame sampling | `live.frame-sampling.v2` | local deterministic, no external evidence |
| Live ASR | `live.asr.zh.v2` | `invocation_evidence_ref` |
| Live OCR | `live.ocr.v2` | `invocation_evidence_ref` |
| Live layout inference | `live.layout-inference.v2` | `invocation_evidence_ref` |
| Live template aggregation | `live.template-aggregation.v2` | `invocation_evidence_ref` |

Migrations `043_provider_neutral_producer_contracts.sql` and
`044_provider_neutral_analysis_identity.sql` provide the durable projection and
database checks. Existing supplier fields are nullable, legacy-only compatibility
data. New non-test external results require an evidence reference, and succeeded
material analyses also require prompt revision plus input/output fingerprints.

## Fail-closed and privacy evidence

- External bindings require a configured processing region and the governed
  `ExternalProcessorService` before invocation.
- Minimum-field projection and an append-only processor call audit occur before an
  external request can leave the service boundary.
- Structured prompt payloads remain structured until recursive key/value redaction
  is complete; the adapter serializes only the redacted payload.
- Provider output is recursively redacted and validated against the strategy JSON
  Schema before it can be returned.
- Supplier details are stored in a confidential, content-addressed artifact with
  `critical-audit-evidence` retention; public metadata contains only capability,
  strategy revision, and fingerprints.
- Evidence object/registry failure prevents the domain result from escaping, and a
  failed ArtifactRef registration rolls back its database transaction.
- Live workers authorize the strategy first, persist invocation evidence second,
  and only then submit completion. Completion recursively rejects supplier
  invocation metadata.

## Verification record

The following checks completed on 2026-07-23:

| Check | Result |
| --- | --- |
| Fresh PostgreSQL migration apply | `migrations_total=44 applied=44` for `001` through `044` |
| Backend full regression | `625 passed in 24.83s` |
| Backend Ruff | `All checks passed` for `app` and `tests` |
| Live-research worker regression | `30 passed in 0.21s` |
| Live-research worker Ruff | `All checks passed` for `src` and `tests` |
| Frontend regression | `32 passed` across 9 test files |
| Frontend typecheck | `tsc -b` passed |
| Production frontend builds | Console, Maitu, and live-research Vite builds passed |
| Runtime health and Console | `/health` returned `ok`; `/console/` returned HTTP 200 |
| Runtime OpenAPI supplier-field scan | empty result for all four producer request/response contract groups |

The runtime OpenAPI keys verified were:

- `AnalysisRunCreate`: analysis identity, input fingerprint, parameters, and
  `strategy_revision` only;
- `AnalysisRunRead`: adds `invocation_evidence_ref` and neutral execution fields;
- `WorkbenchPlanRevisionRead`: generation strategy, prompt, fingerprints, and
  invocation evidence only;
- `VideoAnalysisComplete` and `VideoAnalysisRead`: analysis strategy, prompt,
  fingerprints, and invocation evidence only.

Focused regression additionally covered nested `open_id` redaction before message
serialization, evidence-sink exceptions, ArtifactRef transaction rollback,
processor authorization/evidence binding, evidence-before-completion ordering, and
recursive supplier metadata rejection.

## Known deployment prerequisites

No real third-party model call or production approval was used as automated test
evidence. Production remains fail closed until operations supplies and approves:

- `DEEPSEEK_PROCESSING_REGION` and `OPENAI_PROCESSING_REGION`;
- active external-processor terms for the configured processor codes and regions;
- secret-reference-backed credentials and runtime API keys;
- reachable, versioned evidence object storage and its retention controls; and
- production data/security approval for the intended classifications and regions.

The named Gemini workbench remains a manual web JSON import and human conflict
resolution path; AssetGraph makes no Gemini API call there. Legacy supplier columns
and imported values remain descriptive compatibility evidence only and must be
removed under their separately measured compatibility retirement gates.

## References

- `docs/architecture/provider-adapter-boundary.md`
- `docs/operations/external-platform-register.md`
- `docs/reproducibility.md`
- `backend/migrations/043_provider_neutral_producer_contracts.sql`
- `backend/migrations/044_provider_neutral_analysis_identity.sql`
- `backend/tests/test_provider_neutral_contracts.py`
- `backend/tests/test_provider_router.py`
- `backend/tests/test_provider_evidence_routes_postgres.py`
- `workers/live-research/tests/test_work_heartbeat.py`
