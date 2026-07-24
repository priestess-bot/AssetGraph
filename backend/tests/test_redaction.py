from __future__ import annotations

import os

import psycopg
import pytest

from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.redaction import FieldRedactionService, redact_sensitive_fields


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")


def test_recursive_redaction_removes_credentials_and_personal_fields_without_mutating_input() -> None:
    source = {
        "authorization": "Bearer top-secret-token",
        "nested": {
            "user_id": "user-123",
            "safe": "Contact person@example.test or +86 13800138000",
        },
        "items": [{"cookie_value": "session=private"}, "sk-abcdefghijklmnopqrstuv"],
    }

    result = redact_sensitive_fields(source, context="log")

    serialized = str(result.value)
    for forbidden in (
        "top-secret-token",
        "user-123",
        "person@example.test",
        "13800138000",
        "session=private",
        "sk-abcdefghijklmnopqrstuv",
    ):
        assert forbidden not in serialized
    assert source["nested"]["user_id"] == "user-123"
    assert result.redacted_paths
    assert len(result.output_fingerprint) == 64


def test_numeric_token_counters_survive_without_weakening_credential_redaction() -> None:
    result = redact_sensitive_fields(
        {
            "max_tokens": 5000,
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "api_token": "private-provider-token",
            "max_tokens_override": "must-still-be-redacted",
        },
        context="prompt",
    )

    assert result.value["max_tokens"] == 5000
    assert result.value["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert result.value["api_token"] == "[REDACTED]"
    assert result.value["max_tokens_override"] == "[REDACTED]"


@pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
def test_active_policy_covers_log_screenshot_prompt_and_model_response() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        service = FieldRedactionService(PrivacyGovernanceRepository(connection))
        for context in ("log", "screenshot", "prompt", "model_response"):
            result = service.redact(
                {"ocr_text": "Call 13800138000", "open_id": "private-open-id"},
                context=context,
            )
            assert result.policy_ref == "baseline-sensitive-field-redaction@1"
            assert "13800138000" not in str(result.value)
            assert "private-open-id" not in str(result.value)
