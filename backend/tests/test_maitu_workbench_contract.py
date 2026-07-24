from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pglast import parse_sql

from app.api.routes.maitu_workbench import _reject_secret, get_maitu_workbench_service, router
from app.schemas.maitu_workbench import (
    DraftExecutionJobClaimedRead,
    DraftExecutionJobRead,
    InventorySyncJobClaimedRead,
    InventorySyncJobRead,
    MaterialDecisionCreate,
    ProductFactCardContent,
    WorkbenchRunCreate,
)
from app.services.maitu_workbench import WorkbenchModelUnavailableError
from app.services.maitu_authority import (
    MaituAuthorityError,
    get_maitu_authority_verifier,
)


def test_workbench_legacy_migration_parses_and_is_replaced_by_neutral_contract() -> None:
    migration = Path(__file__).resolve().parents[1] / "migrations" / "023_maitu_production_workbench.sql"
    sql = migration.read_text(encoding="utf-8")

    parse_sql(sql)
    for table in (
        "maitu_workbench_product_fact_card_versions",
        "maitu_workbench_inventory_snapshots",
        "maitu_workbench_inventory_snapshot_items",
        "maitu_workbench_plan_revisions",
        "maitu_workbench_material_requirements",
        "maitu_workbench_material_decisions",
        "maitu_workbench_preflights",
        "maitu_workbench_draft_execution_jobs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "generation_provider VARCHAR(64) NOT NULL" in sql
    assert "generation_actual_model VARCHAR(128) NOT NULL" in sql
    assert "generation_input_fingerprint CHAR(64) NOT NULL" in sql
    assert "generation_output_fingerprint CHAR(64) NOT NULL" in sql
    assert "topic TEXT NOT NULL" in sql
    assert "ready_for_go_live = false" in sql
    assert "FOR UPDATE SKIP LOCKED" not in sql  # Leasing belongs in repository commands.

    replacement = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "043_provider_neutral_producer_contracts.sql"
    ).read_text(encoding="utf-8")
    parse_sql(replacement)
    assert "ALTER COLUMN generation_provider DROP NOT NULL" in replacement
    assert "generation_strategy_revision" in replacement
    assert "generation_invocation_evidence_ref" in replacement


def test_reference_template_handoff_migration_pins_an_immutable_complete_bundle() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "026_maitu_reference_template_handoff.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    parse_sql(sql)
    assert "reference_template_code VARCHAR(64)" in sql
    assert "reference_template_revision_number INTEGER" in sql
    assert "reference_template_projection_fingerprint CHAR(64)" in sql
    assert "reference_template_snapshot JSONB" in sql
    assert "chk_maitu_workbench_run_reference_template_bundle" in sql
    assert "prevent_maitu_workbench_reference_template_mutation" in sql


def test_worker_lease_tokens_are_only_in_claim_response_contracts() -> None:
    assert "lease_token" not in InventorySyncJobRead.model_fields
    assert "lease_token" in InventorySyncJobClaimedRead.model_fields
    assert "lease_token" not in DraftExecutionJobRead.model_fields
    assert "lease_token" in DraftExecutionJobClaimedRead.model_fields


def test_inventory_source_revision_is_a_public_content_identity() -> None:
    _reject_secret({"source_revision": "a" * 64})


