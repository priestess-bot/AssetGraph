from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.contracts import DataClassification
from app.repositories.maitu_workbench import MaituWorkbenchConflictError
from app.services.maitu_workbench import (
    DeterministicPlanGenerationProvider,
    MaituWorkbenchService,
    RoutedPlanGenerationProvider,
    UnavailablePlanGenerationProvider,
    WorkbenchDraftSafetyError,
    WorkbenchModelGenerationError,
    WorkbenchModelUnavailableError,
    _SnapshotBoundAssetRepository,
    assert_draft_only,
)
from app.services.online_models import ModelInvocation, OnlineModelError
from app.services.providers import (
    ModelCapability,
    OpenAICompatibleStructuredAdapter,
    ProviderBinding,
    ProviderRouter,
)


NOW = datetime(2026, 7, 20, tzinfo=UTC)


def fresh_blank_room_verifier(
    live_room_id: str,
    protected_room_ids: set[str] | frozenset[str],
) -> dict[str, Any]:
    assert live_room_id not in protected_room_ids
    return {
        "contract": "maitu-fresh-draft-room-attestation.v2",
        "target_live_room_id": live_room_id,
        "environment": "working",
        "environment_evidence": "working_endpoint",
        "is_live": False,
        "scene_count": 1,
        "material_count": 0,
        "seed_material": None,
        "default_scene_id": "default-scene-001",
        "protected_reference_room_ids": sorted(protected_room_ids),
        "observation_sha256": "d" * 64,
        "readback_attestation_algorithm": "hmac-sha256-v1",
        "readback_attestation": "e" * 64,
    }


def _fact_version() -> dict[str, Any]:
    return {
        "id": "10000000-0000-0000-0000-000000000001",
        "fact_card_code": "MT-FACT-001",
        "version_code": "MT-FACT-001-V001",
        "version_number": 1,
        "status": "approved",
        "content_sha256": "a" * 64,
        "content": {
            "product_name": "贺兰山典藏干红",
            "product_code": "WINE-001",
            "brand": "张裕",
            "category": "葡萄酒",
            "positioning": "适合正式聚餐的结构型干红",
            "verified_facts": [
                "葡萄来自贺兰山东麓产区",
                "酒精度以商品标签标示为准",
                "酒体结构完整且单宁清晰",
                "使用橡木桶进行陈酿",
                "建议饮用前适度醒酒",
            ],
            "tasting_notes": ["黑色水果香气", "单宁清晰", "余味完整"],
            "scenarios": ["正式聚餐", "宴请", "礼赠"],
            "selection_guidance": "需要结构感和餐食搭配能力时，可以核对商品页规格。",
            "objection_response": "偏好轻盈口感时，建议先比较酒体和单宁描述。",
            "asset_keywords": ["贺兰山", "干红", "酒瓶"],
            "verified_promotion_claims": [],
            "unverified_promotion_claims": [],
            "compliance_notes": ["未成年人请勿饮酒"],
            "source_references": [],
        },
    }


def _snapshot() -> dict[str, Any]:
    return {
        "id": "20000000-0000-0000-0000-000000000001",
        "snapshot_code": "MT-INV-SNAP-001",
        "source_system": "maitu",
        "project_code": "DEMO",
        "source_revision": "rev-1",
        "schema_version": "maitu-inventory-snapshot-v1",
        "quality_status": "complete",
        "fingerprint_sha256": "b" * 64,
        "item_count": 1,
        "summary": {"available": 1},
        "captured_at": NOW,
        "created_at": NOW,
        "items": [
            {
                "item_key": "material:background:1",
                "material_id": "9001",
                "title": "贺兰山背景",
                "material_type": "background",
                "category": "background_image",
                "subtype": "image",
                "availability_status": "available",
                "source_material_url": "https://example.test/material/9001",
                "source_cover_url": "https://example.test/cover/9001",
                "speaker_id": None,
                "digital_human_image_id": None,
                "metadata": {},
            }
        ],
    }


def _reference_publication() -> dict[str, Any]:
    fingerprint = "c" * 64
    return {
        "template_code": "LR-TPL-001",
        "template_name": "已发布直播结构",
        "revision_number": 1,
        "projection_contract": "maitu-layout-projection.v1",
        "projection_fingerprint": fingerprint,
        "projection_ready": False,
        "manual_review_required": True,
        "projection_payload": {
            "template_code": "LR-TPL-001",
            "template_name": "已发布直播结构",
            "revision_number": 1,
            "projection_contract": "maitu-layout-projection.v1",
            "projection_fingerprint": fingerprint,
            "projection_ready": False,
            "manual_review_required": True,
            "blocking_reasons": [
                "component_secret-component_source_is_not_verified",
                "speech_bus_overlap:secret-component:other-component",
            ],
            "canvas": {"width": 1080, "height": 1920, "rotation_degrees": 0},
            "scenes": [
                {
                    "scene_key": "secret-scene-id",
                    "name": "问题开场",
                    "start_seconds": 0,
                    "end_seconds": 20,
                    "purpose": "建立选择问题",
                    "script_pattern": "不得进入规划上下文",
                    "material_slots": ["material-secret"],
                }
            ],
            "components": [
                {
                    "component_id": "secret-component",
                    "scene_key": "secret-scene-id",
                    "asset_code": "ASSET-SECRET",
                    "material_id": "MATERIAL-SECRET",
                    "role": "host",
                    "geometry": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.7},
                }
            ],
            "audio_policy": {
                "max_active_speech": 1,
                "max_active_bgm": 1,
                "unknown_audio_default_muted": True,
                "allow_overlapping_bgm_crossfade": False,
                "speech_ducking_db": -9,
                "private_audio_material_id": "MATERIAL-SECRET",
            },
            "provenance": {"source_session_codes": ["SECRET-SESSION"]},
        },
    }


