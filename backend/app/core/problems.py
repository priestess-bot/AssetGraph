from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class ProblemState(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"
    RECONCILE_REQUIRED = "reconcile_required"


@dataclass(frozen=True)
class ProblemRule:
    code: str
    state: ProblemState
    impact: str
    next_step: str
    retryable: bool


_STATUS_RULES: dict[int, ProblemRule] = {
    400: ProblemRule("REQUEST_INVALID", ProblemState.ERROR, "The command was not accepted.", "Correct the request and retry.", False),
    401: ProblemRule("AUTHENTICATION_REQUIRED", ProblemState.ERROR, "The requested data or command was not accessed.", "Sign in with an authorized identity and retry.", False),
    403: ProblemRule("AUTHORIZATION_DENIED", ProblemState.ERROR, "The requested operation was blocked.", "Request the required role or choose an allowed operation.", False),
    404: ProblemRule("RESOURCE_NOT_FOUND", ProblemState.ERROR, "The requested entity was not loaded.", "Verify the stable entity link or return to its list.", False),
    409: ProblemRule("CONCURRENT_MODIFICATION", ProblemState.STALE, "No change was committed from the stale request.", "Reload the latest revision, review the diff, and retry explicitly.", False),
    410: ProblemRule("RESOURCE_GONE", ProblemState.ERROR, "The retired entity cannot be used.", "Open the replacement entity or migration report.", False),
    412: ProblemRule("PRECONDITION_FAILED", ProblemState.STALE, "The command precondition no longer matches.", "Reload evidence and repeat preflight before retrying.", False),
    422: ProblemRule("REQUEST_VALIDATION_FAILED", ProblemState.ERROR, "No command was executed.", "Correct the indicated request fields and retry.", False),
    429: ProblemRule("RATE_LIMITED", ProblemState.WARNING, "The operation is delayed by a quota.", "Wait for the stated retry interval or reduce request rate.", True),
    500: ProblemRule("INTERNAL_ERROR", ProblemState.ERROR, "The operation did not complete.", "Use the trace reference to investigate before retrying.", False),
    502: ProblemRule("UPSTREAM_BAD_GATEWAY", ProblemState.WARNING, "An upstream response could not be verified.", "Check upstream health and reconcile before retrying.", True),
    503: ProblemRule("DEPENDENCY_UNAVAILABLE", ProblemState.WARNING, "The operation is temporarily unavailable.", "Restore the dependency or use the documented degraded path.", True),
    504: ProblemRule("DEPENDENCY_TIMEOUT", ProblemState.RECONCILE_REQUIRED, "The external outcome is unknown.", "Reconcile external state before issuing another command.", False),
}


def _text_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key in ("message", "detail", "error"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return "The request could not be completed."


def _explicit_code(detail: Any) -> str | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get("code")
    if isinstance(value, str) and _CODE_PATTERN.fullmatch(value):
        return value
    return None


def classify_problem(status_code: int, detail: Any) -> ProblemRule:
    text = _text_detail(detail).lower()
    base = _STATUS_RULES.get(
        status_code,
        ProblemRule("HTTP_ERROR", ProblemState.ERROR, "The operation did not complete.", "Review the evidence and retry only when safe.", False),
    )
    if "insufficient_data" in text or "insufficient data" in text:
        return ProblemRule(
            "INSUFFICIENT_DATA",
            ProblemState.INSUFFICIENT_DATA,
            "There is not enough qualified evidence to produce the requested result.",
            "Collect the missing evidence and run the evaluation again.",
            False,
        )
    if "reconcile" in text or "outcome is unknown" in text:
        return ProblemRule(
            "RECONCILE_REQUIRED",
            ProblemState.RECONCILE_REQUIRED,
            "The external side effect may have occurred and is not safe to replay.",
            "Read back external state and complete reconciliation before retrying.",
            False,
        )
    if status_code in (409, 412) and any(word in text for word in ("stale", "lease", "revision", "checkpoint")):
        return ProblemRule(
            "STALE_REVISION",
            ProblemState.STALE,
            "No change was committed from the stale request.",
            "Reload the latest revision and evidence, inspect the diff, and issue a new command.",
            False,
        )
    explicit_code = _explicit_code(detail)
    if explicit_code is None:
        return base
    return ProblemRule(explicit_code, base.state, base.impact, base.next_step, base.retryable)


def problem_payload(
    *,
    status_code: int,
    detail: Any,
    request_path: str,
    trace_id: str | None,
) -> dict[str, Any]:
    rule = classify_problem(status_code, detail)
    evidence = [{"kind": "request", "ref": request_path}]
    if trace_id:
        evidence.append({"kind": "trace", "ref": trace_id})
    return {
        "code": rule.code,
        "state": rule.state.value,
        "message": _text_detail(detail),
        "impact": rule.impact,
        "evidence": evidence,
        "next_step": rule.next_step,
        "retryable": rule.retryable,
        "trace_id": trace_id,
    }