def test_strict_fact_and_material_decision_contracts_reject_unsafe_shapes() -> None:
    facts = ProductFactCardContent.model_validate(
        {
            "product_name": " Demo Wine ",
            "positioning": " Verified positioning ",
            "verified_facts": [" fact one ", "fact one", " fact two "],
            "valid_from": "2026-07-25T00:00:00Z",
            "valid_until": "2026-12-31T23:59:59Z",
            "applicable_platforms": [" douyin ", "douyin"],
        }
    )
    assert facts.product_name == "Demo Wine"
    assert facts.verified_facts == ["fact one", "fact two"]
    assert facts.applicable_platforms == ["douyin"]
    assert facts.model_dump(mode="json")["valid_until"] == "2026-12-31T23:59:59Z"

    with pytest.raises(ValueError, match="valid_from must include a timezone"):
        ProductFactCardContent.model_validate(
            {"product_name": "Demo Wine", "positioning": "Verified", "verified_facts": ["fact"], "valid_from": "2026-07-25T00:00:00"}
        )

    try:
        MaterialDecisionCreate.model_validate(
            {
                "decision": "selected",
                "selected_asset_code": "ASSET-1",
                "selected_material_key": "material:1",
                "reason": "ambiguous",
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("selected decisions must identify exactly one material")

    run = WorkbenchRunCreate.model_validate(
        {
            "title": "一分钟选酒演示",
            "topic": "夏日晚餐如何根据口味选择一款已核验的干红",
            "fact_card_code": "MT-FACT-001",
            "inventory_snapshot_code": "MT-INV-SNAP-001",
        }
    )
    assert run.title == "一分钟选酒演示"
    assert run.topic.startswith("夏日晚餐")
    assert run.target_duration_minutes == 1

    pinned = WorkbenchRunCreate.model_validate(
        {
            **run.model_dump(mode="json"),
            "reference_template_code": "LR-TPL-001",
            "reference_template_revision_number": 2,
            "reference_template_projection_fingerprint": "a" * 64,
        }
    )
    assert pinned.reference_template_revision_number == 2
    with pytest.raises(ValueError, match="must be provided together"):
        WorkbenchRunCreate.model_validate(
            {
                **run.model_dump(mode="json"),
                "reference_template_revision_number": 2,
            }
        )
    with pytest.raises(ValueError, match="must be provided together"):
        WorkbenchRunCreate.model_validate(
            {
                **run.model_dump(mode="json"),
                "reference_template_code": "LR-TPL-001",
            }
        )


def test_router_exposes_complete_workbench_contract_without_go_live_endpoint() -> None:
    paths = {route.path for route in router.routes}
    expected = {
        "/maitu/workbench/product-fact-cards",
        "/maitu/workbench/inventory-sync-jobs/claim-next",
        "/maitu/workbench/inventory-snapshots/{snapshot_code}",
        "/maitu/workbench/runs/{run_code}/target-live-room",
        "/maitu/workbench/runs/{run_code}/plans",
        "/maitu/workbench/runs/{run_code}/replan",
        "/maitu/workbench/runs/{run_code}/material-requirements/{requirement_code}/decisions",
        "/maitu/workbench/runs/{run_code}/preflight",
        "/maitu/workbench/runs/{run_code}/draft-execution-jobs",
        "/maitu/workbench/draft-execution-jobs/claim-next",
        "/maitu/workbench/draft-execution-jobs/{execution_job_code}/complete",
    }
    assert expected <= paths
    assert not any("go-live" in path or "go_live" in path for path in paths)


class FailingPlanningService:
    @staticmethod
    def create_initial_plan(run_code: str, payload: dict[str, object]) -> dict[str, object]:
        del run_code, payload
        raise WorkbenchModelUnavailableError("DeepSeek API key is not configured")


def test_route_maps_required_model_unavailability_to_503() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_maitu_workbench_service] = lambda: FailingPlanningService()

    with TestClient(app) as client:
        response = client.post("/api/maitu/workbench/runs/MT-WB-RUN-001/plans", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "DeepSeek API key is not configured"


class RejectingRoomAuthority:
    @staticmethod
    def attest_fresh_blank_room(
        live_room_id: str,
        protected_room_ids: set[str] | frozenset[str],
    ) -> dict[str, object]:
        assert live_room_id == "room-draft-001"
        assert protected_room_ids == {"38336", "38995"}
        raise MaituAuthorityError("authoritative room is not blank")


class AuthorityAwareWorkbenchService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def preflight(self, run_code, payload, *, room_verifier):
        del run_code, payload
        self.calls.append("preflight")
        return room_verifier("room-draft-001", {"38336", "38995"})

    def create_draft_execution_job(self, run_code, payload, *, room_verifier):
        del run_code, payload
        self.calls.append("draft-execution")
        return room_verifier("room-draft-001", {"38336", "38995"})


@pytest.mark.parametrize(
    ("path", "expected_call"),
    [
        ("/api/maitu/workbench/runs/MT-WB-RUN-001/preflight", "preflight"),
        (
            "/api/maitu/workbench/runs/MT-WB-RUN-001/draft-execution-jobs",
            "draft-execution",
        ),
    ],
)
def test_preflight_and_queue_routes_require_backend_room_authority(
    path: str,
    expected_call: str,
) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    service = AuthorityAwareWorkbenchService()
    app.dependency_overrides[get_maitu_workbench_service] = lambda: service
    app.dependency_overrides[get_maitu_authority_verifier] = RejectingRoomAuthority

    with TestClient(app) as client:
        response = client.post(path, json={"expected_plan_revision": 1})

    assert service.calls == [expected_call]
    assert response.status_code == 409
    assert response.json()["detail"] == "authoritative room is not blank"