class FakeWorkbenchRepository:
    def __init__(self) -> None:
        fact = _fact_version()
        snapshot = _snapshot()
        self.fact = fact
        self.snapshot = snapshot
        self.run = {
            "id": "30000000-0000-0000-0000-000000000001",
            "run_code": "MT-WB-RUN-001",
            "title": "一分钟选酒演示",
            "topic": "夏日晚餐如何根据口味选择一款已核验的干红",
            "status": "draft",
            "fact_card_version_code": fact["version_code"],
            "inventory_snapshot_code": snapshot["snapshot_code"],
            "target_live_room_id": "room-draft-001",
            "target_duration_minutes": 1,
            "build_mode": "strict",
            "include_default_host": True,
            "max_candidates_per_need": 1,
            "canvas_width": 1080,
            "canvas_height": 1920,
            "active_plan_revision": 0,
            "error_code": None,
            "error_message": None,
            "created_by": "tester",
            "created_at": NOW,
            "updated_at": NOW,
            "completed_at": None,
            "fact_card_version": fact,
            "inventory_snapshot": snapshot,
            "active_plan": None,
            "latest_preflight": None,
        }
        self.overrides: list[dict[str, Any]] = []
        self.requirements: list[dict[str, Any]] = []
        self.plan_calls: list[dict[str, Any]] = []
        self.failed: tuple[str, str] | None = None
        self.execution_payload: dict[str, Any] | None = None
        self.analysis_sync_calls: list[str] = []
        self.analysis_blockers: list[dict[str, Any]] = []
        self.reference_publication: dict[str, Any] | None = _reference_publication()
        self.reference_resolution_count = 0
        self.created_reference_template: dict[str, Any] | None = None
        self.protected_resources: dict[tuple[str, str], dict[str, Any]] = {}

    def get_run(self, run_code: str) -> dict[str, Any] | None:
        return deepcopy(self.run) if run_code == self.run["run_code"] else None

    def get_protected_resource(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        resource = self.protected_resources.get((resource_type, resource_id))
        return deepcopy(resource) if resource else None

    def resolve_published_reference_template(
        self, template_code: str
    ) -> dict[str, Any] | None:
        self.reference_resolution_count += 1
        if (
            self.reference_publication is None
            or self.reference_publication["template_code"] != template_code
        ):
            return None
        return deepcopy(self.reference_publication)

    def create_run(
        self,
        payload: dict[str, Any],
        *,
        fact_card_version: dict[str, Any],
        inventory_snapshot: dict[str, Any],
        reference_template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.created_reference_template = deepcopy(reference_template)
        self.run.update(
            title=payload["title"],
            topic=payload["topic"],
            fact_card_version=deepcopy(fact_card_version),
            inventory_snapshot=deepcopy(inventory_snapshot),
            inventory_snapshot_code=inventory_snapshot["snapshot_code"],
        )
        if reference_template:
            self.run.update(
                reference_template_code=reference_template["template_code"],
                reference_template_revision_number=reference_template["revision_number"],
                reference_template_projection_fingerprint=reference_template[
                    "projection_fingerprint"
                ],
                reference_template_snapshot=deepcopy(reference_template["snapshot"]),
            )
        return deepcopy(self.run)

    def update_run_target_live_room(
        self, run_code: str, target_live_room_id: str
    ) -> dict[str, Any] | None:
        if run_code != self.run["run_code"]:
            return None
        self.run["target_live_room_id"] = target_live_room_id
        self.run["status"] = (
            "replan_required" if self.run["active_plan_revision"] else "draft"
        )
        return deepcopy(self.run)

    def resolve_product_fact_card_version(
        self,
        fact_card_code: str,
        version_number: int | None,
        *,
        require_approved: bool,
    ) -> dict[str, Any] | None:
        assert fact_card_code == self.fact["fact_card_code"]
        assert version_number in {None, 1}
        assert require_approved is True
        return deepcopy(self.fact)

    def get_inventory_snapshot(
        self,
        snapshot_code: str,
        *,
        include_items: bool = False,
    ) -> dict[str, Any] | None:
        del include_items
        return deepcopy(self.snapshot) if snapshot_code == self.snapshot["snapshot_code"] else None

    def get_latest_inventory_snapshot(
        self,
        source_system: str,
        project_code: str | None,
    ) -> dict[str, Any]:
        assert (source_system, project_code) == ("maitu", "DEMO")
        return deepcopy(self.snapshot)

    def get_inventory_snapshot_item(self, snapshot_code: str, item_key: str) -> dict[str, Any] | None:
        assert snapshot_code == self.snapshot["snapshot_code"]
        return next(
            (deepcopy(item) for item in self.snapshot["items"] if item["item_key"] == item_key),
            None,
        )

    def get_manual_decision_overrides(self, run_code: str, revision_number: int) -> list[dict[str, Any]]:
        assert run_code == self.run["run_code"]
        assert revision_number == self.run["active_plan_revision"]
        return deepcopy(self.overrides)

    def mark_run_planning(self, run_code: str, *, expected_revision: int) -> dict[str, Any]:
        assert run_code == self.run["run_code"]
        assert expected_revision == self.run["active_plan_revision"]
        self.run["status"] = "planning"
        return deepcopy(self.run)

    def mark_run_failed(
        self,
        run_code: str,
        error_code: str,
        error_message: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        assert run_code == self.run["run_code"]
        assert expected_revision == self.run["active_plan_revision"]
        self.run.update(status="failed", error_code=error_code, error_message=error_message)
        self.failed = (error_code, error_message)
        return deepcopy(self.run)

    def create_plan_revision(self, run_code: str, **kwargs: Any) -> dict[str, Any]:
        assert run_code == self.run["run_code"]
        self.plan_calls.append(deepcopy(kwargs))
        revision = kwargs["expected_revision"] + 1
        plan = {
            "id": f"40000000-0000-0000-0000-{revision:012d}",
            "plan_revision_code": f"MT-WB-PLAN-001-R{revision:03d}",
            "run_code": run_code,
            "revision_number": revision,
            "trigger_type": kwargs["trigger_type"],
            "status": kwargs["status"],
            "fact_card_version_code": kwargs["fact_card_version"]["version_code"],
            "inventory_snapshot_code": kwargs["inventory_snapshot"]["snapshot_code"],
            "source_build_plan_code": kwargs["source_build_plan_code"],
            "input_fingerprint": kwargs["input_fingerprint"],
            "generation_strategy_revision": kwargs["generation_strategy_revision"],
            "generation_invocation_evidence_ref": kwargs[
                "generation_invocation_evidence_ref"
            ],
            "generation_prompt_version": kwargs["generation_prompt_version"],
            "generation_input_fingerprint": kwargs["generation_input_fingerprint"],
            "generation_output_fingerprint": kwargs["generation_output_fingerprint"],
            "pipeline_source": kwargs["pipeline_source"],
            "pipeline_output": kwargs["pipeline_output"],
            "gap_report": kwargs["gap_report"],
            "blocked_reasons": kwargs["blocked_reasons"],
            "reason": kwargs["reason"],
            "created_by": kwargs["created_by"],
            "created_at": NOW,
            "superseded_at": None,
        }
        self.requirements = []
        for index, requirement in enumerate(kwargs["requirements"], start=1):
            item = deepcopy(requirement)
            initial = item.pop("initial_decision", None)
            item.update(
                id=f"50000000-0000-0000-0000-{index:012d}",
                requirement_code=f"MT-WB-REQ-{revision:03d}-{index:03d}",
                run_code=run_code,
                plan_revision_number=revision,
                current_decision_revision=1 if initial else 0,
                created_at=NOW,
                updated_at=NOW,
                decisions=[],
            )
            if initial:
                item["decisions"] = [{**initial, "revision_number": 1}]
            self.requirements.append(item)
        self.run.update(
            status="ready" if kwargs["status"] == "ready" else "blocked",
            active_plan_revision=revision,
            active_plan=plan,
            fact_card_version=deepcopy(kwargs["fact_card_version"]),
            inventory_snapshot=deepcopy(kwargs["inventory_snapshot"]),
        )
        return deepcopy(plan)

    def list_material_requirements(self, run_code: str, *, active_only: bool) -> list[dict[str, Any]]:
        assert run_code == self.run["run_code"]
        assert active_only is True
        return deepcopy(self.requirements)

    def get_asset_selection(self, asset_code: str) -> dict[str, Any] | None:
        if not asset_code.startswith("ASSET-"):
            return None
        return {
            "asset_code": asset_code,
            "asset_type": "IMG",
            "title": asset_code,
            "original_filename": f"{asset_code}.png",
            "display_code": asset_code,
            "local_file_code": asset_code,
            "local_relative_path": f"assets/{asset_code}.png",
            "browser_use_hint": asset_code,
            "maitu_material_id": "9001",
            "source_material_type": None,
            "source_material_url": None,
            "source_cover_url": None,
            "speaker_id": None,
            "digital_human_image_id": None,
            "status": "ready",
        }

    def synchronize_selected_video_analyses(self, run_code: str) -> list[dict[str, Any]]:
        assert run_code == self.run["run_code"]
        self.analysis_sync_calls.append(run_code)
        return []

    def list_selected_analysis_blockers(self, run_code: str) -> list[dict[str, Any]]:
        assert run_code == self.run["run_code"]
        return deepcopy(self.analysis_blockers)

    def create_preflight(self, run_code: str, **kwargs: Any) -> dict[str, Any]:
        preflight = {
            "id": "60000000-0000-0000-0000-000000000001",
            "preflight_code": "MT-WB-PREF-001",
            "run_code": run_code,
            "plan_revision_number": kwargs["expected_plan_revision"],
            "preflight_number": 1,
            "status": kwargs["status"],
            "input_fingerprint": kwargs["input_fingerprint"],
            "checks": kwargs["checks"],
            "blocked_reasons": kwargs["blocked_reasons"],
            "performed_by": kwargs["performed_by"],
            "created_at": NOW,
        }
        self.run["status"] = "preflight_passed" if kwargs["status"] == "passed" else "blocked"
        self.run["latest_preflight"] = preflight
        return deepcopy(preflight)

    def create_draft_execution_job(self, run_code: str, **kwargs: Any) -> dict[str, Any]:
        self.execution_payload = deepcopy(kwargs["payload"])
        return {
            "execution_job_code": "MT-WB-EXEC-001",
            "run_code": run_code,
            **kwargs,
        }


class FakeMaituRepository:
    def __init__(self, *, material_id: str = "9001") -> None:
        self.material_id = material_id

    def select_assets_for_script_asset_need(
        self,
        need: dict[str, Any],
        scene: dict[str, Any],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        del scene, limit
        need_type = str(need["need_type"])
        return [
            {
                "asset_code": f"ASSET-{need_type.upper()}",
                "asset_type": (need.get("accepted_asset_types") or ["IMG"])[0],
                "title": f"{need_type} asset",
                "display_code": f"DISPLAY-{need_type}",
                "local_file_code": f"LOCAL-{need_type}",
                "original_filename": f"{need_type}.png",
                "local_relative_path": f"assets/{need_type}.png",
                "browser_use_hint": need_type,
                "maitu_material_id": self.material_id,
                "source_material_type": None,
                "source_material_url": None,
                "source_cover_url": None,
                "speaker_id": None,
                "digital_human_image_id": None,
                "sound_enabled": False,
                "audio_role": "muted",
                "audio_classification_status": "classified",
                "audio_class": "silent",
                "match_score": 1.0,
                "match_reasons": ["test candidate"],
            }
        ]

    @staticmethod
    def create_script_layout_build_plan(
        build_plan: dict[str, Any],
        *,
        plan_name: str,
    ) -> dict[str, Any]:
        return {**deepcopy(build_plan), "build_plan_code": "MT-BUILD-001", "plan_name": plan_name}


def test_snapshot_bound_assets_receive_authoritative_maitu_binding() -> None:
    snapshot = _snapshot()
    snapshot["items"][0]["asset_code"] = "ASSET-BACKGROUND_IMAGE"
    repository = FakeMaituRepository()
    bound = _SnapshotBoundAssetRepository(repository, snapshot)

    selected = bound.select_assets_for_script_asset_need(
        {
            "need_type": "background_image",
            "accepted_asset_types": ["IMG"],
        },
        {},
    )

    assert selected[0]["maitu_material_id"] == "9001"
    assert selected[0]["source_material_type"] == "background"
    assert selected[0]["source_material_url"] == "https://example.test/material/9001"
    assert selected[0]["source_cover_url"] == "https://example.test/cover/9001"


def test_material_overrides_survive_need_reordering_and_new_scenes() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    selection_plan = {
        "scenes": [
            {
                "scene_index": 3,
                "review_reasons": [],
                "asset_selections": [
                    {
                        "need_type": "script_text",
                        "required_category": "script_text",
                        "status": "generated_content",
                    },
                    {
                        "need_type": "digital_human",
                        "required_category": "digital_human_video",
                        "status": "missing_asset",
                    },
                ],
            }
        ]
    }
    overrides = [
        {
            "requirement_key": "prior-layout-key",
            "scene_index": 0,
            "need_type": "digital_human",
            "required_category": "digital_human_video",
            "requirement_plan_revision_number": 2,
            "revision_number": 1,
            "decision": "selected",
            "selected_material_key": "material:background:1",
            "selected_asset_code": None,
            "reason": "统一使用已审核主播",
        }
    ]

    service._apply_overrides(selection_plan, overrides, repository.snapshot)

    selected = selection_plan["scenes"][0]["asset_selections"][1]
    assert selected["status"] == "selected"
    assert selected["selected_asset_maitu_material_id"] == "9001"
    assert selected["selection_source"] == "workbench_manual_inventory_material"


def test_planning_uses_real_pipeline_and_persists_generation_audit_metadata() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )

    plan = service.create_initial_plan(repository.run["run_code"], {"requested_by": "planner"})

    assert plan["status"] == "ready"
    assert plan["pipeline_output"]["build_plan"]["build_plan_code"] == "MT-BUILD-001"
    assert plan["pipeline_output"]["ready_for_go_live"] is False
    assert plan["pipeline_output"]["model_plan"]["scenes"]
    assert plan["pipeline_output"]["scene_plan"]["scenes"][0]["script"] == (
        plan["pipeline_output"]["model_plan"]["scenes"][0]["script"]
    )
    assert plan["pipeline_output"]["asset_need_plan"]["scenes"][0]["script"] == (
        plan["pipeline_output"]["model_plan"]["scenes"][0]["script"]
    )
    assert any(
        need["need_type"] == "background_image"
        for need in plan["pipeline_output"]["asset_need_plan"]["scenes"][0]["asset_needs"]
    )
    assert sum(
        scene["duration_seconds"] for scene in plan["pipeline_output"]["model_plan"]["scenes"]
    ) == 60
    assert (
        repository.plan_calls[0]["generation_strategy_revision"]
        == "test.maitu.creative-plan.v1"
    )
    assert repository.plan_calls[0]["generation_invocation_evidence_ref"] is None
    assert repository.plan_calls[0]["generation_prompt_version"] == "maitu-workbench-plan-v3"
    assert len(repository.plan_calls[0]["generation_input_fingerprint"]) == 64
    assert len(repository.plan_calls[0]["generation_output_fingerprint"]) == 64
    assert repository.requirements
    assert all(item["status"] == "selected" for item in repository.requirements)


def test_target_room_binding_requires_a_non_reference_room_and_invalidates_existing_plan() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )

    rebound = service.update_run_target_live_room(repository.run["run_code"], "fresh-draft-002")
    assert rebound is not None
    assert rebound["target_live_room_id"] == "fresh-draft-002"
    assert rebound["status"] == "draft"

    repository.run["active_plan_revision"] = 1
    rebound = service.update_run_target_live_room(repository.run["run_code"], "fresh-draft-003")
    assert rebound is not None
    assert rebound["status"] == "replan_required"

    with pytest.raises(MaituWorkbenchConflictError, match="read-only"):
        service.update_run_target_live_room(repository.run["run_code"], "38995")


def test_run_creation_rejects_a_protected_reference_room_before_repository_writes() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )

    with pytest.raises(MaituWorkbenchConflictError, match="read-only"):
        service.create_run(
            {
                "title": "unsafe",
                "topic": "unsafe",
                "fact_card_code": repository.fact["fact_card_code"],
                "inventory_snapshot_code": repository.snapshot["snapshot_code"],
                "target_live_room_id": "38336",
            }
        )


def test_run_creation_pins_sanitized_published_reference_and_replan_reuses_snapshot() -> None:
    repository = FakeWorkbenchRepository()

    class RecordingProvider(DeterministicPlanGenerationProvider):
        def __init__(self) -> None:
            super().__init__()
            self.contexts: list[dict[str, Any]] = []

        def generate(self, context: dict[str, Any]) -> Any:
            self.contexts.append(deepcopy(context))
            return super().generate(context)

    provider = RecordingProvider()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=provider,
    )
    publication = _reference_publication()
    run = service.create_run(
        {
            "title": "固定参考模板运行",
            "topic": "按已核验事实生成一份新计划",
            "fact_card_code": repository.fact["fact_card_code"],
            "fact_card_version": 1,
            "inventory_snapshot_code": repository.snapshot["snapshot_code"],
            "target_duration_minutes": 1,
            "build_mode": "strict",
            "reference_template_code": publication["template_code"],
            "reference_template_revision_number": publication["revision_number"],
            "reference_template_projection_fingerprint": publication[
                "projection_fingerprint"
            ],
        }
    )

    assert run["reference_template_revision_number"] == 1
    snapshot = run["reference_template_snapshot"]
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "secret-component",
        "secret-scene-id",
        "ASSET-SECRET",
        "MATERIAL-SECRET",
        "SECRET-SESSION",
        "不得进入规划上下文",
    ):
        assert forbidden not in serialized
    assert snapshot["reference_mode"] == "reference_only"
    assert snapshot["layout_fidelity"] == "approximate"
    assert snapshot["blocking_reasons"] == [
        "component_source_is_not_verified",
        "speech_bus_overlap",
    ]

    service.create_initial_plan(run["run_code"], {"requested_by": "planner"})
    repository.reference_publication = None
    service.replan(
        run["run_code"],
        {
            "expected_plan_revision": 1,
            "reason": "人工决策后重新规划",
            "requested_by": "planner",
        },
    )

    assert repository.reference_resolution_count == 1
    assert len(provider.contexts) == 2
    assert provider.contexts[0]["reference_template"] == provider.contexts[1][
        "reference_template"
    ]
    reference_context = provider.contexts[0]["reference_template"]
    assert set(reference_context) == {
        "reference_mode",
        "layout_fidelity",
        "scene_sequence",
        "approximate_composition",
        "audio_policy",
        "blocking_reasons",
    }


