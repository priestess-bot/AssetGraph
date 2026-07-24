# Stable Error And Operational State Contract

Status: active baseline, Phase 0

## Response compatibility

Every non-success HTTP response keeps the legacy top-level `detail` field and
adds an `error` object with these stable fields:

| Field | Meaning |
| --- | --- |
| `code` | Stable machine rule code; never derive workflow behavior from message text. |
| `state` | `error`, `warning`, `insufficient_data`, `stale`, or `reconcile_required`. |
| `message` | Human-readable summary; not a programmatic contract. |
| `impact` | What did not happen, may have happened, or remains unavailable. |
| `evidence` | Request path and trace reference; domain APIs may add artifact/rule references. |
| `next_step` | Safe operator action. |
| `retryable` | Whether an unchanged automatic retry is allowed. |
| `trace_id` | OpenTelemetry trace ID when one exists. |

Unknown exceptions never expose stack traces, credentials, raw personal data,
provider payloads, or arbitrary internal exception values.

## State semantics

- `error`: the operation failed and no success may be shown.
- `warning`: the requested result is delayed or degraded; it is not success.
- `insufficient_data`: qualified evidence is missing; it is neither failure nor a valid result.
- `stale`: the caller's revision/precondition is outdated and no stale write was accepted.
- `reconcile_required`: an external effect may have happened; blind replay is prohibited.

The Console renders all five states visibly. `warning`, `stale`,
`insufficient_data`, and `reconcile_required` never use the success treatment.

## Baseline codes

`REQUEST_INVALID`, `AUTHENTICATION_REQUIRED`, `AUTHORIZATION_DENIED`,
`RESOURCE_NOT_FOUND`, `CONCURRENT_MODIFICATION`, `STALE_REVISION`,
`PRECONDITION_FAILED`, `REQUEST_VALIDATION_FAILED`, `RATE_LIMITED`,
`INSUFFICIENT_DATA`, `RECONCILE_REQUIRED`, `INTERNAL_ERROR`,
`UPSTREAM_BAD_GATEWAY`, `DEPENDENCY_UNAVAILABLE`, and `DEPENDENCY_TIMEOUT` are
reserved global codes. Domain APIs may return a more specific uppercase code in
their structured exception detail; changing the meaning of a published code
requires a versioned contract change.
