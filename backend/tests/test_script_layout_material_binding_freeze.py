from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.domain.contracts import canonical_fingerprint
from app.repositories import maitu as maitu_repository
from app.repositories.maitu import BuildPlanCheckpointConflictError, MaituMaterialSlotRepository
from app.services.maitu_binding_identity import canonical_maitu_binding_identity


READBACK_KEY = "test-material-binding-readback-key-32-bytes"


class BindingCursor:
    def __init__(self, asset: dict, *, active_test_job: bool = True) -> None:
        self.asset = asset
        self.active_test_job = active_test_job
        self.row: dict | None = None

    def execute(self, query: str, _params: tuple[object, ...]) -> None:
        if "FROM assets" in query:
            self.row = self.asset
        elif "FROM maitu_workbench_draft_execution_jobs" in query:
            self.row = {"active": True} if self.active_test_job else None
        else:  # pragma: no cover - guards changes to the freeze query contract
            raise AssertionError(query)

    def fetchone(self) -> dict | None:
        return self.row


def _asset_binding(*, digital_human: bool, backend_attested: bool = False) -> dict:
    material_id = None if digital_human else 37262
    binding = {
        "maitu_material_id": material_id,
        "maitu_source_material_id": 37200 if digital_human else material_id,
        "source_material_type": "digital_human" if digital_human else "image",
        "source_material_url": None
        if digital_human
        else "https://cdn.example.test/materials/37262.png",
        "source_cover_url": "https://cdn.example.test/covers/37200.png"
        if digital_human
        else "https://cdn.example.test/covers/37262.png",
        "speaker_id": 3760 if digital_human else None,
        "digital_human_image_id": 7717 if digital_human else None,
    }
    nonce = str(uuid4())
    inventory_fingerprint = "a" * 64
    attested = {
        "asset_code": "AG-DH-37200" if digital_human else "AG-IMG-37262",
        "binding": binding,
        "inventory_snapshot_sha256": inventory_fingerprint,
        "readback_nonce": nonce,
    }
    signature = hmac.new(
        READBACK_KEY.encode(),
        json.dumps(attested, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "asset_code": attested["asset_code"],
        **binding,
        "maitu_binding_verification_source": (
            "backend_maitu_inventory_readback"
            if backend_attested
            else "worker_maitu_inventory_readback"
        ),
        "maitu_binding_verified_at": datetime.now(UTC),
        "maitu_binding_scope": "assetgraph_script_layout_material_binding_v2",
        "maitu_binding_inventory_fingerprint": inventory_fingerprint,
        "maitu_binding_readback_nonce": nonce if backend_attested else None,
        "maitu_binding_attestation": signature if backend_attested else None,
        "maitu_binding_evidence": (
            {}
            if backend_attested
            else {
                "source": "active_functional_worker_inventory_readback",
                "execution_job_code": "MT-WB-EXEC-FREEZE-001",
                "build_plan_code": "MT-BUILD-FREEZE-001",
                "source_plan_fingerprint": "b" * 64,
                "inventory_item_fingerprint": inventory_fingerprint,
                "binding_identity_fingerprint": canonical_fingerprint(
                    canonical_maitu_binding_identity(attested["asset_code"], binding)
                ),
            }
        ),
    }


def _freeze(
    asset: dict,
    *,
    requested_source_id: int | None = None,
    return_verify: bool = False,
) -> dict:
    source_operations = [
        {
            "operation_type": "preflight_content_build_plan",
            "status": "ready",
            "target_live_room_id": "41172",
        },
        {
            "operation_type": "insert_asset_layer",
            "operation_name": "Insert bound material",
            "status": "ready",
            "scene_index": 0,
            "scene_name": "Opening",
            "layer_id": "hero",
            "layer_type": "digital_human"
            if asset["source_material_type"] == "digital_human"
            else "background",
            "asset_code": asset["asset_code"],
        },
        {
            "operation_type": "verify_scene",
            "operation_name": "Verify scene",
            "status": "ready",
            "scene_index": 0,
            "scene_name": "Opening",
        },
    ]
    resolved = {
        **source_operations[1],
        "maitu_material_id": asset["maitu_material_id"],
        "maitu_source_material_id": (
            asset["maitu_source_material_id"]
            if requested_source_id is None
            else requested_source_id
        ),
        "material_id": asset["maitu_material_id"],
        "source_material_type": asset["source_material_type"],
        "source_material_url": asset["source_material_url"],
        "source_cover_url": asset["source_cover_url"],
        "speaker_id": asset["speaker_id"],
        "digital_human_image_id": asset["digital_human_image_id"],
        "material_resolution_status": "refreshed_functional_worker_inventory_readback",
    }
    manifest, _, _ = MaituMaterialSlotRepository(None)._freeze_script_layout_manifest(
        cursor=BindingCursor(
            asset,
            active_test_job=asset["maitu_binding_verification_source"].startswith("worker_"),
        ),
        build_plan_code="MT-BUILD-FREEZE-001",
        checkpoint_contract="script_layout_checkpoint_v1",
        source_plan_fingerprint="b" * 64,
        target_live_room_id="41172",
        source_operations=source_operations,
        requested_operations=[
            {"operation_index": 0, "intent": source_operations[0]},
            {"operation_index": 1, "intent": resolved},
            {"operation_index": 2, "intent": source_operations[2]},
        ],
    )
    return manifest[2 if return_verify else 1]["intent"]


@pytest.mark.parametrize("digital_human", [False, True])
def test_freeze_preserves_regular_and_digital_human_source_identity(
    digital_human: bool,
) -> None:
    asset = _asset_binding(digital_human=digital_human)

    intent = _freeze(asset)

    assert intent["maitu_source_material_id"] == (37200 if digital_human else 37262)
    assert intent["material_id"] == (None if digital_human else 37262)
    assert intent["maitu_material_id"] == (None if digital_human else 37262)


def test_freeze_rejects_tampered_source_identity() -> None:
    with pytest.raises(BuildPlanCheckpointConflictError, match="maitu_source_material_id"):
        _freeze(_asset_binding(digital_human=True), requested_source_id=99999)


def test_freeze_rejects_worker_receipt_without_exact_execution_job_evidence() -> None:
    asset = _asset_binding(digital_human=False)
    asset["maitu_binding_evidence"] = {
        **asset["maitu_binding_evidence"],
        "execution_job_code": "",
    }

    with pytest.raises(BuildPlanCheckpointConflictError, match="authoritative material binding receipt"):
        _freeze(asset)


def test_freeze_uses_same_identity_for_image_without_cover_url() -> None:
    asset = _asset_binding(digital_human=False)
    asset["source_cover_url"] = None
    asset["maitu_binding_evidence"]["binding_identity_fingerprint"] = (
        canonical_fingerprint(canonical_maitu_binding_identity(asset["asset_code"], asset))
    )

    intent = _freeze(asset)

    assert intent["source_cover_url"] is None


def test_verify_scene_keeps_digital_human_source_material_id() -> None:
    intent = _freeze(_asset_binding(digital_human=True), return_verify=True)

    assert intent["expected_layers"][0]["source_material_id"] == 37200


def test_freeze_verifies_backend_receipt_with_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        maitu_repository.settings,
        "maitu_readback_attestation_key",
        SecretStr(READBACK_KEY),
    )

    intent = _freeze(_asset_binding(digital_human=False, backend_attested=True))

    assert intent["maitu_source_material_id"] == 37262