@pytest.mark.parametrize(
    ("pin_field", "pin_value", "message"),
    [
        ("reference_template_revision_number", 2, "revision pin is stale"),
        ("reference_template_projection_fingerprint", "d" * 64, "fingerprint pin is stale"),
    ],
)
def test_run_creation_rejects_stale_reference_template_pins(
    pin_field: str,
    pin_value: Any,
    message: str,
) -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    payload = {
        "title": "固定参考模板运行",
        "topic": "测试 stale pin",
        "fact_card_code": repository.fact["fact_card_code"],
        "fact_card_version": 1,
        "inventory_snapshot_code": repository.snapshot["snapshot_code"],
        "reference_template_code": "LR-TPL-001",
        "reference_template_revision_number": 1,
        "reference_template_projection_fingerprint": "c" * 64,
        pin_field: pin_value,
    }

    with pytest.raises(MaituWorkbenchConflictError, match=message):
        service.create_run(payload)


def test_run_creation_rejects_a_partial_reference_template_pin() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )

    with pytest.raises(MaituWorkbenchConflictError, match="must be pinned together"):
        service.create_run(
            {
                "title": "不完整固定版本",
                "topic": "拒绝只提供模板编号",
                "fact_card_code": repository.fact["fact_card_code"],
                "inventory_snapshot_code": repository.snapshot["snapshot_code"],
                "reference_template_code": "LR-TPL-001",
            }
        )


