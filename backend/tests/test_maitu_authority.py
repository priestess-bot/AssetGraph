from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.repositories.maitu import MaituMaterialSlotRepository
from app.services import maitu_authority
from app.services.maitu_authority import MaituAuthorityError, MaituAuthorityVerifier


SIGNING_KEY = "test-backend-maitu-authority-signing-key"
AUTHORITY_TOKEN = "test-backend-maitu-authority-token"


def test_settings_load_documented_assetgraph_authority_environment(monkeypatch) -> None:
    monkeypatch.setenv("ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN", "worker-token-with-32-characters-value")
    monkeypatch.setenv("ASSETGRAPH_MAITU_AUTHORITY_TOKEN", "authority-token-with-32-characters")
    monkeypatch.setenv("ASSETGRAPH_MAITU_READBACK_ATTESTATION_KEY", "signing-key-with-at-least-32-characters")
    configured = Settings(_env_file=None)

    assert configured.maitu_script_layout_worker_token is not None
    assert configured.maitu_script_layout_worker_token.get_secret_value().startswith("worker-token")
    assert configured.maitu_authority_token is not None
    assert configured.maitu_authority_token.get_secret_value().startswith("authority-token")
    assert configured.maitu_readback_attestation_key is not None


def verifier_for(monkeypatch, responses: dict[str, Any]) -> MaituAuthorityVerifier:
    monkeypatch.setattr(maitu_authority.settings, "maitu_authority_token", SecretStr(AUTHORITY_TOKEN))
    monkeypatch.setattr(maitu_authority.settings, "maitu_readback_attestation_key", SecretStr(SIGNING_KEY))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query.decode()}"
        return httpx.Response(200, json=responses[path])

    client = httpx.Client(
        base_url="https://authority.example/",
        transport=httpx.MockTransport(handler),
    )
    return MaituAuthorityVerifier(client=client)


def test_reconciliation_attests_confirmed_not_applied_when_effect_is_absent(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "environment": "working",
                "is_live": False,
                "topics": [{"clips": [{"id": 1, "name": "默认场景", "clip_materials": []}]}],
            }
        },
    )
    checkpoint = {
        "operation_fingerprint": "b" * 64,
        "operation_type": "create_scene",
        "intent_snapshot": {"operation_type": "create_scene", "scene_name": "促单"},
    }
    payload = {
        "operation_fingerprint": "b" * 64,
        "reconciliation_id": "88888888-8888-4888-8888-888888888888",
        "reconciled_attempt_id": "44444444-4444-4444-8444-444444444444",
        "resolution": "confirmed_not_applied",
        "evidence": {
            "verified": True,
            "operation_applied": False,
            "operation_type": "create_scene",
            "target_live_room_id": "47000002",
            "clip_id": 416426,
        },
    }

    result = verifier.attest_reconciliation(
        build_plan_code="MT-BUILD-20260712-000001",
        execution_code="MT-EXEC-20260712-000001",
        operation_index=1,
        checkpoint=checkpoint,
        payload=payload,
    )

    assert result["evidence"]["backend_authority_observation"]["operation_applied"] is False
    assert result["evidence"]["readback_attestation_algorithm"] == "hmac-sha256-v1"
    assert len(result["evidence"]["readback_attestation"]) == 64


def test_completion_attestation_validates_at_repository_boundary(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "environment": "working",
                "is_live": False,
                "topics": [{"clips": [{"id": 1, "name": "默认场景", "clip_materials": []}]}],
            }
        },
    )
    checkpoint = {
        "operation_fingerprint": "b" * 64,
        "operation_type": "preflight_content_build_plan",
        "intent_snapshot": {"operation_type": "preflight_content_build_plan"},
    }
    payload = {
        "operation_fingerprint": "b" * 64,
        "attempt_id": "44444444-4444-4444-8444-444444444444",
        "lease_token": "55555555-5555-4555-8555-555555555555",
        "lease_version": 1,
        "completion_id": "66666666-6666-4666-8666-666666666666",
        "evidence": {
            "verified": True,
            "operation_applied": False,
            "operation_type": "preflight_content_build_plan",
            "target_live_room_id": "47000002",
            "default_clip_id": 1,
        },
    }

    result = verifier.attest_completion(
        build_plan_code="MT-BUILD-20260712-000001",
        execution_code="MT-EXEC-20260712-000001",
        operation_index=0,
        checkpoint=checkpoint,
        payload=payload,
    )

    MaituMaterialSlotRepository._validate_completion_readback_attestation(
        build_plan_code="MT-BUILD-20260712-000001",
        execution_code="MT-EXEC-20260712-000001",
        operation_index=0,
        checkpoint=checkpoint,
        payload=result,
    )


