from __future__ import annotations

from typing import Any

from app.services.livestream_script_writer import LivestreamScriptWriter
from app.services.script_asset_gap_reporter import ScriptAssetGapReporter
from app.services.script_asset_need_planner import ScriptAssetNeedPlanner
from app.services.script_asset_selector import ScriptAssetSelector
from app.services.script_layout_build_plan_builder import ScriptLayoutBuildPlanBuilder
from app.services.script_layout_planner import ScriptLayoutPlanner

SOURCE = "script_driven_build_pipeline_v1"
STAGE_ORDER = [
    "script_generation_and_quality_gate",
    "script_scene_plan",
    "script_asset_needs",
    "script_asset_selections",
    "script_asset_gap_report",
    "script_layout_plan",
    "script_layout_build_plan",
]


class ScriptDrivenBuildPipeline:
    """Run script generation as Stage 0 of the content-driven room builder."""

    def __init__(self, repository: Any, *, writer: LivestreamScriptWriter | None = None):
        self.repository = repository
        self.writer = writer or LivestreamScriptWriter()

    def run(
        self,
        script_request: dict[str, Any],
        *,
        build_mode: str = "strict",
        target_live_room_id: str | None = None,
        include_default_host: bool = True,
        max_candidates_per_need: int = 1,
        canvas_width: int = 1080,
        canvas_height: int = 1920,
    ) -> dict[str, Any]:
        script_draft = self.writer.generate(script_request)
        scene_plan = dict(script_draft["scene_plan_payload"])
        asset_need_plan = ScriptAssetNeedPlanner().plan(
            scene_plan["scenes"],
            include_default_host=include_default_host,
            include_script_text_need=True,
        )
        asset_selection_plan = ScriptAssetSelector(self.repository).select(
            asset_need_plan["scenes"],
            max_candidates_per_need=max_candidates_per_need,
        )
        gap_report = ScriptAssetGapReporter().report(asset_selection_plan["scenes"])
        layout_plan = ScriptLayoutPlanner().plan(
            asset_selection_plan["scenes"],
            build_mode=build_mode,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
        build_plan = ScriptLayoutBuildPlanBuilder().build(
            layout_plan,
            target_live_room_id=target_live_room_id,
        )

        if script_draft["manual_review_required"]:
            self._apply_script_quality_gate(build_plan)
            status = "script_quality_review_required"
        elif build_plan.get("can_execute"):
            status = "ready_for_draft_build"
        elif int(gap_report.get("blocking_gap_count") or 0) > 0:
            status = "blocked_missing_required_assets"
        else:
            status = "manual_review_required"

        build_plan = self.repository.create_script_layout_build_plan(
            build_plan,
            plan_name=f"{script_draft['title']} 剧本驱动 BuildPlan",
        )

        return {
            "source": SOURCE,
            "status": status,
            "ready_for_go_live": False,
            "script_draft": script_draft,
            "scene_plan": scene_plan,
            "asset_need_plan": asset_need_plan,
            "asset_selection_plan": asset_selection_plan,
            "gap_report": gap_report,
            "layout_plan": layout_plan,
            "build_plan": build_plan,
            "stage_order": STAGE_ORDER,
        }

    @staticmethod
    def _apply_script_quality_gate(build_plan: dict[str, Any]) -> None:
        build_plan["can_execute"] = False
        build_plan["manual_review_required"] = True
        build_plan["status"] = "manual_review_required"
        reasons = list(build_plan.get("blocked_reasons") or [])
        if "script_quality_review_required" not in reasons:
            reasons.append("script_quality_review_required")
        build_plan["blocked_reasons"] = reasons
        safe_review_operations = {"preflight_content_build_plan", "verify_scene"}
        for operation in build_plan.get("operations") or []:
            if operation.get("operation_type") in safe_review_operations:
                continue
            operation["status"] = "blocked_script_quality"
            operation["blocked_reason"] = "script_quality_review_required"
            if operation.get("operation_type") in {"save_draft", "verify_draft_persisted"}:
                operation["instruction"] = (
                    "剧本质量或目标时长素材仍需人工复核；只允许审阅草稿，不点击正式开播。"
                )