def test_run_creation_without_reference_template_preserves_existing_path() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )

    run = service.create_run(
        {
            "title": "无参考模板运行",
            "topic": "继续使用原有创建路径",
            "fact_card_code": repository.fact["fact_card_code"],
            "fact_card_version": 1,
            "inventory_snapshot_code": repository.snapshot["snapshot_code"],
        }
    )

    assert repository.reference_resolution_count == 0
    assert repository.created_reference_template is None
    assert "reference_template_code" not in run


def test_replan_carries_manual_waiver_and_blocks_required_material() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    service.create_initial_plan(repository.run["run_code"], {})
    required = next(item for item in repository.requirements if item["is_required"])
    repository.overrides = [
        {
            "requirement_key": required["requirement_key"],
            "decision": "waived",
            "selected_asset_code": None,
            "selected_material_key": None,
            "reason": "演示中暂不使用该图层",
            "decided_by": "reviewer",
            "created_at": NOW,
        }
    ]

    replanned = service.replan(
        repository.run["run_code"],
        {"expected_plan_revision": 1, "reason": "应用人工素材决策"},
    )

    assert replanned["revision_number"] == 2
    assert replanned["status"] == "blocked"
    carried = next(item for item in repository.requirements if item["requirement_key"] == required["requirement_key"])
    assert carried["status"] == "waived"
    assert carried["decisions"][0]["decision_source"] == "carried_forward"
    assert any(reason.startswith("required_material_unresolved:") for reason in replanned["blocked_reasons"])
    json.dumps(replanned["pipeline_output"], ensure_ascii=False)


