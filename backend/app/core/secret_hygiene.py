from __future__ import annotations

import re
from typing import Any, Iterable

_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "cookie",
    "token",
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+\S+")
_UUID_TOKEN_PATTERN = re.compile(
    r"(?i)(?:[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})"
)
_PROVIDER_TOKEN_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"sk-[a-z0-9_-]{20,}|"
    r"github_pat_[a-z0-9_]{20,}|"
    r"gh[pousr]_[a-z0-9]{20,}|"
    r"hf_[a-z0-9]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{35}"
    r")(?![a-z0-9_-])"
)


def contains_durable_secret(candidate: Any, *, forbidden_values: Iterable[str] = ()) -> bool:
    """Reject credentials in arbitrary durable JSON-like keys or values.

    UUID-shaped values are rejected because retry claim tokens are UUIDs and must
    never enter reconciliation summaries, evidence, receipts, or responses.
    Explicit forbidden values cover deployment-specific operator credentials.
    """

    forbidden = tuple(value for value in forbidden_values if value)

    def contains(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
                if any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS):
                    return True
                if contains(key_text) or contains(item):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            return any(contains(item) for item in value)
        if not isinstance(value, str):
            return False
        return bool(
            any(secret in value for secret in forbidden)
            or _BEARER_PATTERN.search(value)
            or _UUID_TOKEN_PATTERN.search(value)
            or _PROVIDER_TOKEN_PATTERN.search(value)
        )

    return contains(candidate)
