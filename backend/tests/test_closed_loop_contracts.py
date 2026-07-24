from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.contracts import (
    Capability,
    EventEnvelope,
    RationalTime,
    SessionTimeRange,
    canonical_fingerprint,
    canonical_json_bytes,
)
from app.domain.errors import DomainAuthorizationError, DomainConflictError, DomainValidationError
from app.domain.state_machines import RELEASE_STATE_MACHINE, WORKFLOW_STATE_MACHINE
from app.services.authorization import consume_authorization_claim, issue_authorization_claim
from app.services.manifests import (
    explain_manifest_difference,
    seal_run_manifest,
    verify_sealed_manifest,
)


def _manifest(**overrides: object) -> dict:
    result = {
        "input_revisions": [{"code": "CONTENT-1", "revision": 1}],
        "input_artifacts": [],
        "inventory_refs": [],
        "material_refs": [],
        "constraint_refs": [],
        "rights_refs": [],
        "template_refs": [],
        "fact_refs": [{"code": "FACT-1", "revision": 2}],
        "content_refs": [{"code": "SCRIPT-1", "revision": 1}],
        "model_strategies": [{"capability": "script_generation", "revision": "writer.v1"}],
        "prompt_revisions": ["writer-prompt.v2"],
        "code_revision": "git:abc123",
        "tool_versions": [{"tool": "ffmpeg", "version": "7.0"}],
        "random_seed": 42,
        "environment": {"python": "3.11"},
    }
    result.update(overrides)
    return result


def test_canonical_fingerprint_is_order_independent_and_type_stable() -> None:
    left = {
        "when": datetime(2026, 7, 23, 1, 2, 3, tzinfo=UTC),
        "amount": Decimal("1.20"),
        "items": {"b", "a"},
    }
    right = {
        "items": {"a", "b"},
        "amount": Decimal("1.20"),
        "when": datetime(2026, 7, 23, 1, 2, 3, tzinfo=UTC),
    }

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_fingerprint(left) == canonical_fingerprint(right)
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_fingerprint({"when": datetime(2026, 7, 23)})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_fingerprint({"bad": float("nan")})


def test_time_contracts_keep_frame_and_session_domains_distinct() -> None:
    frame_time = RationalTime(
        value_numerator=50,
        value_denominator=1,
        rate_numerator=25,
        rate_denominator=1,
    )
    assert frame_time.seconds == 2
    assert SessionTimeRange(start_ms=0, end_ms=2000).model_dump() == {"start_ms": 0, "end_ms": 2000}
    with pytest.raises(ValidationError, match="end_ms must be greater"):
        SessionTimeRange(start_ms=1000, end_ms=1000)


def test_event_envelope_requires_explicit_delete_and_aware_times() -> None:
    now = datetime.now(UTC)
    event = EventEnvelope(
        event_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        source_system="jd",
        source_event_id="source-1",
        schema_version="jd-event.v1",
        operation="delete",
        event_time=now,
        processing_time=now,
        payload={},
        tombstone=True,
    )
    assert event.tombstone is True
    with pytest.raises(ValidationError, match="delete events must be tombstones"):
        EventEnvelope.model_validate({**event.model_dump(), "tombstone": False})


def test_state_machines_return_stable_conflict_details() -> None:
    WORKFLOW_STATE_MACHINE.require_transition("queued", "running")
    RELEASE_STATE_MACHINE.require_transition("approved", "delivery_pending")
    with pytest.raises(DomainConflictError) as error:
        RELEASE_STATE_MACHINE.require_transition("candidate", "delivered")
    assert error.value.code == "STATE_TRANSITION_NOT_ALLOWED"
    assert error.value.details["allowed"] == ["revoked", "validating"]


def test_run_manifest_is_signed_reproducible_and_diffable() -> None:
    key = b"test-signing-key"
    first = seal_run_manifest(_manifest(), signing_key=key, key_id="test-key")
    replay = seal_run_manifest(_manifest(), signing_key=key, key_id="test-key")
    changed = seal_run_manifest(
        _manifest(random_seed=43),
        signing_key=key,
        key_id="test-key",
        output_refs=[{"artifact": "A"}],
    )

    assert first == replay
    assert verify_sealed_manifest(first, signing_key=key) is True
    assert explain_manifest_difference(first, changed) == {
        "same_input": False,
        "same_output": False,
        "same_manifest": False,
        "changed_sections": ["random_seed"],
    }
    tampered = replace(first, manifest=_manifest(random_seed=99))
    assert verify_sealed_manifest(tampered, signing_key=key) is False
    with pytest.raises(DomainValidationError) as error:
        seal_run_manifest({"environment": {}}, signing_key=key, key_id="test-key")
    assert error.value.code == "RUN_MANIFEST_SCHEMA_INVALID"


def test_authorization_is_short_lived_single_use_and_bound_to_target_hash_and_capability() -> None:
    now = datetime(2026, 7, 23, 1, 0, tzinfo=UTC)
    claim, raw_token = issue_authorization_claim(
        authorization_code="AUTH-1",
        principal_id="worker-a",
        capability=Capability.WRITE_DRAFT,
        target_type="maitu_live_room",
        target_id="40147",
        plan_or_release_hash="a" * 64,
        site_fingerprint="b" * 64,
        ttl=timedelta(minutes=5),
        now=now,
    )
    consumed = consume_authorization_claim(
        claim,
        raw_token=raw_token,
        principal_id="worker-a",
        capability=Capability.WRITE_DRAFT,
        target_type="maitu_live_room",
        target_id="40147",
        plan_or_release_hash="a" * 64,
        site_fingerprint="b" * 64,
        now=now + timedelta(minutes=1),
    )
    assert consumed.status == "consumed"
    with pytest.raises(DomainAuthorizationError) as replay:
        consume_authorization_claim(
            consumed,
            raw_token=raw_token,
            principal_id="worker-a",
            capability=Capability.WRITE_DRAFT,
            target_type="maitu_live_room",
            target_id="40147",
            plan_or_release_hash="a" * 64,
            site_fingerprint="b" * 64,
            now=now + timedelta(minutes=2),
        )
    assert replay.value.code == "AUTHORIZATION_NOT_ACTIVE"

    for mismatch in (
        {"target_id": "99999"},
        {"plan_or_release_hash": "c" * 64},
        {"capability": Capability.UPLOAD_ASSET},
        {"site_fingerprint": "d" * 64},
    ):
        kwargs = {
            "raw_token": raw_token,
            "principal_id": "worker-a",
            "capability": Capability.WRITE_DRAFT,
            "target_type": "maitu_live_room",
            "target_id": "40147",
            "plan_or_release_hash": "a" * 64,
            "site_fingerprint": "b" * 64,
            "now": now + timedelta(minutes=1),
        }
        kwargs.update(mismatch)
        with pytest.raises(DomainAuthorizationError):
            consume_authorization_claim(claim, **kwargs)

    with pytest.raises(DomainAuthorizationError) as disabled:
        issue_authorization_claim(
            authorization_code="AUTH-LIVE",
            principal_id="worker-a",
            capability=Capability.GO_LIVE,
            target_type="maitu_live_room",
            target_id="40147",
            plan_or_release_hash="a" * 64,
            site_fingerprint="b" * 64,
            ttl=timedelta(minutes=1),
            now=now,
        )
    assert disabled.value.code == "GO_LIVE_CAPABILITY_DISABLED"