def test_automatic_selection_is_restricted_to_the_frozen_inventory_snapshot() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(material_id="outside-snapshot"),
        generation_provider=DeterministicPlanGenerationProvider(),
    )

    plan = service.create_initial_plan(repository.run["run_code"], {})

    assert plan["status"] == "blocked"
    assert plan["pipeline_output"]["asset_selection_plan"]["selected_count"] == 0
    assert plan["pipeline_output"]["gap_report"]["blocking_gap_count"] > 0


def test_model_unavailable_fails_closed_before_pipeline_persistence() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=UnavailablePlanGenerationProvider("missing model credential"),
    )

    with pytest.raises(WorkbenchModelUnavailableError):
        service.create_initial_plan(repository.run["run_code"], {})

    assert repository.failed == (
        "MODEL_UNAVAILABLE",
        "Creative-plan model strategy is unavailable",
    )
    assert repository.plan_calls == []


def test_preflight_and_execution_payload_remain_draft_only() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    service.create_initial_plan(repository.run["run_code"], {})

    preflight = service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1, "performed_by": "reviewer"},
        room_verifier=fresh_blank_room_verifier,
    )
    job = service.create_draft_execution_job(
        repository.run["run_code"],
        {"expected_plan_revision": 1, "queued_by": "reviewer"},
        room_verifier=fresh_blank_room_verifier,
    )

    assert preflight["status"] == "passed"
    assert job["payload"]["ready_for_go_live"] is False
    assert job["payload"]["safety_boundary"]["go_live_permitted"] is False
    operation_types = {
        operation["operation_type"] for operation in job["payload"]["build_plan"]["operations"]
    }
    assert "go_live" not in operation_types

    with pytest.raises(WorkbenchDraftSafetyError):
        assert_draft_only({"operation_type": "go_live"})
    with pytest.raises(WorkbenchDraftSafetyError):
        assert_draft_only({"ready_for_go_live": True})