@pytest.mark.parametrize(
    "room",
    [
        {
            "environment": "working",
            "is_live": False,
            "topics": [{"clips": [{"id": 1, "name": "默认场景", "clip_materials": []}]}],
        },
        {
            "id": 47000002,
            "topics": [{"clips": [{"id": 1, "name": "默认场景", "clip_materials": []}]}],
        },
    ],
)
def test_working_room_requires_exact_identity_and_environment(monkeypatch, room: dict[str, Any]) -> None:
    verifier = verifier_for(
        monkeypatch,
        {"/live_rooms/47000002?env=working&include_qa_clips=true": room},
    )

    with pytest.raises(MaituAuthorityError):
        verifier.verify_checkpoint(
            {"operation_type": "preflight_content_build_plan", "intent_snapshot": {}},
            {"target_live_room_id": "47000002", "default_clip_id": 1},
        )


def test_working_room_accepts_real_maitu_status_zero_as_non_live_evidence(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "status": 0,
                "topics": [{"clips": [{"id": 1, "name": "默认场景", "clip_materials": []}]}],
            }
        },
    )

    observation = verifier.verify_checkpoint(
        {"operation_type": "preflight_content_build_plan", "intent_snapshot": {}},
        {"target_live_room_id": "47000002", "default_clip_id": 1},
    )

    assert observation["operation_applied"] is True


@pytest.mark.parametrize("status_value", [1, 2, True])
def test_working_room_rejects_active_or_unknown_maitu_status(monkeypatch, status_value: Any) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "status": status_value,
                "topics": [{"clips": [{"id": 1, "name": "默认场景", "clip_materials": []}]}],
            }
        },
    )

    with pytest.raises(MaituAuthorityError):
        verifier.verify_checkpoint(
            {"operation_type": "preflight_content_build_plan", "intent_snapshot": {}},
            {"target_live_room_id": "47000002", "default_clip_id": 1},
        )


def test_reconciliation_rejects_bogus_missing_clip_when_intended_scene_exists(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "environment": "working",
                "is_live": False,
                "topics": [{"clips": [{"id": 99, "name": "促单", "clip_materials": []}]}],
            }
        },
    )
    checkpoint = {
        "operation_fingerprint": "b" * 64,
        "operation_type": "create_scene",
        "intent_snapshot": {"operation_type": "create_scene", "scene_name": "促单"},
    }
    payload = {
        "reconciliation_id": "88888888-8888-4888-8888-888888888888",
        "reconciled_attempt_id": "44444444-4444-4444-8444-444444444444",
        "resolution": "confirmed_not_applied",
        "evidence": {
            "verified": True,
            "operation_applied": False,
            "target_live_room_id": "47000002",
            "clip_id": 416426,
        },
    }

    with pytest.raises(MaituAuthorityError, match="not applied"):
        verifier.attest_reconciliation(
            build_plan_code="MT-BUILD-1",
            execution_code="MT-EXEC-1",
            operation_index=1,
            checkpoint=checkpoint,
            payload=payload,
        )


