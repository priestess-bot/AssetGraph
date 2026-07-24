# Provider Adapter Boundary

## Status

This is the implemented Phase 0 boundary for online model producers. The domain
contracts are supplier-neutral; supplier bindings remain infrastructure
configuration and classified evidence.

## Domain contract

Domain commands identify an immutable `strategy_revision` and a
`ModelCapability`. They do not accept or return a supplier name, supplier model,
endpoint, response ID, usage record, or latency. A successful online result
contains:

- the strategy and input/output schema revisions;
- redacted content plus canonical input/output fingerprints; and
- an `invocation_evidence_ref` to a durable ArtifactRef.

The shared capability contract covers structured generation, speech-to-text,
OCR, image/video understanding, embedding, and reranking. Output is checked
against the strategy JSON Schema before evidence or domain state can be written.

## Infrastructure binding and processor governance

`ProviderRouter` resolves one strategy revision to one infrastructure adapter and
requested model. Every external binding declares its processor code, approved
processing region, purpose, allowed data classifications, and canonical input
limit. `ExternalProcessorService` applies the minimum-field projection and writes
an append-only processor call audit before the adapter can run.

Both `DEEPSEEK_PROCESSING_REGION` and `OPENAI_PROCESSING_REGION` intentionally
default to unset. An external producer is unavailable until deployment supplies
an approved region, active processor terms, a secret-reference-backed credential,
and reachable evidence storage. Missing strategy bindings, guard configuration,
terms, region, credentials, adapter availability, valid output, or evidence all
fail closed.

Prompt inputs and model results pass through the versioned baseline redaction
policy. Structured-generation inputs remain structured until this pass completes;
only the adapter serializes the redacted user payload into a provider message.

## Invocation evidence

Supplier adapter/model identifiers, provider response IDs, usage, latency,
processor audit code, trace context, redaction counts, and canonical fingerprints
are stored only in a confidential
`provider-invocation-evidence.v1` content-addressed artifact with the
`critical-audit-evidence` retention policy. Its public ArtifactRef metadata holds
only capability, strategy revision, and fingerprints. A domain result is not
released if object storage or ArtifactRef registration fails; a failed registry
transaction is rolled back.

## Producer projections

The migrated producers use these neutral identities:

| Producer | Domain strategy | Durable projection |
| --- | --- | --- |
| Maitu creative plan | `maitu.creative-plan.v2` | `generation_strategy_revision`, `generation_invocation_evidence_ref` |
| Material semantic observation | `material.semantic-observation.v2` | `analysis_strategy_revision`, `invocation_evidence_ref`, prompt/input/output fingerprints |
| Live ASR | `live.asr.zh.v2` | `strategy_revision`, `invocation_evidence_ref` |
| Live OCR | `live.ocr.v2` | `strategy_revision`, `invocation_evidence_ref` |
| Live layout inference | `live.layout-inference.v2` | `strategy_revision`, `invocation_evidence_ref` |
| Live template aggregation | `live.template-aggregation.v2` | `strategy_revision`, `invocation_evidence_ref` |

Frame sampling is a local deterministic strategy and does not require external
invocation evidence. Test strategies use the `test.*` namespace and cannot be
mistaken for production strategies.

The live-analysis worker uses a two-step protocol. It obtains a strategy-bound
processor authorization before the provider call, then persists evidence bound to
that processor audit before sending completion. Completion rejects recursive
supplier metadata, and a missing evidence reference prevents `succeeded` state.

## Compatibility boundary

Migrations `043` and `044` classify old rows under explicit `legacy.*` strategy
revisions and retain old supplier columns as nullable, descriptive compatibility
data. New strategy rows must leave those columns null. Database checks enforce the
neutral contract, evidence requirement, and complete material-analysis prompt and
fingerprint identity. Public schemas, current producers, business decisions, and
RunManifest references do not consume legacy supplier fields.

The Gemini screen is a labelled manual web JSON import and conflict-resolution
workflow. AssetGraph does not call a Gemini API in that path. Its submitted JSON is
legacy/manual secondary observation evidence, not an online provider producer and
not a way to bypass the router. Any future automated Gemini integration must add a
governed adapter binding and satisfy this same contract before being enabled.
