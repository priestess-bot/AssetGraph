from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from psycopg.rows import dict_row

from app.api.routes.maitu import reject_script_layout_worker_secret
from app.repositories.maitu import MaituMaterialSlotRepository
from app.schemas.maitu import (
    MaituLiveRoomBuildPlanOperationRead,
    MaituScriptLayoutExecutionManifestOperation,
)


def test_build_plan_code_generation_supports_dict_row_connections() -> None:
    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            assert "RETURNING current_value" in query
            assert len(params) == 2

        def fetchone(self) -> dict[str, int]:
            return {"current_value": 7}

    class FakeConnection:
        def cursor(self, *, row_factory: object) -> FakeCursor:
            assert row_factory is dict_row
            return FakeCursor()

    repository = object.__new__(MaituMaterialSlotRepository)
    repository.connection = FakeConnection()  # type: ignore[assignment]

    assert repository._next_build_plan_code().endswith("-000007")


def test_system_host_binding_fingerprint_is_not_treated_as_a_worker_secret() -> None:
    operation = MaituScriptLayoutExecutionManifestOperation.model_validate(
        {
            "operation_index": 0,
            "intent": {
                "operation_type": "insert_asset_layer",
                "constraint_evidence": {
                    "system_host_binding_fingerprint": "a" * 64,
                },
            },
        }
    )

    assert operation.intent["constraint_evidence"]["system_host_binding_fingerprint"] == "a" * 64


@pytest.mark.parametrize(
    "fingerprint",
    ["Bearer exfiltrated-credential", "not-a-sha256-digest", "A" * 64],
)
def test_system_host_binding_fingerprint_rejects_non_sha256_values(
    fingerprint: str,
) -> None:
    with pytest.raises(ValidationError):
        MaituScriptLayoutExecutionManifestOperation.model_validate(
            {
                "operation_index": 0,
                "intent": {
                    "operation_type": "insert_asset_layer",
                    "constraint_evidence": {
                        "system_host_binding_fingerprint": fingerprint,
                    },
                },
            }
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "source_plan_fingerprint",
        "operation_fingerprint",
        "fingerprint",
        "system_host_binding_fingerprint",
        "inventory_snapshot_sha256",
        "script_sha256",
        "expected_script_sha256",
    ],
)
def test_terminal_report_filter_validates_nested_public_sha256_fields(
    field_name: str,
) -> None:
    reject_script_layout_worker_secret(
        {"details": {field_name: "b" * 64}}
    )

    with pytest.raises(HTTPException) as rejected:
        reject_script_layout_worker_secret(
            {"details": {field_name: "Bearer exfiltrated-credential"}}
        )

    assert rejected.value.status_code == 422
    assert rejected.value.detail == f"{field_name} must be a SHA-256 digest"


def test_legacy_blueprint_operation_does_not_expose_internal_columns_or_flatten_details() -> None:
    row = {
        "id": "internal-operation-id",
        "build_plan_id": "internal-plan-id",
        "build_plan_code": "MT-BUILD-LEGACY",
        "operation_type": "replace_layer_asset",
        "operation_name": "替换旧蓝图图层",
        "sort_order": 10,
        "status": "planned",
        "scene_name": "旧场景",
        "layer_name": "旧图层",
        "accepted_asset_types": ["IMG"],
        "match_reasons": [],
        "instruction": "保持旧响应契约。",
        "details": {
            "legacy_only": "must-stay-nested",
            "scene_template_code": "MT-SCENE-LEGACY",
        },
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    normalized = MaituMaterialSlotRepository._normalize_live_room_build_plan_operation(row)
    serialized = MaituLiveRoomBuildPlanOperationRead.model_validate(normalized).model_dump(exclude_none=True)

    assert serialized["details"]["legacy_only"] == "must-stay-nested"
    assert "legacy_only" not in serialized
    assert "scene_template_code" not in serialized
    for internal_field in ("id", "build_plan_id", "build_plan_code", "created_at", "updated_at"):
        assert internal_field not in serialized