def test_draft_execution_rejects_a_preflight_that_became_stale() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    service.create_initial_plan(repository.run["run_code"], {})
    service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1},
        room_verifier=fresh_blank_room_verifier,
    )
    repository.run["fact_card_version"]["status"] = "superseded"

    with pytest.raises(MaituWorkbenchConflictError, match="no longer current"):
        service.create_draft_execution_job(
            repository.run["run_code"],
            {"expected_plan_revision": 1},
            room_verifier=fresh_blank_room_verifier,
        )


def test_preflight_blocks_only_selected_material_analysis_conflicts() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    service.create_initial_plan(repository.run["run_code"], {})
    repository.analysis_blockers = [
        {
            "conflict_code": "MT-MAT-CON-001",
            "analysis_code": "MT-MAT-AN-001",
            "asset_code": "ASSET-PRODUCT_VIDEO",
            "severity": "critical",
            "resolution": None,
        }
    ]

    preflight = service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1},
        room_verifier=fresh_blank_room_verifier,
    )

    assert preflight["status"] == "blocked"
    analysis_check = next(
        check for check in preflight["checks"] if check["code"] == "selected_video_analysis_conflicts"
    )
    assert analysis_check["passed"] is False
    repository.analysis_blockers = []
    assert service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1},
        room_verifier=fresh_blank_room_verifier,
    )["status"] == "passed"


