from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainUnavailableError, DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository


BASELINE_REDACTION_POLICY_REF = "baseline-sensitive-field-redaction@1"
_FORBIDDEN_KEY_MARKERS = (
    "authorization",
    "cookie",
    "token",
    "password",
    "secret",
    "credential",
    "rawpayload",
)
_PERSONAL_KEY_MARKERS = (
    "email",
    "phone",
    "mobile",
    "userid",
    "openid",
    "orderid",
    "address",
    "commenttext",
)
_NON_SECRET_TOKEN_KEYS = frozenset(
    {
        "maxtokens",
        "inputtokens",
        "outputtokens",
        "totaltokens",
        "reasoningtokens",
        "cachedtokens",
    }
)
_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[^\s,;]+"),
    re.compile(
        r"(?i)(?<![a-z0-9])(?:sk-[a-z0-9_-]{12,}|github_pat_[a-z0-9_]{12,}|"
        r"gh[pousr]_[a-z0-9]{12,}|hf_[a-z0-9]{12,}|AKIA[0-9A-Z]{16}|"
        r"AIza[0-9A-Za-z_-]{35})(?![a-z0-9_-])"
    ),
    re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}(?![\w.-])"),
    re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    value: Any
    context: str
    policy_ref: str
    redacted_paths: tuple[str, ...]
    output_fingerprint: str


def redact_sensitive_fields(
    value: Any,
    *,
    context: str,
    policy_ref: str = BASELINE_REDACTION_POLICY_REF,
    replacement: str = "[REDACTED]",
) -> RedactionResult:
    redacted_paths: list[str] = []

    def normalized_key(key: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(key).lower())

    def redact_string(text: str, path: str) -> str:
        result = text
        for pattern in _VALUE_PATTERNS:
            result, count = pattern.subn(replacement, result)
            if count and path not in redacted_paths:
                redacted_paths.append(path)
        return result

    def visit(item: Any, path: str) -> Any:
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for index, (key, child) in enumerate(item.items()):
                key_text = redact_string(str(key), f"{path}.$key")
                if key_text != str(key):
                    key_text = f"[REDACTED_KEY_{index}]"
                normalized = normalized_key(key)
                child_path = f"{path}.{key_text}"
                forbidden_markers = _FORBIDDEN_KEY_MARKERS + _PERSONAL_KEY_MARKERS
                is_safe_token_counter = (
                    normalized in _NON_SECRET_TOKEN_KEYS
                    and isinstance(child, (int, float))
                    and not isinstance(child, bool)
                )
                if not is_safe_token_counter and any(
                    marker in normalized for marker in forbidden_markers
                ):
                    result[key_text] = replacement
                    redacted_paths.append(child_path)
                else:
                    result[key_text] = visit(child, child_path)
            return result
        if isinstance(item, (list, tuple)):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(item)]
        if isinstance(item, str):
            return redact_string(item, path)
        return item

    redacted = visit(value, "$")
    return RedactionResult(
        value=redacted,
        context=context,
        policy_ref=policy_ref,
        redacted_paths=tuple(sorted(set(redacted_paths))),
        output_fingerprint=canonical_fingerprint(redacted),
    )


class FieldRedactionService:
    def __init__(
        self,
        repository: PrivacyGovernanceRepository,
        *,
        policy_code: str = "baseline-sensitive-field-redaction",
    ) -> None:
        self.repository = repository
        self.policy_code = policy_code

    def redact(self, value: Any, *, context: str) -> RedactionResult:
        try:
            policy = self.repository.get_active_redaction_policy(self.policy_code)
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "REDACTION_POLICY_UNAVAILABLE",
                "Redaction policy is unavailable; the artifact cannot be produced",
            ) from exc
        if policy is None:
            raise DomainUnavailableError(
                "REDACTION_POLICY_UNAVAILABLE",
                "No active redaction policy is available",
            )
        if context not in set(policy["contexts"]):
            raise DomainValidationError(
                "REDACTION_CONTEXT_DENIED",
                "The active redaction policy does not cover this artifact context",
            )
        return redact_sensitive_fields(
            value,
            context=context,
            policy_ref=f"{policy['policy_code']}@{policy['revision_number']}",
            replacement=policy["replacement"],
        )