def test_negative_reconciliation_searches_frozen_material_identity_not_evidence_ids(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "environment": "working",
                "is_live": False,
                "topics": [
                    {
                        "clips": [
                            {
                                "id": 10,
                                "name": "促单",
                                "clip_materials": [
                                    {
                                        "id": 20,
                                        "name": "product",
                                        "type": "image",
                                        "material_id": 901,
                                        "url": "https://cdn.example/product.png",
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        },
    )

    with pytest.raises(MaituAuthorityError, match="not applied"):
        verifier.verify_checkpoint(
            {
                "operation_type": "insert_asset_layer",
                "intent_snapshot": {
                    "scene_name": "促单",
                    "layer_id": "product",
                    "source_material_type": "image",
                    "material_id": 901,
                    "source_material_url": "https://cdn.example/product.png",
                },
            },
            {"target_live_room_id": "47000002", "clip_id": 999, "material_id": 998},
            expect_applied=False,
        )


def test_negative_reconciliation_searches_script_content_not_evidence_ids(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "environment": "working",
                "is_live": False,
                "topics": [
                    {
                        "clips": [
                            {
                                "id": 10,
                                "name": "促单",
                                "clip_materials": [{"id": 30, "type": "text", "content": "成交口播"}],
                            }
                        ]
                    }
                ],
            }
        },
    )

    with pytest.raises(MaituAuthorityError, match="not applied"):
        verifier.verify_checkpoint(
            {
                "operation_type": "write_script",
                "intent_snapshot": {"scene_name": "促单", "script_text": "成交口播"},
            },
            {"target_live_room_id": "47000002", "clip_id": 999, "text_material_id": 998},
            expect_applied=False,
        )


def test_binding_uses_authoritative_cover_url_instead_of_worker_value(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/materials/?is_pub=false&offset=0&limit=100": {
                "items": [
                    {
                        "id": 901,
                        "type": "image",
                        "url": "https://cdn.example/product.png",
                        "cover_url": "https://cdn.example/product-cover.png",
                    }
                ]
            },
            "/materials/digital_human?access_rule=private&offset=0&limit=100": {"items": []},
        },
    )

    result = verifier.attest_binding(
        "AG-IMG-1",
        {
            "maitu_material_id": 901,
            "source_material_type": "image",
            "source_material_url": "https://cdn.example/product.png",
            "source_cover_url": "https://attacker.example/forged.png",
            "speaker_id": None,
            "digital_human_image_id": None,
        },
    )

    assert result["source_cover_url"] == "https://cdn.example/product-cover.png"


def test_binding_rejects_inventory_url_with_credential_query(monkeypatch) -> None:
    credential_url = "https://cdn.example/product.png?X-Amz-Signature=secret-value"
    verifier = verifier_for(
        monkeypatch,
        {
            "/materials/?is_pub=false&offset=0&limit=100": {
                "items": [{"id": 901, "type": "image", "url": credential_url}]
            },
            "/materials/digital_human?access_rule=private&offset=0&limit=100": {"items": []},
        },
    )

    with pytest.raises(MaituAuthorityError, match="credential-like"):
        verifier.attest_binding(
            "AG-IMG-1",
            {
                "maitu_material_id": 901,
                "source_material_type": "image",
                "source_material_url": credential_url,
                "source_cover_url": None,
                "speaker_id": None,
                "digital_human_image_id": None,
            },
        )


def test_binding_accepts_public_oss_transform_query(monkeypatch) -> None:
    public_url = (
        "https://mytwins-static.oss-cn-hangzhou.aliyuncs.com/images/"
        "b565b64460bb99e0332e494a68cc3c8ed084ade9.jpeg?x-oss-process=image/resize,w_1080"
    )
    verifier = verifier_for(
        monkeypatch,
        {
            "/materials/?is_pub=false&offset=0&limit=100": {
                "items": [{"id": 901, "type": "image", "url": public_url}]
            },
            "/materials/digital_human?access_rule=private&offset=0&limit=100": {"items": []},
        },
    )

    result = verifier.attest_binding(
        "AG-IMG-1",
        {
            "maitu_material_id": 901,
            "source_material_type": "image",
            "source_material_url": public_url,
            "source_cover_url": None,
            "speaker_id": None,
            "digital_human_image_id": None,
        },
    )

    assert result["source_material_url"] == public_url


def test_verify_scene_rejects_worker_geometry_not_present_in_authoritative_room(monkeypatch) -> None:
    verifier = verifier_for(
        monkeypatch,
        {
            "/live_rooms/47000002?env=working&include_qa_clips=true": {
                "id": 47000002,
                "environment": "working",
                "is_live": False,
                "topics": [
                    {
                        "clips": [
                            {
                                "id": 10,
                                "name": "促单",
                                "clip_materials": [
                                    {
                                        "id": 20,
                                        "type": "image",
                                        "material_id": 901,
                                        "url": "https://cdn.example/product.png",
                                        "style": {"left": 999, "top": 20, "width": 300, "height": 200, "zIndex": 3},
                                    },
                                    {"id": 30, "type": "text", "content": "成交口播"},
                                ],
                            }
                        ]
                    }
                ],
            }
        },
    )
    expected_layer = {
        "asset_code": "AG-IMG-1",
        "layer_id": "product",
        "layer_type": "product_image",
        "source_material_id": 901,
        "source_material_type": "image",
        "source_material_url": "https://cdn.example/product.png",
        "speaker_id": None,
        "digital_human_image_id": None,
        "left": 10,
        "top": 20,
        "width": 300,
        "height": 200,
        "z_index": 3,
    }

    with pytest.raises(MaituAuthorityError, match="applied"):
        verifier.verify_checkpoint(
            {
                "operation_type": "verify_scene",
                "intent_snapshot": {
                    "scene_name": "促单",
                    "expected_layers": [expected_layer],
                    "expected_visual_count": 1,
                    "expected_text_count": 1,
                    "expected_script_text": "成交口播",
                },
            },
            {
                "target_live_room_id": "47000002",
                "clip_id": 10,
                "scene_name": "促单",
                "verified_layers": [{**expected_layer, "material_id": 20}],
                "text_material_id": 30,
                "verified_script_text": "成交口播",
            },
        )