def test_preflight_requires_backend_blank_room_attestation() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    service.create_initial_plan(repository.run["run_code"], {})

    preflight = service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1},
    )

    assert preflight["status"] == "blocked"
    authority_check = next(
        check for check in preflight["checks"] if check["code"] == "authoritative_blank_draft"
    )
    assert authority_check["passed"] is False


def test_preflight_independently_rejects_a_dynamically_protected_target_room() -> None:
    repository = FakeWorkbenchRepository()
    repository.protected_resources[("maitu_room", "room-draft-001")] = {
        "protection_mode": "deny_write",
        "allowed_capabilities": [],
        "reason_code": "PRODUCTION_HOLD",
    }
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    service.create_initial_plan(repository.run["run_code"], {})

    preflight = service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1},
        room_verifier=fresh_blank_room_verifier,
    )

    target_check = next(check for check in preflight["checks"] if check["code"] == "target_room")
    assert preflight["status"] == "blocked"
    assert target_check["passed"] is False
    assert target_check["evidence"]["registry_reason"] == "PROTECTED_RESOURCE_DENY_WRITE"


def test_draft_execution_rechecks_authoritative_room_evidence() -> None:
    repository = FakeWorkbenchRepository()
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(),
    )
    scene_id = {"value": "default-scene-001"}

    def changing_room_verifier(
        live_room_id: str,
        protected_room_ids: set[str] | frozenset[str],
    ) -> dict[str, Any]:
        evidence = fresh_blank_room_verifier(live_room_id, protected_room_ids)
        evidence["default_scene_id"] = scene_id["value"]
        return evidence

    service.create_initial_plan(repository.run["run_code"], {})
    service.preflight(
        repository.run["run_code"],
        {"expected_plan_revision": 1},
        room_verifier=changing_room_verifier,
    )
    scene_id["value"] = "replacement-default-scene"

    with pytest.raises(MaituWorkbenchConflictError, match="fingerprint is stale"):
        service.create_draft_execution_job(
            repository.run["run_code"],
            {"expected_plan_revision": 1},
            room_verifier=changing_room_verifier,
        )


class FakeDeepSeekClient:
    def __init__(self, content: dict[str, Any]) -> None:
        self.content = content
        self.call: dict[str, Any] | None = None

    def generate_json(self, **kwargs: Any) -> ModelInvocation:
        self.call = kwargs
        return ModelInvocation(
            provider="deepseek",
            requested_model=kwargs["model"],
            actual_model="deepseek-v4-pro-202607",
            response_id="chatcmpl-test",
            content=self.content,
            usage={"input_tokens": 10, "output_tokens": 20},
            input_fingerprint="c" * 64,
            output_fingerprint="d" * 64,
            latency_ms=42,
        )


class MemoryProviderEvidenceSink:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def persist_provider_invocation(self, evidence: dict[str, Any]) -> str:
        self.items.append(evidence)
        return "ART-PROVIDER-TEST"


def _routed_plan_provider(
    client: Any,
) -> tuple[RoutedPlanGenerationProvider, MemoryProviderEvidenceSink]:
    sink = MemoryProviderEvidenceSink()
    adapter = OpenAICompatibleStructuredAdapter(
        client,
        adapter_code="deepseek-chat-test.v1",
        provider_code="deepseek",
    )
    router = ProviderRouter(
        [
            ProviderBinding(
                strategy_revision="maitu.creative-plan.v2",
                capability=ModelCapability.STRUCTURED_GENERATION,
                adapter=adapter,
                provider_model="deepseek-v4-pro",
                allowed_classifications=frozenset(
                    {DataClassification.CONFIDENTIAL}
                ),
            )
        ],
        sink,
    )
    return RoutedPlanGenerationProvider(router), sink


def _deepseek_model_output() -> dict[str, Any]:
    return {
        "title": "完整场景计划",
        "host_persona": "专业、克制",
        "target_audience": "按用途选购的用户",
        "selling_angle": "使用已核验事实建立选择标准",
        "scenes": [
            {
                "scene_name": "开场",
                "scene_goal": "opening",
                "duration_seconds": 20,
                "script": "允许的开场句。",
                "keywords": ["商品"],
                "composition_intent": "建立清晰的商品讲解区域",
                "material_intents": [
                    {
                        "need_type": "background_image",
                        "required_category": "background_image",
                        "accepted_asset_types": ["IMG"],
                        "description": "主题背景",
                        "keywords": ["背景"],
                        "priority": "high",
                    }
                ],
            },
            {
                "scene_name": "商品事实",
                "scene_goal": "product_explanation",
                "duration_seconds": 40,
                "script": "允许的商品事实。",
                "keywords": ["商品"],
                "composition_intent": "商品主体与主播同时可见",
                "material_intents": [
                    {
                        "need_type": "product_image",
                        "required_category": "product_image",
                        "accepted_asset_types": ["IMG"],
                        "description": "商品主图",
                        "keywords": ["商品主图"],
                        "priority": "high",
                    }
                ],
            },
        ],
        "compliance_focus": ["不使用未核验优惠"],
    }


