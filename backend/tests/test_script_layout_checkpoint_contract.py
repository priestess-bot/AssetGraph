from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from app.repositories import maitu as maitu_repository

from app.repositories.maitu import BuildPlanCheckpointConflictError, MaituMaterialSlotRepository
from app.schemas.maitu import (
    MaituScriptLayoutExecutionCheckpointBeginCreate,
    MaituScriptLayoutExecutionCheckpointCompleteCreate,
    MaituScriptLayoutExecutionCheckpointInvalidateCreate,
    MaituScriptLayoutExecutionCheckpointReconcileCreate,
    MaituScriptLayoutExecutionFinalizeCreate,
    MaituScriptLayoutExecutionStartCreate,
)

FINGERPRINT = "a" * 64
ATTEMPT_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPLETION_ID = UUID("22222222-2222-4222-8222-222222222222")
START_REQUEST_ID = UUID("33333333-3333-4333-8333-333333333333")
LEASE_TOKEN = UUID("44444444-4444-4444-8444-444444444444")
RECONCILIATION_ID = UUID("55555555-5555-4555-8555-555555555555")
FINALIZATION_ID = UUID("66666666-6666-4666-8666-666666666666")
READBACK_ATTESTATION_KEY = "test-readback-attestation-key-32-bytes"


def test_readback_attestation_rejects_self_reported_or_tampered_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        maitu_repository.settings,
        "maitu_readback_attestation_key",
        SecretStr(READBACK_ATTESTATION_KEY),
    )
    evidence = {"verified": True, "clip_id": 410001}
    attested_payload = {
        "build_plan_code": "MT-BUILD-1",
        "execution_code": "MT-EXEC-1",
        "operation_index": 1,
        "operation_fingerprint": FINGERPRINT,
        "attempt_id": str(ATTEMPT_ID),
        "lease_token": str(LEASE_TOKEN),
        "lease_version": 1,
        "completion_id": str(COMPLETION_ID),
        "evidence": evidence,
    }
    signature = hmac.new(
        READBACK_ATTESTATION_KEY.encode("utf-8"),
        json.dumps(attested_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    MaituMaterialSlotRepository._require_readback_attestation(
        attested_payload,
        {
            **evidence,
            "readback_attestation_algorithm": "hmac-sha256-v1",
            "readback_attestation": signature,
        },
    )
    with pytest.raises(BuildPlanCheckpointConflictError, match="invalid"):
        MaituMaterialSlotRepository._require_readback_attestation(
            {**attested_payload, "operation_index": 2},
            {
                **evidence,
                "readback_attestation_algorithm": "hmac-sha256-v1",
                "readback_attestation": signature,
            },
        )
    with pytest.raises(BuildPlanCheckpointConflictError, match="missing"):
        MaituMaterialSlotRepository._require_readback_attestation(attested_payload, evidence)


def test_invalidation_rejects_client_supplied_readback_attestation() -> None:
    with pytest.raises(ValidationError, match="attestation"):
        MaituScriptLayoutExecutionCheckpointInvalidateCreate.model_validate(
            {
                "operation_fingerprint": FINGERPRINT,
                "attempt_id": ATTEMPT_ID,
                "lease_token": LEASE_TOKEN,
                "lease_version": 1,
                "evidence": {
                    "verified": True,
                    "checkpoint_invalid": True,
                    "readback_attestation": "a" * 64,
                },
            }
        )


def start_payload() -> dict:
    return {
        "start_request_id": START_REQUEST_ID,
        "run_attempt_id": ATTEMPT_ID,
        "source_plan_fingerprint": "c" * 64,
        "target_live_room_id": "47000002",
        "operations": [
            {
                "operation_index": 0,
                "intent": {
                    "operation_type": "preflight_content_build_plan",
                    "status": "ready",
                    "target_live_room_id": "47000002",
                },
            },
            {"operation_index": 1, "intent": {"operation_type": "create_scene", "scene_index": 1}},
        ],
    }


def test_script_layout_execution_start_contract_requires_fenced_canonical_manifest() -> None:
    payload = MaituScriptLayoutExecutionStartCreate.model_validate(start_payload())

    assert payload.mode == "script_layout_draft"
    assert payload.checkpoint_contract == "script_layout_checkpoint_v1"
    assert payload.operations[0].intent["operation_type"] == "preflight_content_build_plan"
    with pytest.raises(ValidationError, match="contiguous"):
        MaituScriptLayoutExecutionStartCreate.model_validate(
            {
                **start_payload(),
                "operations": [{"operation_index": 1, "intent": {"operation_type": "create_scene"}}],
            }
        )

    with pytest.raises(ValidationError, match="non-finite"):
        MaituScriptLayoutExecutionStartCreate.model_validate(
            {
                **start_payload(),
                "operations": [{"operation_index": 0, "intent": {"x": float("nan")}}],
            }
        )


def test_script_layout_manifest_accepts_backend_bound_public_material_urls() -> None:
    payload = start_payload()
    payload["operations"][1]["intent"].update(
        {
            "source_material_url": (
                "https://mytwins-static.oss-cn-hangzhou.aliyuncs.com/images/"
                "b565b64460bb99e0332e494a68cc3c8ed084ade9.jpeg?x-oss-process=image/resize,w_1080"
            ),
            "source_cover_url": "https://mtc.maituai.com/image/20260618_165812_cover.png",
        }
    )

    parsed = MaituScriptLayoutExecutionStartCreate.model_validate(payload)

    assert parsed.operations[1].intent["source_material_url"].startswith("https://")


def test_checkpoint_complete_requires_fence_verified_evidence_and_matching_result_identity() -> None:
    payload = MaituScriptLayoutExecutionCheckpointCompleteCreate.model_validate(
        {
            "operation_fingerprint": FINGERPRINT,
            "attempt_id": ATTEMPT_ID,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "completion_id": COMPLETION_ID,
            "result_summary": "scene created and read back",
            "evidence": {
                "verified": True,
                "operation_applied": True,
                "operation_index": 2,
                "operation_type": "create_scene",
                "scene_index": 1,
                "clip_id": 416426,
                "go_live_clicked": False,
            },
            "operation_result": {
                "operation_index": 2,
                "operation_type": "create_scene",
                "operation_name": "新建场景：促单",
                "scene_index": 1,
                "scene_name": "促单",
                "clip_id": 416426,
                "action_type": "create_draft_scene",
                "status": "completed",
                "details": {"go_live_clicked": False},
            },
        }
    )

    assert payload.evidence["verified"] is True
    assert payload.lease_version == 1

    with pytest.raises(ValidationError, match="verified"):
        MaituScriptLayoutExecutionCheckpointCompleteCreate.model_validate(
            {**payload.model_dump(), "evidence": {"verified": False}}
        )


def test_checkpoint_complete_accepts_backend_bound_public_material_url() -> None:
    public_url = (
        "https://mytwins-static.oss-cn-hangzhou.aliyuncs.com/images/"
        "316028d179bffa34ef5e1796b7ae6340c8d47d1c.png?x-oss-process=style/max_width_720"
    )
    payload = MaituScriptLayoutExecutionCheckpointCompleteCreate.model_validate(
        {
            "operation_fingerprint": FINGERPRINT,
            "attempt_id": ATTEMPT_ID,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "completion_id": COMPLETION_ID,
            "result_summary": "material inserted and read back",
            "evidence": {
                "verified": True,
                "operation_applied": True,
                "operation_index": 2,
                "operation_type": "insert_asset_layer",
                "source_material_url": public_url,
            },
            "operation_result": {
                "operation_index": 2,
                "operation_type": "insert_asset_layer",
                "status": "completed",
                "details": {"source_material_url": public_url},
            },
        }
    )

    assert payload.evidence["source_material_url"] == public_url


def test_checkpoint_complete_accepts_public_script_content_hashes() -> None:
    script_hash = "a" * 64
    payload = MaituScriptLayoutExecutionCheckpointCompleteCreate.model_validate(
        {
            "operation_fingerprint": FINGERPRINT,
            "attempt_id": ATTEMPT_ID,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "completion_id": COMPLETION_ID,
            "result_summary": "script written and read back",
            "evidence": {
                "verified": True,
                "operation_applied": True,
                "operation_index": 6,
                "operation_type": "write_script",
                "script_sha256": script_hash,
                "expected_script_sha256": script_hash,
            },
            "operation_result": {
                "operation_index": 6,
                "operation_type": "write_script",
                "status": "completed",
                "details": {"go_live_clicked": False},
            },
        }
    )

    assert payload.evidence["script_sha256"] == script_hash


def test_checkpoint_begin_and_reconcile_contracts_are_fenced_secret_free_and_explicit() -> None:
    begin = MaituScriptLayoutExecutionCheckpointBeginCreate.model_validate(
        {
            "operation_fingerprint": FINGERPRINT,
            "attempt_id": ATTEMPT_ID,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
        }
    )
    assert begin.attempt_id == ATTEMPT_ID

    reconcile = MaituScriptLayoutExecutionCheckpointReconcileCreate.model_validate(
        {
            "operation_fingerprint": FINGERPRINT,
            "reconciliation_id": RECONCILIATION_ID,
            "reconciled_attempt_id": ATTEMPT_ID,
            "resolution": "confirmed_not_applied",
            "resolution_summary": "authoritative room readback found no matching scene",
            "evidence": {"verified": True, "operation_applied": False, "go_live_clicked": False},
        }
    )
    assert reconcile.resolution == "confirmed_not_applied"

    with pytest.raises(ValidationError, match="operation_applied"):
        MaituScriptLayoutExecutionCheckpointReconcileCreate.model_validate(
            {**reconcile.model_dump(), "resolution": "confirmed_completed"}
        )


def test_finalize_contract_has_stable_identity_and_cannot_smuggle_operation_results() -> None:
    payload = MaituScriptLayoutExecutionFinalizeCreate.model_validate(
        {
            "finalization_id": FINALIZATION_ID,
            "run_attempt_id": ATTEMPT_ID,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "execution_status": "completed_with_manual_review",
            "result_summary": "draft complete",
            "ready_for_go_live": False,
            "manual_review_required": True,
        }
    )
    assert payload.mode == "script_layout_draft"

    with pytest.raises(ValidationError):
        MaituScriptLayoutExecutionFinalizeCreate.model_validate(
            {**payload.model_dump(), "operation_results": []}
        )


def test_preflight_terminal_evidence_requires_authoritative_working_room_receipt() -> None:
    checkpoint = {
        "effect_class": "read_only",
        "operation_type": "preflight_content_build_plan",
        "intent_snapshot": {"operation_type": "preflight_content_build_plan"},
    }
    operation_result = {"operation_type": "preflight_content_build_plan", "status": "completed"}
    generic = {"verified": True, "operation_applied": False, "no_side_effect": True}

    with pytest.raises(BuildPlanCheckpointConflictError, match="working-room"):
        MaituMaterialSlotRepository._validate_script_layout_terminal_evidence(
            checkpoint, generic, operation_result
        )

    MaituMaterialSlotRepository._validate_script_layout_terminal_evidence(
        checkpoint,
        {
            **generic,
            "verification_source": "working_room_readback",
            "environment": "working",
            "not_live": True,
            "clip_id": 410001,
            "default_clip_id": 410001,
        },
        operation_result,
    )


def test_digital_human_terminal_evidence_uses_speaker_and_image_not_fake_material_id() -> None:
    checkpoint = {
        "effect_class": "mutating",
        "operation_type": "insert_asset_layer",
        "intent_snapshot": {
            "scene_index": 0,
            "scene_name": "数字人",
            "asset_code": "AG-VID-1",
            "layer_id": "digital-human",
            "layer_type": "digital_human",
            "source_material_type": "digital_human",
            "speaker_id": 81,
            "digital_human_image_id": 91,
        },
    }
    evidence = {
        "verified": True,
        "operation_applied": True,
        "verification_source": "working_room_readback",
        "clip_id": 410001,
        "material_id": 510001,
        "source_material_id": None,
        "source_material_type": "digital_human",
        "speaker_id": 81,
        "digital_human_image_id": 91,
        "scene_index": 0,
        "scene_name": "数字人",
        "asset_code": "AG-VID-1",
        "layer_id": "digital-human",
        "layer_type": "digital_human",
    }
    operation_result = {"operation_type": "insert_asset_layer", "status": "completed"}
    MaituMaterialSlotRepository._validate_script_layout_terminal_evidence(
        checkpoint, evidence, operation_result
    )
    with pytest.raises(BuildPlanCheckpointConflictError, match="speaker_id"):
        MaituMaterialSlotRepository._validate_script_layout_terminal_evidence(
            checkpoint, {**evidence, "speaker_id": 82}, operation_result
        )


def test_verify_scene_dynamic_lineage_binds_exact_visual_and_text_material_ids() -> None:
    class Cursor:
        def execute(self, *_args, **_kwargs) -> None:
            pass

        def fetchall(self) -> list[dict]:
            return [
                {
                    "operation_type": "create_scene",
                    "intent_snapshot": {"scene_index": 0, "scene_name": "开场"},
                    "completion_evidence": {"clip_id": 410001},
                },
                {
                    "operation_type": "insert_asset_layer",
                    "intent_snapshot": {
                        "scene_index": 0,
                        "scene_name": "开场",
                        "layer_id": "hero",
                        "asset_code": "AG-IMG-1",
                    },
                    "completion_evidence": {"clip_id": 410001, "material_id": 510001},
                },
                {
                    "operation_type": "write_script",
                    "intent_snapshot": {"scene_index": 0, "scene_name": "开场"},
                    "completion_evidence": {"clip_id": 410001, "text_material_id": 610001},
                },
            ]

    checkpoint = {
        "operation_index": 4,
        "operation_type": "verify_scene",
        "intent_snapshot": {"scene_index": 0, "scene_name": "开场"},
    }
    evidence = {
        "clip_id": 410001,
        "text_material_id": 610001,
        "verified_layers": [{"layer_id": "hero", "asset_code": "AG-IMG-1", "material_id": 510001}],
    }
    MaituMaterialSlotRepository._validate_script_layout_dynamic_lineage(
        Cursor(), "MT-EXEC-1", checkpoint, evidence
    )
    with pytest.raises(BuildPlanCheckpointConflictError, match="text material id"):
        MaituMaterialSlotRepository._validate_script_layout_dynamic_lineage(
            Cursor(), "MT-EXEC-1", checkpoint, {**evidence, "text_material_id": 610002}
        )
    with pytest.raises(BuildPlanCheckpointConflictError, match="material id"):
        MaituMaterialSlotRepository._validate_script_layout_dynamic_lineage(
            Cursor(),
            "MT-EXEC-1",
            checkpoint,
            {
                **evidence,
                "verified_layers": [
                    {"layer_id": "hero", "asset_code": "AG-IMG-1", "material_id": 510002}
                ],
            },
        )


def test_finalize_contract_rejects_unsafe_draft_and_manual_review_flags() -> None:
    base = {
        "finalization_id": FINALIZATION_ID,
        "run_attempt_id": ATTEMPT_ID,
        "lease_token": LEASE_TOKEN,
        "lease_version": 1,
        "execution_status": "completed",
    }
    with pytest.raises(ValidationError, match="ready_for_go_live"):
        MaituScriptLayoutExecutionFinalizeCreate.model_validate(
            {**base, "ready_for_go_live": True}
        )
    with pytest.raises(ValidationError, match="manual_review_required"):
        MaituScriptLayoutExecutionFinalizeCreate.model_validate(
            {**base, "execution_status": "completed_with_manual_review"}
        )