def test_routed_plan_strategy_uses_json_contract_and_is_provider_neutral() -> None:
    client = FakeDeepSeekClient(_deepseek_model_output())
    provider, sink = _routed_plan_provider(client)

    result = provider.generate(
        {
            "approved_product_facts": {"product_name": "demo"},
            "request_context": {"open_id": "sensitive-user-123"},
        }
    )

    assert client.call is not None
    assert client.call["provider"] == "deepseek"
    assert client.call["model"] == "deepseek-v4-pro"
    assert client.call["temperature"] == 0.2
    system_prompt = client.call["messages"][0]["content"]
    assert "reference_only / approximate" in system_prompt
    assert "不得把它当作精确麦兔组件" in system_prompt
    assert "不得把其中任何文案当作产品事实" in system_prompt
    user_payload = json.loads(client.call["messages"][1]["content"])
    schema = user_payload["creative_plan_json_schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["scenes"]["maxItems"] == 12
    assert schema["$defs"]["_CreativeScene"]["properties"]["scene_goal"]["enum"] == [
        "opening",
        "product_explanation",
        "explanation",
        "conversion",
        "transition",
        "closing",
    ]
    assert user_payload["material_taxonomy"]["digital_human"] == {
        "required_category": "digital_human_video",
        "accepted_asset_types": ["IMG", "VID"],
    }
    assert user_payload["context"]["request_context"]["open_id"] == "[REDACTED]"
    assert "sensitive-user-123" not in client.call["messages"][1]["content"]
    assert result.strategy_revision == "maitu.creative-plan.v2"
    assert result.invocation_evidence_ref == "ART-PROVIDER-TEST"
    assert len(result.input_fingerprint) == 64
    assert len(result.output_fingerprint) == 64
    assert sink.items[0]["actual_model"] == "deepseek-v4-pro-202607"
    assert sink.items[0]["provider_response_id"] == "chatcmpl-test"
    assert sink.items[0]["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert sink.items[0]["input_redaction_count"] == 1


def test_routed_plan_strategy_rejects_malformed_model_output() -> None:
    provider, _sink = _routed_plan_provider(FakeDeepSeekClient({"title": "missing fields"}))

    with pytest.raises(WorkbenchModelGenerationError):
        provider.generate({"approved_product_facts": {}})


def test_routed_plan_strategy_classifies_non_json_content_as_unavailable() -> None:
    class NonJSONClient:
        def generate_json(self, **_kwargs: Any) -> ModelInvocation:
            raise OnlineModelError("chat response content was not valid JSON")

    provider, _sink = _routed_plan_provider(NonJSONClient())

    with pytest.raises(WorkbenchModelUnavailableError, match="could not produce"):
        provider.generate({"approved_product_facts": {}})


def test_routed_plan_strategy_preserves_transport_failure_as_unavailable() -> None:
    class UnavailableClient:
        def generate_json(self, **_kwargs: Any) -> ModelInvocation:
            raise OnlineModelError("upstream timed out", retryable=True)

    provider, _sink = _routed_plan_provider(UnavailableClient())

    with pytest.raises(WorkbenchModelUnavailableError, match="could not produce"):
        provider.generate({"approved_product_facts": {}})


def test_approved_keyword_catalog_includes_fact_card_compliance_notes() -> None:
    repository = FakeWorkbenchRepository()
    repository.fact["content"]["compliance_notes"] = ["理性饮酒"]

    context = MaituWorkbenchService._generation_context(
        repository.run,
        repository.fact,
        repository.snapshot,
        [],
        None,
    )

    assert "理性饮酒" in context["allowed_keywords"]


def test_approved_keyword_catalog_normalizes_unicode_whitespace() -> None:
    repository = FakeWorkbenchRepository()
    repository.snapshot["items"][0]["title"] = "素材编号\u00a0商品视频.mov"

    context = MaituWorkbenchService._generation_context(
        repository.run,
        repository.fact,
        repository.snapshot,
        [],
        None,
    )

    assert "素材编号 商品视频.mov" in context["allowed_keywords"]
    assert "素材编号\u00a0商品视频.mov" not in context["allowed_keywords"]


@pytest.mark.parametrize("invalid_kind", ["duration", "ungrounded_script"])
def test_planning_rejects_invalid_duration_and_ungrounded_model_script(invalid_kind: str) -> None:
    repository = FakeWorkbenchRepository()
    context = MaituWorkbenchService._generation_context(
        repository.run,
        repository.fact,
        repository.snapshot,
        [],
        None,
    )
    content = DeterministicPlanGenerationProvider().generate(context).content
    if invalid_kind == "duration":
        content["scenes"][0]["duration_seconds"] += 1
    else:
        content["scenes"][0]["script"] += "这是事实卡中不存在的新承诺。"
    service = MaituWorkbenchService(
        repository,
        FakeMaituRepository(),
        generation_provider=DeterministicPlanGenerationProvider(content),
    )

    with pytest.raises(WorkbenchModelGenerationError):
        service.create_initial_plan(repository.run["run_code"], {})

    assert repository.failed == (
        "MODEL_OUTPUT_INVALID",
        "Creative-plan model strategy output is invalid",
    )
    assert repository.plan_calls == []
