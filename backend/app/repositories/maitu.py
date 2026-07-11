from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.secret_hygiene import contains_durable_secret
from app.services.code_generator import (
    BusinessObjectType,
    format_jd_live_metric_session_code,
    format_maitu_build_plan_code,
    format_maitu_layout_adjustment_code,
    format_maitu_execution_code,
    format_maitu_plan_code,
    format_maitu_retry_task_code,
    format_maitu_slot_code,
)


class RetryLeaseConflictError(RuntimeError):
    """The retry task lease is missing, expired, or owned by another claim."""


class RetryExecutionConflictError(RuntimeError):
    """An idempotency key was reused for a different retry execution result."""


class RetryCheckpointConflictError(RuntimeError):
    """A retry operation checkpoint conflicts with authoritative intent or state."""


class MaituMaterialSlotRepository:
    writable_fields = (
        "slot_name",
        "maitu_project_code",
        "scene_name",
        "scene_index",
        "layer_name",
        "layer_index",
        "required_category",
        "accepted_asset_types",
        "aspect_ratio",
        "left_position",
        "top_position",
        "width",
        "height",
        "z_index",
        "replacement_policy",
        "description",
    )

    def __init__(self, connection: Connection):
        self.connection = connection

    def import_reference_blueprint(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = dict(payload["reference_profile"])
        blueprint = dict(payload["blueprint"])
        profile_code = str(profile["profile_code"])
        blueprint_code = str(blueprint["blueprint_code"])
        reference_profile_code = str(blueprint.get("reference_profile_code") or profile_code)
        reference_room_id = blueprint.get("reference_room_id") or profile.get("reference_room_id")
        reference_room_name = blueprint.get("reference_room_name") or profile.get("reference_room_name")
        platform = blueprint.get("platform") or profile.get("platform")
        material_tabs = blueprint.get("material_tabs") or profile.get("material_tabs") or []
        workbench_tabs = blueprint.get("workbench_tabs") or profile.get("workbench_tabs") or []

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_reference_room_profiles (
                    profile_code, source, source_url, page_title, reference_room_id,
                    reference_room_name, platform, active_scene_name, logged_in,
                    login_required, scenes, active_scene_layers, material_tabs,
                    workbench_tabs, script_texts, raw_profile
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (profile_code)
                DO UPDATE SET
                    source = EXCLUDED.source,
                    source_url = EXCLUDED.source_url,
                    page_title = EXCLUDED.page_title,
                    reference_room_id = EXCLUDED.reference_room_id,
                    reference_room_name = EXCLUDED.reference_room_name,
                    platform = EXCLUDED.platform,
                    active_scene_name = EXCLUDED.active_scene_name,
                    logged_in = EXCLUDED.logged_in,
                    login_required = EXCLUDED.login_required,
                    scenes = EXCLUDED.scenes,
                    active_scene_layers = EXCLUDED.active_scene_layers,
                    material_tabs = EXCLUDED.material_tabs,
                    workbench_tabs = EXCLUDED.workbench_tabs,
                    script_texts = EXCLUDED.script_texts,
                    raw_profile = EXCLUDED.raw_profile,
                    updated_at = now(),
                    deleted_at = NULL
                RETURNING *
                """,
                (
                    profile_code,
                    profile.get("source") or "browser_use_observe",
                    profile.get("source_url"),
                    profile.get("page_title"),
                    reference_room_id,
                    reference_room_name,
                    profile.get("platform"),
                    profile.get("active_scene_name"),
                    bool(profile.get("logged_in", False)),
                    bool(profile.get("login_required", False)),
                    Jsonb(profile.get("scenes") or []),
                    Jsonb(profile.get("active_scene_layers") or []),
                    Jsonb(profile.get("material_tabs") or []),
                    Jsonb(profile.get("workbench_tabs") or []),
                    Jsonb(profile.get("script_texts") or []),
                    Jsonb(profile),
                ),
            )
            profile_row = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO maitu_live_room_blueprints (
                    blueprint_code, reference_profile_id, reference_profile_code, title,
                    platform, room_type, reference_room_id, reference_room_name, status,
                    description, scenes, script_blocks, material_tabs, workbench_tabs,
                    safety_rules, raw_blueprint
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (blueprint_code)
                DO UPDATE SET
                    reference_profile_id = EXCLUDED.reference_profile_id,
                    reference_profile_code = EXCLUDED.reference_profile_code,
                    title = EXCLUDED.title,
                    platform = EXCLUDED.platform,
                    room_type = EXCLUDED.room_type,
                    reference_room_id = EXCLUDED.reference_room_id,
                    reference_room_name = EXCLUDED.reference_room_name,
                    status = EXCLUDED.status,
                    description = EXCLUDED.description,
                    scenes = EXCLUDED.scenes,
                    script_blocks = EXCLUDED.script_blocks,
                    material_tabs = EXCLUDED.material_tabs,
                    workbench_tabs = EXCLUDED.workbench_tabs,
                    safety_rules = EXCLUDED.safety_rules,
                    raw_blueprint = EXCLUDED.raw_blueprint,
                    updated_at = now(),
                    deleted_at = NULL
                RETURNING *
                """,
                (
                    blueprint_code,
                    profile_row["id"],
                    reference_profile_code,
                    blueprint.get("title") or f"参考直播间 {reference_room_id} 重建蓝图",
                    platform,
                    blueprint.get("room_type") or "reference_rebuild",
                    reference_room_id,
                    reference_room_name,
                    blueprint.get("status") or "draft",
                    blueprint.get("description"),
                    Jsonb(blueprint.get("scenes") or []),
                    Jsonb(blueprint.get("script_blocks") or []),
                    Jsonb(material_tabs),
                    Jsonb(workbench_tabs),
                    Jsonb(blueprint.get("safety_rules") or []),
                    Jsonb(blueprint),
                ),
            )
            blueprint_row = cursor.fetchone()
            self._rebuild_live_room_template_component_index(cursor, blueprint_row, blueprint, profile)
        self.connection.commit()
        return self.get_live_room_blueprint_by_code(blueprint_code) or {}

    def list_live_room_blueprints(
        self,
        *,
        reference_room_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["b.deleted_at IS NULL", "p.deleted_at IS NULL"]
        values: list[Any] = []
        if reference_room_id is not None:
            where_clauses.append("b.reference_room_id = %s")
            values.append(reference_room_id)
        if status is not None:
            where_clauses.append("b.status = %s")
            values.append(status)
        if q:
            like_query = f"%{q}%"
            where_clauses.append(
                "(" 
                "b.blueprint_code ILIKE %s OR b.title ILIKE %s OR "
                "b.reference_room_id ILIKE %s OR b.reference_room_name ILIKE %s OR "
                "b.description ILIKE %s OR b.scenes::text ILIKE %s OR "
                "b.script_blocks::text ILIKE %s OR b.raw_blueprint::text ILIKE %s OR "
                "p.raw_profile::text ILIKE %s"
                ")"
            )
            values.extend([like_query] * 9)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT b.*, p.raw_profile AS reference_profile
                FROM maitu_live_room_blueprints b
                JOIN maitu_reference_room_profiles p ON p.id = b.reference_profile_id
                WHERE {' AND '.join(where_clauses)}
                ORDER BY b.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_live_room_blueprint(row) for row in rows]

    def list_live_room_template_scenes(
        self,
        *,
        blueprint_code: str | None = None,
        reference_room_id: str | None = None,
        template_library_code: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["s.deleted_at IS NULL", "b.deleted_at IS NULL"]
        values: list[Any] = []
        if blueprint_code is not None:
            where_clauses.append("s.blueprint_code = %s")
            values.append(blueprint_code)
        if reference_room_id is not None:
            where_clauses.append("b.reference_room_id = %s")
            values.append(reference_room_id)
        if template_library_code is not None:
            where_clauses.append("s.template_library_code = %s")
            values.append(template_library_code)
        if status is not None:
            where_clauses.append("b.status = %s")
            values.append(status)
        if q:
            like_query = f"%{q}%"
            where_clauses.append(
                "(s.scene_template_code ILIKE %s OR s.scene_name ILIKE %s OR "
                "s.reference_product_name ILIKE %s OR s.script_content ILIKE %s OR s.raw_scene::text ILIKE %s)"
            )
            values.extend([like_query] * 5)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT s.*
                FROM maitu_live_room_template_scenes s
                JOIN maitu_live_room_blueprints b ON b.blueprint_code = s.blueprint_code
                WHERE {' AND '.join(where_clauses)}
                ORDER BY b.created_at DESC, s.sort_order ASC NULLS LAST, s.scene_template_code ASC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_live_room_template_scene(row) for row in rows]

    def list_live_room_template_scene_components(self, scene_template_code: str) -> list[dict[str, Any]] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM maitu_live_room_template_scenes
                WHERE scene_template_code = %s AND deleted_at IS NULL
                LIMIT 1
                """,
                (scene_template_code,),
            )
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                """
                SELECT *
                FROM maitu_live_room_template_components
                WHERE scene_template_code = %s AND deleted_at IS NULL
                ORDER BY sort_order ASC NULLS LAST, z_index ASC NULLS LAST, component_template_code ASC
                """,
                (scene_template_code,),
            )
            rows = cursor.fetchall()
        return [self._normalize_live_room_template_component(row) for row in rows]

    def search_live_room_scene_components_by_script(
        self,
        *,
        q: str,
        reference_room_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        index_results = self._search_live_room_scene_components_by_script_from_index(
            q=q,
            reference_room_id=reference_room_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        if index_results:
            return index_results

        where_clauses = ["b.deleted_at IS NULL", "p.deleted_at IS NULL", "b.script_blocks::text ILIKE %s"]
        values: list[Any] = [f"%{q}%"]
        if reference_room_id is not None:
            where_clauses.append("b.reference_room_id = %s")
            values.append(reference_room_id)
        if status is not None:
            where_clauses.append("b.status = %s")
            values.append(status)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT b.*, p.raw_profile AS reference_profile
                FROM maitu_live_room_blueprints b
                JOIN maitu_reference_room_profiles p ON p.id = b.reference_profile_id
                WHERE {' AND '.join(where_clauses)}
                ORDER BY b.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            blueprint = self._normalize_live_room_blueprint(row)
            results.extend(self._scene_component_search_result(blueprint, q))
        return results

    def get_live_room_blueprint_by_code(self, blueprint_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT b.*, p.raw_profile AS reference_profile
                FROM maitu_live_room_blueprints b
                JOIN maitu_reference_room_profiles p ON p.id = b.reference_profile_id
                WHERE b.blueprint_code = %s AND b.deleted_at IS NULL AND p.deleted_at IS NULL
                """,
                (blueprint_code,),
            )
            row = cursor.fetchone()
        return self._normalize_live_room_blueprint(row) if row else None

    def create_live_room_build_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        blueprint = self.get_live_room_blueprint_by_code(payload["blueprint_code"])
        if blueprint is None:
            return None
        build_plan_code = self._next_build_plan_code()
        plan_name = payload.get("plan_name") or f"{blueprint['title']} BuildPlan"
        auto_select_assets = bool(payload.get("auto_select_assets")) or payload.get("strategy") == "script_context_best_match"
        operations = self._build_live_room_operations_from_blueprint(
            blueprint,
            auto_select_assets=auto_select_assets,
            selection_query=payload.get("selection_query") or payload.get("description"),
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_live_room_build_plans (
                    build_plan_code, blueprint_code, plan_name, target_app, executor,
                    status, strategy, description
                )
                VALUES (%s, %s, %s, 'maitu', 'browser_use', 'draft', %s, %s)
                RETURNING *
                """,
                (
                    build_plan_code,
                    blueprint["blueprint_code"],
                    plan_name,
                    payload.get("strategy", "reference_rebuild_dry_run"),
                    payload.get("description"),
                ),
            )
            plan = cursor.fetchone()
            for operation in operations:
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_build_plan_operations (
                        build_plan_id, build_plan_code, operation_type, operation_name,
                        sort_order, status, scene_name, layer_name, layer_role,
                        required_category, accepted_asset_types, replacement_policy,
                        selected_asset_code, selected_asset_title, selected_asset_display_code,
                        selected_asset_local_file_code, selected_asset_original_filename,
                        selected_asset_local_relative_path, selected_asset_browser_use_hint,
                        match_score, match_reasons, selection_source,
                        script_block_code, script_block_content, instruction, details
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        plan["id"],
                        build_plan_code,
                        operation["operation_type"],
                        operation["operation_name"],
                        operation["sort_order"],
                        operation["status"],
                        operation.get("scene_name"),
                        operation.get("layer_name"),
                        operation.get("layer_role"),
                        operation.get("required_category"),
                        Jsonb(operation.get("accepted_asset_types") or []),
                        operation.get("replacement_policy"),
                        operation.get("selected_asset_code"),
                        operation.get("selected_asset_title"),
                        operation.get("selected_asset_display_code"),
                        operation.get("selected_asset_local_file_code"),
                        operation.get("selected_asset_original_filename"),
                        operation.get("selected_asset_local_relative_path"),
                        operation.get("selected_asset_browser_use_hint"),
                        operation.get("match_score"),
                        Jsonb(operation.get("match_reasons") or []),
                        operation.get("selection_source"),
                        operation.get("script_block_code"),
                        operation.get("script_block_content"),
                        operation["instruction"],
                        Jsonb(operation.get("details") or {}),
                    ),
                )
        self.connection.commit()
        return self.get_live_room_build_plan_by_code(build_plan_code) or self._normalize_live_room_build_plan(plan)

    def create_live_room_scene_build_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        scenes = self.list_live_room_template_scenes(
            blueprint_code=payload.get("blueprint_code"),
            reference_room_id=payload.get("reference_room_id"),
            template_library_code=payload.get("template_library_code"),
            status=payload.get("status"),
            q=payload["script_query"],
            limit=1,
            offset=0,
        )
        if not scenes:
            return None
        scene = scenes[0]
        blueprint = self.get_live_room_blueprint_by_code(scene["blueprint_code"])
        if blueprint is None:
            return None
        components = self.list_live_room_template_scene_components(scene["scene_template_code"]) or []
        build_plan_code = self._next_build_plan_code()
        plan_name = payload.get("plan_name") or f"{scene['scene_name']} SceneBuildPlan dry-run"
        operations = self._build_single_scene_template_operations(
            scene,
            components,
            script_query=payload["script_query"],
            target_script_content=payload.get("target_script_content"),
            target_live_room_id=payload.get("target_live_room_id"),
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_live_room_build_plans (
                    build_plan_code, blueprint_code, plan_name, target_app, executor,
                    status, strategy, description
                )
                VALUES (%s, %s, %s, 'maitu', 'browser_use', 'draft', %s, %s)
                RETURNING *
                """,
                (
                    build_plan_code,
                    scene["blueprint_code"],
                    plan_name,
                    payload.get("strategy", "template_scene_dry_run"),
                    payload.get("description") or f"单场景 dry-run：基于 {scene['scene_name']} 的模板组件索引生成。",
                ),
            )
            plan = cursor.fetchone()
            for operation in operations:
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_build_plan_operations (
                        build_plan_id, build_plan_code, operation_type, operation_name,
                        sort_order, status, scene_name, layer_name, layer_role,
                        required_category, accepted_asset_types, replacement_policy,
                        selected_asset_code, selected_asset_title, selected_asset_display_code,
                        selected_asset_local_file_code, selected_asset_original_filename,
                        selected_asset_local_relative_path, selected_asset_browser_use_hint,
                        match_score, match_reasons, selection_source,
                        script_block_code, script_block_content, instruction, details
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        plan["id"],
                        build_plan_code,
                        operation["operation_type"],
                        operation["operation_name"],
                        operation["sort_order"],
                        operation["status"],
                        operation.get("scene_name"),
                        operation.get("layer_name"),
                        operation.get("layer_role"),
                        operation.get("required_category"),
                        Jsonb(operation.get("accepted_asset_types") or []),
                        operation.get("replacement_policy"),
                        operation.get("selected_asset_code"),
                        operation.get("selected_asset_title"),
                        operation.get("selected_asset_display_code"),
                        operation.get("selected_asset_local_file_code"),
                        operation.get("selected_asset_original_filename"),
                        operation.get("selected_asset_local_relative_path"),
                        operation.get("selected_asset_browser_use_hint"),
                        operation.get("match_score"),
                        Jsonb(operation.get("match_reasons") or []),
                        operation.get("selection_source"),
                        operation.get("script_block_code"),
                        operation.get("script_block_content"),
                        operation["instruction"],
                        Jsonb(operation.get("details") or {}),
                    ),
                )
        self.connection.commit()
        return self.get_live_room_build_plan_by_code(build_plan_code) or self._normalize_live_room_build_plan(plan)

    def get_live_room_build_plan_by_code(self, build_plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_live_room_build_plans
                WHERE build_plan_code = %s AND deleted_at IS NULL
                """,
                (build_plan_code,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        plan = self._normalize_live_room_build_plan(row)
        plan["operations"] = self._fetch_live_room_build_plan_operations(build_plan_code)
        return plan

    def get_live_room_build_plan_operations(self, build_plan_code: str) -> dict[str, Any] | None:
        plan = self.get_live_room_build_plan_by_code(build_plan_code)
        if plan is None:
            return None
        blueprint = self.get_live_room_blueprint_by_code(plan["blueprint_code"])
        operations = plan.get("operations", [])
        preflight = next(
            (
                operation
                for operation in operations
                if isinstance(operation, dict)
                and operation.get("operation_type") in {"preflight_scene_build_plan", "preflight_build_plan"}
            ),
            None,
        )
        preflight_details = preflight.get("details") if isinstance(preflight, dict) and isinstance(preflight.get("details"), dict) else {}
        return {
            "build_plan_code": plan["build_plan_code"],
            "blueprint_code": plan["blueprint_code"],
            "reference_room_id": blueprint.get("reference_room_id") if blueprint else None,
            "reference_room_name": blueprint.get("reference_room_name") if blueprint else None,
            "target_live_room_id": preflight_details.get("target_live_room_id"),
            "executor": plan["executor"],
            "target_app": plan["target_app"],
            "operations": operations,
        }

    def create_live_room_build_plan_execution_result(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.get_live_room_build_plan_by_code(build_plan_code)
        if plan is None:
            return None

        execution_code = self._next_execution_code()
        operation_results = payload.get("operation_results", [])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_live_room_build_plan_executions (
                    execution_code, build_plan_code, blueprint_code, executor,
                    execution_status, mode, started_at, finished_at, failure_type,
                    retryable, retry_instruction, error_message, screenshot_asset_code,
                    dom_snapshot_asset_code, result_summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    execution_code,
                    build_plan_code,
                    plan["blueprint_code"],
                    payload.get("executor", "browser_use"),
                    payload["execution_status"],
                    payload.get("mode", "non_destructive"),
                    payload.get("started_at"),
                    payload.get("finished_at"),
                    payload.get("failure_type"),
                    payload.get("retryable", False),
                    payload.get("retry_instruction"),
                    payload.get("error_message"),
                    payload.get("screenshot_asset_code"),
                    payload.get("dom_snapshot_asset_code"),
                    payload.get("result_summary"),
                ),
            )
            execution = cursor.fetchone()

            for sort_order, operation in enumerate(operation_results):
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_build_plan_operation_results (
                        execution_id, execution_code, build_plan_code, operation_index,
                        operation_type, operation_name, scene_name, layer_name, action_type,
                        status, failure_type, retryable, retry_instruction, error_message,
                        screenshot_asset_code, dom_snapshot_asset_code, details, sort_order
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        execution["id"],
                        execution_code,
                        build_plan_code,
                        operation["operation_index"],
                        operation["operation_type"],
                        operation.get("operation_name"),
                        operation.get("scene_name"),
                        operation.get("layer_name"),
                        operation.get("action_type"),
                        operation["status"],
                        operation.get("failure_type"),
                        operation.get("retryable", False),
                        operation.get("retry_instruction"),
                        operation.get("error_message"),
                        operation.get("screenshot_asset_code"),
                        operation.get("dom_snapshot_asset_code"),
                        Jsonb(operation.get("details", {})),
                        sort_order,
                    ),
                )

            cursor.execute(
                """
                UPDATE maitu_live_room_build_plans
                SET status = %s, updated_at = now()
                WHERE build_plan_code = %s AND deleted_at IS NULL
                """,
                (self._build_plan_status_from_execution(payload["execution_status"]), build_plan_code),
            )
        self.connection.commit()
        return self.get_live_room_build_plan_execution_result_by_code(build_plan_code, execution_code)

    def list_live_room_build_plan_execution_results(
        self,
        build_plan_code: str,
        *,
        executor: str | None = None,
        execution_status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if self.get_live_room_build_plan_by_code(build_plan_code) is None:
            return None
        where_clauses = ["build_plan_code = %s", "deleted_at IS NULL"]
        values: list[Any] = [build_plan_code]
        if executor is not None:
            where_clauses.append("executor = %s")
            values.append(executor)
        if execution_status is not None:
            where_clauses.append("execution_status = %s")
            values.append(execution_status)
        if mode is not None:
            where_clauses.append("mode = %s")
            values.append(mode)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_live_room_build_plan_executions
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_live_room_build_plan_execution(row) for row in rows]

    def get_live_room_build_plan_execution_result_by_code(
        self,
        build_plan_code: str,
        execution_code: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_live_room_build_plan_executions
                WHERE build_plan_code = %s AND execution_code = %s AND deleted_at IS NULL
                """,
                (build_plan_code, execution_code),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        execution = self._normalize_live_room_build_plan_execution(row)
        execution["operation_results"] = self._fetch_live_room_build_plan_operation_results(execution_code)
        return execution

    def create_jd_live_metric_session(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        build_plan_code = payload.get("build_plan_code")
        if build_plan_code and self.get_live_room_build_plan_by_code(str(build_plan_code)) is None:
            return None
        capture_session_code = self._next_jd_live_metric_session_code()
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_jd_live_metric_sessions (
                    capture_session_code, build_plan_code, frontend_execution_code,
                    live_room_id, jd_live_id, jd_shop_name, dashboard_url, status,
                    capture_interval_seconds, sync_start_mode, current_scene_name,
                    current_scene_index, metric_names, scene_schedule, config,
                    started_at, result_summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    capture_session_code,
                    build_plan_code,
                    payload.get("frontend_execution_code"),
                    payload.get("live_room_id"),
                    payload.get("jd_live_id"),
                    payload.get("jd_shop_name"),
                    payload.get("dashboard_url"),
                    payload.get("status", "planned"),
                    payload.get("capture_interval_seconds", 30),
                    payload.get("sync_start_mode", "with_frontend_agent"),
                    payload.get("current_scene_name"),
                    payload.get("current_scene_index"),
                    Jsonb(payload.get("metric_names") or []),
                    Jsonb(payload.get("scene_schedule") or []),
                    Jsonb(payload.get("config") or {}),
                    payload.get("started_at"),
                    payload.get("result_summary"),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_jd_live_metric_session(row)

    def list_jd_live_metric_sessions(
        self,
        *,
        build_plan_code: str | None = None,
        frontend_execution_code: str | None = None,
        live_room_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["deleted_at IS NULL"]
        values: list[Any] = []
        if build_plan_code is not None:
            where_clauses.append("build_plan_code = %s")
            values.append(build_plan_code)
        if frontend_execution_code is not None:
            where_clauses.append("frontend_execution_code = %s")
            values.append(frontend_execution_code)
        if live_room_id is not None:
            where_clauses.append("live_room_id = %s")
            values.append(live_room_id)
        if status is not None:
            where_clauses.append("status = %s")
            values.append(status)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_jd_live_metric_sessions
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_jd_live_metric_session(row) for row in rows]

    def get_jd_live_metric_session_by_code(self, capture_session_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_jd_live_metric_sessions
                WHERE capture_session_code = %s AND deleted_at IS NULL
                """,
                (capture_session_code,),
            )
            row = cursor.fetchone()
        return self._normalize_jd_live_metric_session(row) if row else None

    def update_jd_live_metric_session(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        writable_fields = (
            "status",
            "current_scene_name",
            "current_scene_index",
            "started_at",
            "finished_at",
            "result_summary",
            "error_message",
        )
        updates = {field: payload[field] for field in writable_fields if field in payload}
        if not updates:
            return self.get_jd_live_metric_session_by_code(capture_session_code)
        assignments = [f"{field} = %s" for field in updates]
        values = list(updates.values())
        values.append(capture_session_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE maitu_jd_live_metric_sessions
                SET {', '.join(assignments)}, updated_at = now()
                WHERE capture_session_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_jd_live_metric_session(row) if row else None

    def create_jd_live_metric_sample(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        session = self.get_jd_live_metric_session_by_code(capture_session_code)
        if session is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(sample_index), -1) + 1 AS next_sample_index
                FROM maitu_jd_live_metric_samples
                WHERE capture_session_code = %s
                """,
                (capture_session_code,),
            )
            sample_index = cursor.fetchone()["next_sample_index"]
            cursor.execute(
                """
                INSERT INTO maitu_jd_live_metric_samples (
                    capture_session_id, capture_session_code, sample_index, sampled_at,
                    scene_name, scene_index, frontend_event_code, live_elapsed_seconds,
                    online_viewers, average_stay_seconds, product_click_rate,
                    product_conversion_rate, gmv, uv_value, product_exposures,
                    product_clicks, transaction_count, transaction_amount,
                    traffic_sources, interaction_data, raw_metrics, screenshot_asset_code,
                    dom_snapshot_asset_code, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    session["id"],
                    capture_session_code,
                    sample_index,
                    payload.get("sampled_at") or datetime.now(UTC),
                    payload.get("scene_name"),
                    payload.get("scene_index"),
                    payload.get("frontend_event_code"),
                    payload.get("live_elapsed_seconds"),
                    payload.get("online_viewers"),
                    payload.get("average_stay_seconds"),
                    payload.get("product_click_rate"),
                    payload.get("product_conversion_rate"),
                    payload.get("gmv"),
                    payload.get("uv_value"),
                    payload.get("product_exposures"),
                    payload.get("product_clicks"),
                    payload.get("transaction_count"),
                    payload.get("transaction_amount"),
                    Jsonb(payload.get("traffic_sources") or {}),
                    Jsonb(payload.get("interaction_data") or {}),
                    Jsonb(payload.get("raw_metrics") or {}),
                    payload.get("screenshot_asset_code"),
                    payload.get("dom_snapshot_asset_code"),
                    payload.get("status", "captured"),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_jd_live_metric_sample(row)

    def list_jd_live_metric_samples(
        self,
        capture_session_code: str,
        *,
        scene_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if self.get_jd_live_metric_session_by_code(capture_session_code) is None:
            return None
        where_clauses = ["capture_session_code = %s"]
        values: list[Any] = [capture_session_code]
        if scene_name is not None:
            where_clauses.append("scene_name = %s")
            values.append(scene_name)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_jd_live_metric_samples
                WHERE {' AND '.join(where_clauses)}
                ORDER BY sample_index ASC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_jd_live_metric_sample(row) for row in rows]

    def create_layout_adjustment(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.layout_adjustment import LayerGeometry, plan_layout_adjustment

        adjustment_code = self._next_layout_adjustment_code()
        before_geometry = dict(payload["before_geometry"])
        plan = plan_layout_adjustment(
            user_instruction=payload["user_instruction"],
            before_geometry=LayerGeometry(**before_geometry),
            canvas_width=payload["canvas_width"],
            canvas_height=payload["canvas_height"],
            safe_margin=payload.get("safe_margin", 20),
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_layout_adjustments (
                    adjustment_code, build_plan_code, scene_name, layer_name,
                    user_instruction, status, before_geometry, target_geometry,
                    operation, checks
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    adjustment_code,
                    payload.get("build_plan_code"),
                    payload.get("scene_name"),
                    payload.get("layer_name"),
                    payload["user_instruction"],
                    plan.status,
                    Jsonb(before_geometry),
                    Jsonb(plan.operation["target_geometry"]),
                    Jsonb(plan.operation),
                    Jsonb(plan.checks),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_layout_adjustment(row)

    def get_layout_adjustment_by_code(self, adjustment_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_layout_adjustments
                WHERE adjustment_code = %s AND deleted_at IS NULL
                """,
                (adjustment_code,),
            )
            row = cursor.fetchone()
        return self._normalize_layout_adjustment(row) if row else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._filter_writable(payload)
        data["accepted_asset_types"] = self._serialize_asset_types(data.get("accepted_asset_types"))
        data["slot_code"] = self._next_slot_code()
        fields = tuple(data.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                INSERT INTO maitu_material_slots ({columns})
                VALUES ({placeholders})
                RETURNING *
                """,
                tuple(data[field] for field in fields),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_row(row)

    def list(
        self,
        *,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        required_category: str | None = None,
        slot_name: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["deleted_at IS NULL"]
        values: list[Any] = []

        if maitu_project_code is not None:
            where_clauses.append("maitu_project_code = %s")
            values.append(maitu_project_code)
        if scene_name is not None:
            where_clauses.append("scene_name = %s")
            values.append(scene_name)
        if required_category is not None:
            where_clauses.append("required_category = %s")
            values.append(required_category)
        if slot_name is not None:
            where_clauses.append("slot_name = %s")
            values.append(slot_name)
        if q:
            where_clauses.append(
                "(slot_code ILIKE %s OR slot_name ILIKE %s OR scene_name ILIKE %s OR layer_name ILIKE %s OR description ILIKE %s)"
            )
            pattern = f"%{q}%"
            values.extend([pattern, pattern, pattern, pattern, pattern])

        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_material_slots
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_row(row) for row in rows]

    def get_by_code(self, slot_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_material_slots
                WHERE slot_code = %s AND deleted_at IS NULL
                """,
                (slot_code,),
            )
            row = cursor.fetchone()
        return self._normalize_row(row) if row else None

    def update(self, slot_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        data = self._filter_writable(payload)
        if "accepted_asset_types" in data:
            data["accepted_asset_types"] = self._serialize_asset_types(data.get("accepted_asset_types"))
        if not data:
            return self.get_by_code(slot_code)

        assignments = ", ".join([f"{field} = %s" for field in data])
        values: list[Any] = list(data.values())
        values.append(slot_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._lock_slot_retry_intent_for_mutation(cursor, slot_code)
            cursor.execute(
                f"""
                UPDATE maitu_material_slots
                SET {assignments}, updated_at = now()
                WHERE slot_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_row(row) if row else None

    def soft_delete(self, slot_code: str) -> bool:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._lock_slot_retry_intent_for_mutation(cursor, slot_code)
            cursor.execute(
                """
                UPDATE maitu_material_slots
                SET deleted_at = now(), updated_at = now()
                WHERE slot_code = %s AND deleted_at IS NULL
                RETURNING id
                """,
                (slot_code,),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return row is not None

    def list_candidate_assets(
        self,
        slot_code: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        slot = self.get_by_code(slot_code)
        if slot is None:
            return None

        accepted_asset_types = slot.get("accepted_asset_types", [])
        where_clauses = ["deleted_at IS NULL", "maitu_category = %s"]
        values: list[Any] = [slot["required_category"]]
        if accepted_asset_types:
            placeholders = ", ".join(["%s"] * len(accepted_asset_types))
            where_clauses.append(f"asset_type IN ({placeholders})")
            values.extend(accepted_asset_types)

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT asset_code, asset_type, title, original_filename, maitu_category,
                    maitu_project_code, maitu_scene_name, maitu_layer_name,
                    maitu_slot_name, maitu_slot_code, layer_width, layer_height,
                    replacement_policy, created_at
                FROM assets
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                """,
                tuple(values),
            )
            rows = cursor.fetchall()

        candidates = [self._normalize_candidate_asset(row, slot) for row in rows]
        candidates.sort(key=lambda row: (row["match_score"], row["asset_code"]), reverse=True)
        return {
            "slot_code": slot["slot_code"],
            "required_category": slot["required_category"],
            "accepted_asset_types": accepted_asset_types,
            "assets": candidates[offset : offset + limit],
        }

    def create_replacement_plan(
        self,
        payload: dict[str, Any],
        slot_candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] | None = None,
    ) -> dict[str, Any]:
        plan_code = self._next_plan_code()
        plan_data = {
            "plan_code": plan_code,
            "plan_name": payload["plan_name"],
            "maitu_project_code": payload.get("maitu_project_code"),
            "scene_name": payload.get("scene_name"),
            "status": "draft",
            "strategy": payload.get("strategy", "best_match"),
            "description": payload.get("description"),
        }
        if slot_candidates is None:
            slots = self._resolve_plan_slots(payload)
            slot_candidates = []
            for slot in slots:
                candidate_response = self.list_candidate_assets(slot["slot_code"], limit=1)
                candidate = candidate_response["assets"][0] if candidate_response and candidate_response["assets"] else None
                slot_candidates.append((slot, candidate))

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_replacement_plans (
                    plan_code, plan_name, maitu_project_code, scene_name,
                    status, strategy, description
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    plan_data["plan_code"],
                    plan_data["plan_name"],
                    plan_data["maitu_project_code"],
                    plan_data["scene_name"],
                    plan_data["status"],
                    plan_data["strategy"],
                    plan_data["description"],
                ),
            )
            plan = cursor.fetchone()

            for sort_order, (slot, candidate) in enumerate(slot_candidates):
                cursor.execute(
                    """
                    INSERT INTO maitu_replacement_plan_items (
                        plan_id, plan_code, slot_code, slot_name, required_category,
                        selected_asset_code, selected_asset_title, match_score,
                        match_reasons, replacement_policy, sort_order, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        plan["id"],
                        plan_code,
                        slot["slot_code"],
                        slot.get("slot_name"),
                        slot.get("required_category"),
                        candidate.get("asset_code") if candidate else None,
                        candidate.get("title") if candidate else None,
                        candidate.get("match_score") if candidate else None,
                        Jsonb(candidate.get("match_reasons", [])) if candidate else Jsonb([]),
                        candidate.get("replacement_policy") if candidate else slot.get("replacement_policy"),
                        sort_order,
                        "selected" if candidate else "missing",
                    ),
                )
        self.connection.commit()
        return self.get_replacement_plan_by_code(plan_code) or self._normalize_plan(plan)

    def list_replacement_plans(
        self,
        *,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["deleted_at IS NULL"]
        values: list[Any] = []
        if maitu_project_code is not None:
            where_clauses.append("maitu_project_code = %s")
            values.append(maitu_project_code)
        if scene_name is not None:
            where_clauses.append("scene_name = %s")
            values.append(scene_name)
        if status is not None:
            where_clauses.append("status = %s")
            values.append(status)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_replacement_plans
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_plan(row) for row in rows]

    def get_replacement_plan_by_code(self, plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_replacement_plans
                WHERE plan_code = %s AND deleted_at IS NULL
                """,
                (plan_code,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        plan = self._normalize_plan(row)
        plan["items"] = self._fetch_plan_items(plan_code)
        return plan

    def get_browser_use_operation_plan(self, plan_code: str) -> dict[str, Any] | None:
        plan = self.get_replacement_plan_by_code(plan_code)
        if plan is None:
            return None

        operations = []
        for item in plan.get("items", []):
            slot = self.get_by_code(item["slot_code"])
            scene_name = slot.get("scene_name") if slot else plan.get("scene_name")
            layer_name = slot.get("layer_name") if slot else None
            slot_name = item.get("slot_name") or (slot.get("slot_name") if slot else None)
            if item.get("selected_asset_code"):
                policy = item.get("replacement_policy") or (slot.get("replacement_policy") if slot else "keep_layout")
                asset = self._fetch_asset_operation_metadata(item["selected_asset_code"]) or {}
                asset_title = asset.get("title") or item.get("selected_asset_title") or "未命名素材"
                asset_display_code = asset.get("display_code") or asset.get("local_file_code") or item["selected_asset_code"]
                asset_filename = asset.get("original_filename")
                asset_hint = asset.get("browser_use_hint")
                instruction = (
                    f"进入麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
                    f"找到目标图层/槽位 {layer_name or slot_name or item['slot_code']}，"
                    f"将素材替换为 {asset_display_code}（{asset_title}；AssetGraph编号 {item['selected_asset_code']}），"
                    f"替换策略为 {policy}；保持原图层位置和尺寸不变"
                )
                if asset_filename:
                    instruction += f"；素材文件名：{asset_filename}"
                if asset_hint:
                    instruction += f"；选择提示：{asset_hint}"
                instruction += "，替换后保存项目。"
                operations.append(
                    {
                        "operation_type": "replace_layer_asset",
                        "slot_code": item["slot_code"],
                        "slot_name": slot_name,
                        "scene_name": scene_name,
                        "layer_name": layer_name,
                        "asset_code": item.get("selected_asset_code"),
                        "asset_title": asset_title,
                        "asset_display_code": asset.get("display_code"),
                        "asset_local_file_code": asset.get("local_file_code"),
                        "asset_original_filename": asset.get("original_filename"),
                        "asset_local_relative_path": asset.get("local_relative_path"),
                        "asset_browser_use_hint": asset.get("browser_use_hint"),
                        "replacement_policy": policy,
                        "status": "ready",
                        "instruction": instruction,
                    }
                )
            else:
                instruction = (
                    f"槽位 {item['slot_code']}（{slot_name or '未命名槽位'}）暂无可替换素材；"
                    f"请先在 AssetGraph 中补充 {item.get('required_category') or '匹配分类'} 类型素材，或人工选择素材后再执行。"
                )
                operations.append(
                    {
                        "operation_type": "resolve_missing_slot_asset",
                        "slot_code": item["slot_code"],
                        "slot_name": slot_name,
                        "scene_name": scene_name,
                        "layer_name": layer_name,
                        "asset_code": None,
                        "asset_title": None,
                        "replacement_policy": item.get("replacement_policy"),
                        "status": "missing_asset",
                        "instruction": instruction,
                    }
                )

        return {
            "plan_code": plan["plan_code"],
            "executor": "browser_use",
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": plan.get("scene_name"),
            "operations": operations,
        }

    def create_execution_result(self, plan_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.get_replacement_plan_by_code(plan_code)
        if plan is None:
            return None

        execution_code = self._next_execution_code()
        operation_results = payload.get("operation_results", [])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_replacement_plan_executions (
                    execution_code, plan_code, executor, execution_status, started_at,
                    finished_at, failure_type, retryable, retry_instruction,
                    error_message, screenshot_asset_code, result_summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    execution_code,
                    plan_code,
                    payload.get("executor", "browser_use"),
                    payload["execution_status"],
                    payload.get("started_at"),
                    payload.get("finished_at"),
                    payload.get("failure_type"),
                    payload.get("retryable", False),
                    payload.get("retry_instruction"),
                    payload.get("error_message"),
                    payload.get("screenshot_asset_code"),
                    payload.get("result_summary"),
                ),
            )
            execution = cursor.fetchone()

            for sort_order, operation in enumerate(operation_results):
                cursor.execute(
                    """
                    INSERT INTO maitu_replacement_plan_operation_results (
                        execution_id, execution_code, plan_code, slot_code, operation_type,
                        asset_code, status, failure_type, retryable, retry_instruction,
                        error_message, screenshot_asset_code, details, sort_order
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        execution["id"],
                        execution_code,
                        plan_code,
                        operation["slot_code"],
                        operation.get("operation_type", "replace_layer_asset"),
                        operation.get("asset_code"),
                        operation["status"],
                        operation.get("failure_type"),
                        operation.get("retryable", False),
                        operation.get("retry_instruction"),
                        operation.get("error_message"),
                        operation.get("screenshot_asset_code"),
                        Jsonb(operation.get("details", {})),
                        sort_order,
                    ),
                )

            self._create_retry_tasks_for_execution(cursor, execution_code, plan_code, payload)

            cursor.execute(
                """
                UPDATE maitu_replacement_plans
                SET status = %s, updated_at = now()
                WHERE plan_code = %s AND deleted_at IS NULL
                """,
                (self._plan_status_from_execution(payload["execution_status"]), plan_code),
            )
        self.connection.commit()
        return self.get_execution_result_by_code(plan_code, execution_code)

    def list_execution_results(
        self,
        plan_code: str,
        *,
        executor: str | None = None,
        execution_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if self.get_replacement_plan_by_code(plan_code) is None:
            return None

        where_clauses = ["plan_code = %s", "deleted_at IS NULL"]
        values: list[Any] = [plan_code]
        if executor is not None:
            where_clauses.append("executor = %s")
            values.append(executor)
        if execution_status is not None:
            where_clauses.append("execution_status = %s")
            values.append(execution_status)
        values.extend([limit, offset])

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_replacement_plan_executions
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_execution(row) for row in rows]

    def get_execution_result_by_code(self, plan_code: str, execution_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_replacement_plan_executions
                WHERE plan_code = %s AND execution_code = %s AND deleted_at IS NULL
                """,
                (plan_code, execution_code),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        execution = self._normalize_execution(row)
        execution["operation_results"] = self._fetch_operation_results(execution_code)
        return execution

    def list_retry_tasks(
        self,
        *,
        plan_code: str | None = None,
        execution_code: str | None = None,
        status: str | None = None,
        failure_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["deleted_at IS NULL"]
        values: list[Any] = []
        if plan_code is not None:
            where_clauses.append("plan_code = %s")
            values.append(plan_code)
        if execution_code is not None:
            where_clauses.append("execution_code = %s")
            values.append(execution_code)
        if status is not None:
            where_clauses.append("status = %s")
            values.append(status)
        if failure_type is not None:
            where_clauses.append("failure_type = %s")
            values.append(failure_type)
        values.extend([limit, offset])

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_execution_retry_tasks
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_retry_task(row) for row in rows]

    def list_retry_queue(
        self,
        *,
        status: str | None = "pending",
        failure_type: str | None = None,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        max_attempts: int = 3,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = [
            "rt.deleted_at IS NULL",
            "rt.retryable = true",
            "rt.retry_attempt_count < %s",
        ]
        values: list[Any] = [max_attempts]
        if status is not None:
            where_clauses.append("rt.status = %s")
            values.append(status)
        if failure_type is not None:
            where_clauses.append("rt.failure_type = %s")
            values.append(failure_type)
        if maitu_project_code is not None:
            where_clauses.append("COALESCE(ms.maitu_project_code, rp.maitu_project_code) = %s")
            values.append(maitu_project_code)
        if scene_name is not None:
            where_clauses.append("COALESCE(ms.scene_name, rp.scene_name) = %s")
            values.append(scene_name)
        values.extend([limit, offset])

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT rt.*, COALESCE(ms.maitu_project_code, rp.maitu_project_code) AS maitu_project_code,
                    COALESCE(ms.scene_name, rp.scene_name) AS scene_name,
                    ms.slot_name, ms.layer_name
                FROM maitu_execution_retry_tasks rt
                LEFT JOIN maitu_replacement_plans rp ON rp.plan_code = rt.plan_code AND rp.deleted_at IS NULL
                LEFT JOIN maitu_material_slots ms ON ms.slot_code = rt.slot_code AND ms.deleted_at IS NULL
                WHERE {' AND '.join(where_clauses)}
                ORDER BY rt.retry_attempt_count ASC, rt.created_at ASC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._normalize_retry_queue_item(row) for row in rows]

    def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        where_clauses = [
            "rt.deleted_at IS NULL",
            "rt.retryable = true",
            "rt.status = 'pending'",
            "rt.retry_attempt_count < %s",
        ]
        values: list[Any] = [payload.get("max_attempts", 3)]
        if payload.get("failure_type") is not None:
            where_clauses.append("rt.failure_type = %s")
            values.append(payload["failure_type"])
        if payload.get("maitu_project_code") is not None:
            where_clauses.append("COALESCE(ms.maitu_project_code, rp.maitu_project_code) = %s")
            values.append(payload["maitu_project_code"])
        if payload.get("scene_name") is not None:
            where_clauses.append("COALESCE(ms.scene_name, rp.scene_name) = %s")
            values.append(payload["scene_name"])
        values.extend([payload["claimed_by"], payload.get("lock_ttl_seconds", 900)])

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                WITH candidate AS (
                    SELECT rt.retry_task_code,
                           COALESCE(ms.maitu_project_code, rp.maitu_project_code) AS maitu_project_code,
                           COALESCE(ms.scene_name, rp.scene_name) AS scene_name,
                           ms.slot_name,
                           ms.layer_name
                    FROM maitu_execution_retry_tasks rt
                    LEFT JOIN maitu_replacement_plans rp ON rp.plan_code = rt.plan_code AND rp.deleted_at IS NULL
                    LEFT JOIN maitu_material_slots ms ON ms.slot_code = rt.slot_code AND ms.deleted_at IS NULL
                    WHERE {' AND '.join(where_clauses)}
                    ORDER BY rt.retry_attempt_count ASC, rt.created_at ASC
                    LIMIT 1
                    FOR UPDATE OF rt SKIP LOCKED
                )
                UPDATE maitu_execution_retry_tasks rt
                SET status = 'in_progress', claimed_by = %s, claimed_at = now(),
                    claim_expires_at = now() + (%s * interval '1 second'),
                    claim_token = gen_random_uuid(), lease_version = lease_version + 1,
                    updated_at = now()
                FROM candidate
                WHERE rt.retry_task_code = candidate.retry_task_code
                RETURNING rt.*, candidate.maitu_project_code, candidate.scene_name,
                          candidate.slot_name, candidate.layer_name
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            return None
        return self._normalize_retry_queue_item(row)

    def reclaim_expired_retry_tasks(self) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH reclaimed AS (
                    UPDATE maitu_execution_retry_tasks
                    SET status = 'pending', claimed_by = NULL, claimed_at = NULL,
                        claim_expires_at = NULL, claim_token = NULL, updated_at = now()
                    WHERE deleted_at IS NULL
                        AND status = 'in_progress'
                        AND claim_expires_at IS NOT NULL
                        AND claim_expires_at < now()
                    RETURNING retry_task_code
                ), marked_checkpoints AS (
                    UPDATE maitu_retry_operation_checkpoints checkpoint
                    SET state = 'reconcile_required', updated_at = now()
                    WHERE checkpoint.state = 'begun'
                        AND checkpoint.retry_task_code IN (SELECT retry_task_code FROM reclaimed)
                    RETURNING checkpoint.retry_task_code
                )
                SELECT retry_task_code FROM reclaimed
                """
            )
            rows = cursor.fetchall()
        self.connection.commit()
        codes = [row["retry_task_code"] for row in rows]
        return {"reclaimed_count": len(codes), "retry_task_codes": codes}

    def get_retry_worker_next(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        reclaim_result = self.reclaim_expired_retry_tasks()
        retry_task = self.claim_next_retry_task(payload)
        if retry_task is None:
            return None
        operation_plan = self.get_retry_task_browser_use_operation_plan(retry_task["retry_task_code"])
        if operation_plan is None:
            return None
        return {
            "reclaimed_count": reclaim_result["reclaimed_count"],
            "reclaimed_retry_task_codes": reclaim_result["retry_task_codes"],
            "retry_task": retry_task,
            "operation_plan": operation_plan,
        }

    def heartbeat_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_execution_retry_tasks
                SET claim_expires_at = now() + (%s * interval '1 second'), updated_at = now()
                WHERE retry_task_code = %s
                    AND deleted_at IS NULL
                    AND status = 'in_progress'
                    AND claimed_by = %s
                    AND claim_token = %s
                    AND lease_version = %s
                    AND claim_expires_at IS NOT NULL
                    AND claim_expires_at >= now()
                RETURNING *
                """,
                (
                    payload.get("lock_ttl_seconds", 900),
                    retry_task_code,
                    payload["claimed_by"],
                    payload["claim_token"],
                    payload["lease_version"],
                ),
            )
            row = cursor.fetchone()
            task_exists = False
            if row is None:
                cursor.execute(
                    "SELECT 1 FROM maitu_execution_retry_tasks WHERE retry_task_code = %s AND deleted_at IS NULL",
                    (retry_task_code,),
                )
                task_exists = cursor.fetchone() is not None
        self.connection.commit()
        if row is not None:
            return self._normalize_retry_task(row)
        if task_exists:
            raise RetryLeaseConflictError("lease is expired or owned by another claim")
        return None

    def release_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        assignments = [
            "status = %s",
            "claimed_by = NULL",
            "claimed_at = NULL",
            "claim_expires_at = NULL",
            "claim_token = NULL",
        ]
        values: list[Any] = [payload.get("status", "pending")]
        if "result_summary" in payload:
            assignments.append("result_summary = %s")
            values.append(payload["result_summary"])
        values.extend(
            [
                retry_task_code,
                payload["claimed_by"],
                payload["claim_token"],
                payload["lease_version"],
            ]
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE maitu_execution_retry_tasks
                SET {', '.join(assignments)}, updated_at = now()
                WHERE retry_task_code = %s
                    AND deleted_at IS NULL
                    AND status = 'in_progress'
                    AND claimed_by = %s
                    AND claim_token = %s
                    AND lease_version = %s
                    AND claim_expires_at IS NOT NULL
                    AND claim_expires_at >= now()
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
            task_exists = False
            if row is not None:
                cursor.execute(
                    """
                    UPDATE maitu_retry_operation_checkpoints
                    SET state = 'reconcile_required', updated_at = now()
                    WHERE retry_task_code = %s
                        AND state = 'begun'
                        AND begun_by = %s
                        AND begun_lease_version = %s
                    """,
                    (retry_task_code, payload["claimed_by"], payload["lease_version"]),
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM maitu_execution_retry_tasks WHERE retry_task_code = %s AND deleted_at IS NULL",
                    (retry_task_code,),
                )
                task_exists = cursor.fetchone() is not None
        self.connection.commit()
        if row is not None:
            return self._normalize_retry_task(row)
        if task_exists:
            raise RetryLeaseConflictError("lease is expired or owned by another claim")
        return None

    def _get_retry_queue_item_by_code(self, retry_task_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT rt.*, COALESCE(ms.maitu_project_code, rp.maitu_project_code) AS maitu_project_code,
                    COALESCE(ms.scene_name, rp.scene_name) AS scene_name,
                    ms.slot_name, ms.layer_name
                FROM maitu_execution_retry_tasks rt
                LEFT JOIN maitu_replacement_plans rp ON rp.plan_code = rt.plan_code AND rp.deleted_at IS NULL
                LEFT JOIN maitu_material_slots ms ON ms.slot_code = rt.slot_code AND ms.deleted_at IS NULL
                WHERE rt.retry_task_code = %s AND rt.deleted_at IS NULL
                """,
                (retry_task_code,),
            )
            row = cursor.fetchone()
        return self._normalize_retry_queue_item(row) if row else None

    def get_retry_task_by_code(self, retry_task_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_execution_retry_tasks
                WHERE retry_task_code = %s AND deleted_at IS NULL
                """,
                (retry_task_code,),
            )
            row = cursor.fetchone()
        return self._normalize_retry_task(row) if row else None

    def update_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        writable_fields = ("result_summary", "retry_instruction")
        data = {field: payload[field] for field in writable_fields if field in payload}
        if not data:
            return self.get_retry_task_by_code(retry_task_code)

        assignments = ", ".join([f"{field} = %s" for field in data])
        values: list[Any] = list(data.values())
        values.append(retry_task_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE maitu_execution_retry_tasks
                SET {assignments}, updated_at = now()
                WHERE retry_task_code = %s
                    AND deleted_at IS NULL
                    AND status <> 'in_progress'
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
            task_exists = False
            if row is None:
                cursor.execute(
                    "SELECT 1 FROM maitu_execution_retry_tasks WHERE retry_task_code = %s AND deleted_at IS NULL",
                    (retry_task_code,),
                )
                task_exists = cursor.fetchone() is not None
        self.connection.commit()
        if row is not None:
            return self._normalize_retry_task(row)
        if task_exists:
            raise RetryLeaseConflictError("retry task metadata cannot change while a worker lease is active")
        return None

    def get_retry_task_browser_use_operation_plan(self, retry_task_code: str) -> dict[str, Any] | None:
        task = self.get_retry_task_by_code(retry_task_code)
        if task is None:
            return None

        plan = self.get_replacement_plan_by_code(task["plan_code"]) or {}
        slot = self.get_by_code(task["slot_code"]) if task.get("slot_code") else None
        plan_items = plan.get("items", [])
        plan_item = next((item for item in plan_items if item.get("slot_code") == task.get("slot_code")), {})
        operations = self._build_retry_operations(task, plan, slot or {}, plan_item)
        return {
            "retry_task_code": retry_task_code,
            "plan_code": task["plan_code"],
            "execution_code": task["execution_code"],
            "executor": task.get("executor", "browser_use"),
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": (slot or {}).get("scene_name") or plan.get("scene_name"),
            "operations": operations,
        }

    def list_retry_operation_checkpoints(self, retry_task_code: str) -> list[dict[str, Any]] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT retry_task_code
                FROM maitu_execution_retry_tasks
                WHERE retry_task_code = %s AND deleted_at IS NULL
                """,
                (retry_task_code,),
            )
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                """
                SELECT *
                FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s
                ORDER BY operation_key
                """,
                (retry_task_code,),
            )
            checkpoints = cursor.fetchall()
        return [self._normalize_retry_checkpoint(checkpoint, None) for checkpoint in checkpoints]

    def begin_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if UUID(str(payload["attempt_id"])) == UUID(str(payload["claim_token"])):
            raise RetryCheckpointConflictError("checkpoint attempt_id must not equal the active claim token")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            task = self._lock_retry_task_for_checkpoint(cursor, retry_task_code)
            if task is None:
                self.connection.commit()
                return None
            self._assert_current_retry_lease(task, payload)
            operation = self._find_authoritative_retry_operation(cursor, task, operation_key)
            if operation["operation_fingerprint"] != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise RetryCheckpointConflictError("operation fingerprint differs from authoritative intent")

            cursor.execute(
                """
                SELECT *
                FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s AND operation_key = %s
                FOR UPDATE
                """,
                (retry_task_code, operation_key),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None:
                cursor.execute(
                    """
                    INSERT INTO maitu_retry_operation_checkpoints (
                        retry_task_code, operation_key, operation_fingerprint, state,
                        attempt_id, begun_by, begun_lease_version
                    )
                    VALUES (%s, %s, %s, 'begun', %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        retry_task_code,
                        operation_key,
                        operation["operation_fingerprint"],
                        payload["attempt_id"],
                        payload["claimed_by"],
                        payload["lease_version"],
                    ),
                )
                checkpoint = cursor.fetchone()
                decision = "execute"
            else:
                if checkpoint["operation_fingerprint"] != operation["operation_fingerprint"]:
                    self.connection.rollback()
                    raise RetryCheckpointConflictError("stored checkpoint fingerprint differs from authoritative intent")
                if checkpoint["state"] == "retry_authorized":
                    cursor.execute(
                        """
                        UPDATE maitu_retry_operation_checkpoints
                        SET state = 'begun', attempt_id = %s, begun_by = %s,
                            begun_lease_version = %s, begun_at = now(), updated_at = now()
                        WHERE retry_task_code = %s AND operation_key = %s
                            AND state = 'retry_authorized'
                        RETURNING *
                        """,
                        (
                            payload["attempt_id"],
                            payload["claimed_by"],
                            payload["lease_version"],
                            retry_task_code,
                            operation_key,
                        ),
                    )
                    checkpoint = cursor.fetchone()
                    if checkpoint is None:
                        self.connection.rollback()
                        raise RetryCheckpointConflictError("retry authorization was consumed concurrently")
                    decision = "execute"
                elif checkpoint["state"] == "completed":
                    self._assert_verified_secret_free_evidence(
                        checkpoint.get("completion_evidence") or {},
                        payload["claim_token"],
                    )
                    decision = "skip"
                elif (
                    checkpoint["state"] == "begun"
                    and str(checkpoint["attempt_id"]) == str(payload["attempt_id"])
                    and checkpoint["begun_by"] == payload["claimed_by"]
                    and checkpoint["begun_lease_version"] == payload["lease_version"]
                ):
                    decision = "execute"
                else:
                    decision = "reconcile"

        self.connection.commit()
        return self._normalize_retry_checkpoint(checkpoint, decision)

    def complete_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if UUID(str(payload["attempt_id"])) == UUID(str(payload["claim_token"])):
            raise RetryCheckpointConflictError("checkpoint attempt_id must not equal the active claim token")
        if UUID(str(payload["completion_id"])) == UUID(str(payload["claim_token"])):
            raise RetryCheckpointConflictError("checkpoint completion_id must not equal the active claim token")
        self._assert_verified_secret_free_evidence(payload.get("evidence", {}), payload["claim_token"])
        if payload.get("result_summary") and str(payload["claim_token"]).lower() in payload["result_summary"].lower():
            raise RetryCheckpointConflictError("checkpoint summary must not contain the active claim token")
        completion_fingerprint = self._completion_payload_fingerprint(payload)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            task = self._lock_retry_task_for_checkpoint(cursor, retry_task_code)
            if task is None:
                self.connection.commit()
                return None
            self._assert_current_retry_lease(task, payload)
            operation = self._find_authoritative_retry_operation(cursor, task, operation_key)
            if operation["operation_fingerprint"] != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise RetryCheckpointConflictError("operation fingerprint differs from authoritative intent")

            cursor.execute(
                """
                SELECT *
                FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s AND operation_key = %s
                FOR UPDATE
                """,
                (retry_task_code, operation_key),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None:
                self.connection.rollback()
                raise RetryCheckpointConflictError("operation checkpoint was not begun")
            if checkpoint["operation_fingerprint"] != operation["operation_fingerprint"]:
                self.connection.rollback()
                raise RetryCheckpointConflictError("stored checkpoint fingerprint differs from authoritative intent")

            if checkpoint["state"] == "completed":
                self._assert_verified_secret_free_evidence(
                    checkpoint.get("completion_evidence") or {},
                    payload["claim_token"],
                )
                if (
                    str(checkpoint["completion_id"]) == str(payload["completion_id"])
                    and checkpoint["completion_fingerprint"] == completion_fingerprint
                    and str(checkpoint["attempt_id"]) == str(payload["attempt_id"])
                ):
                    self.connection.commit()
                    return self._normalize_retry_checkpoint(checkpoint, "skip")
                self.connection.rollback()
                raise RetryCheckpointConflictError("completion_id or completion payload conflicts with completed checkpoint")

            if (
                checkpoint["state"] != "begun"
                or str(checkpoint["attempt_id"]) != str(payload["attempt_id"])
                or checkpoint["begun_by"] != payload["claimed_by"]
                or checkpoint["begun_lease_version"] != payload["lease_version"]
            ):
                self.connection.rollback()
                raise RetryCheckpointConflictError("checkpoint requires reconciliation or belongs to another attempt")

            cursor.execute(
                """
                UPDATE maitu_retry_operation_checkpoints
                SET state = 'completed', completion_id = %s, completion_fingerprint = %s,
                    completion_summary = %s, completed_by = %s, completed_lease_version = %s,
                    completion_evidence = %s, completion_source = 'worker',
                    completion_reconciliation_id = NULL, completed_at = now(), updated_at = now()
                WHERE retry_task_code = %s AND operation_key = %s
                    AND state = 'begun' AND attempt_id = %s
                    AND begun_by = %s AND begun_lease_version = %s
                RETURNING *
                """,
                (
                    payload["completion_id"],
                    completion_fingerprint,
                    payload.get("result_summary"),
                    payload["claimed_by"],
                    payload["lease_version"],
                    Jsonb(payload.get("evidence", {})),
                    retry_task_code,
                    operation_key,
                    payload["attempt_id"],
                    payload["claimed_by"],
                    payload["lease_version"],
                ),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None:
                self.connection.rollback()
                raise RetryCheckpointConflictError("checkpoint changed while completion was recorded")

        self.connection.commit()
        return self._normalize_retry_checkpoint(checkpoint, "skip")

    def reconcile_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        self._assert_reconciliation_evidence(payload)
        result_fingerprint = self._reconciliation_payload_fingerprint(payload)
        reconciliation_id = payload["reconciliation_id"]

        with self.connection.cursor(row_factory=dict_row) as cursor:
            task = self._lock_retry_task_for_checkpoint(cursor, retry_task_code)
            if task is None:
                self.connection.commit()
                return None

            cursor.execute(
                """
                SELECT *
                FROM maitu_retry_operation_reconciliations
                WHERE reconciliation_id = %s
                """,
                (reconciliation_id,),
            )
            receipt = cursor.fetchone()
            if receipt is not None:
                stored_result_fingerprint = self._reconciliation_receipt_fingerprint(receipt)
                if (
                    receipt["retry_task_code"] == retry_task_code
                    and receipt["operation_key"] == operation_key
                    and stored_result_fingerprint is not None
                    and receipt["result_fingerprint"] == stored_result_fingerprint
                    and receipt["result_fingerprint"] == result_fingerprint
                ):
                    self.connection.commit()
                    return self._normalize_retry_reconciliation(receipt)
                self.connection.rollback()
                raise RetryCheckpointConflictError("reconciliation_id was reused with different content")

            if task.get("status") == "in_progress":
                self.connection.rollback()
                raise RetryLeaseConflictError("operation reconciliation is forbidden while a worker lease is active")
            if task.get("status") not in {"pending", "manual_required", "failed"}:
                self.connection.rollback()
                raise RetryCheckpointConflictError("retry task is not awaiting operation reconciliation")

            operation = self._find_authoritative_retry_operation(cursor, task, operation_key)
            if operation["operation_fingerprint"] != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise RetryCheckpointConflictError("operation fingerprint differs from authoritative intent")

            cursor.execute(
                """
                SELECT *
                FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s AND operation_key = %s
                FOR UPDATE
                """,
                (retry_task_code, operation_key),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None or checkpoint.get("state") != "reconcile_required":
                self.connection.rollback()
                raise RetryCheckpointConflictError("operation checkpoint is not awaiting reconciliation")
            if checkpoint["operation_fingerprint"] != operation["operation_fingerprint"]:
                self.connection.rollback()
                raise RetryCheckpointConflictError("stored checkpoint fingerprint differs from authoritative intent")
            if UUID(str(checkpoint["attempt_id"])) != UUID(str(payload["expected_attempt_id"])):
                self.connection.rollback()
                raise RetryCheckpointConflictError("reconciliation targets a stale operation attempt")

            resulting_state = (
                "completed" if payload["resolution"] == "confirmed_completed" else "retry_authorized"
            )
            cursor.execute(
                """
                INSERT INTO maitu_retry_operation_reconciliations (
                    reconciliation_id, retry_task_code, operation_key, reconciled_attempt_id,
                    operation_fingerprint, resolution, resulting_state, resolved_by,
                    resolution_summary, evidence, result_fingerprint
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING *
                """,
                (
                    reconciliation_id,
                    retry_task_code,
                    operation_key,
                    payload["expected_attempt_id"],
                    operation["operation_fingerprint"],
                    payload["resolution"],
                    resulting_state,
                    payload["resolved_by"],
                    payload["resolution_summary"],
                    Jsonb(payload["evidence"]),
                    result_fingerprint,
                ),
            )
            receipt = cursor.fetchone()
            if receipt is None:
                cursor.execute(
                    "SELECT * FROM maitu_retry_operation_reconciliations WHERE reconciliation_id = %s",
                    (reconciliation_id,),
                )
                receipt = cursor.fetchone()
                stored_result_fingerprint = self._reconciliation_receipt_fingerprint(receipt or {})
                if receipt is not None and (
                    receipt["retry_task_code"] == retry_task_code
                    and receipt["operation_key"] == operation_key
                    and stored_result_fingerprint is not None
                    and receipt["result_fingerprint"] == stored_result_fingerprint
                    and receipt["result_fingerprint"] == result_fingerprint
                ):
                    self.connection.commit()
                    return self._normalize_retry_reconciliation(receipt)
                self.connection.rollback()
                raise RetryCheckpointConflictError("reconciliation_id was reused with different content")

            if payload["resolution"] == "confirmed_completed":
                cursor.execute(
                    """
                    UPDATE maitu_retry_operation_checkpoints
                    SET state = 'completed', completion_id = %s, completion_fingerprint = %s,
                        completion_summary = %s, completed_by = %s, completed_lease_version = NULL,
                        completion_evidence = %s, completion_source = 'reconciliation',
                        completion_reconciliation_id = %s, completed_at = now(), updated_at = now()
                    WHERE retry_task_code = %s AND operation_key = %s
                        AND state = 'reconcile_required' AND attempt_id = %s
                        AND operation_fingerprint = %s
                    RETURNING retry_task_code
                    """,
                    (
                        reconciliation_id,
                        result_fingerprint,
                        payload["resolution_summary"],
                        payload["resolved_by"],
                        Jsonb(payload["evidence"]),
                        reconciliation_id,
                        retry_task_code,
                        operation_key,
                        payload["expected_attempt_id"],
                        operation["operation_fingerprint"],
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE maitu_retry_operation_checkpoints
                    SET state = 'retry_authorized', completion_id = NULL, completion_fingerprint = NULL,
                        completion_summary = NULL, completed_by = NULL, completed_lease_version = NULL,
                        completion_evidence = '{}'::jsonb, completion_source = NULL,
                        completion_reconciliation_id = NULL, completed_at = NULL, updated_at = now()
                    WHERE retry_task_code = %s AND operation_key = %s
                        AND state = 'reconcile_required' AND attempt_id = %s
                        AND operation_fingerprint = %s
                    RETURNING retry_task_code
                    """,
                    (
                        retry_task_code,
                        operation_key,
                        payload["expected_attempt_id"],
                        operation["operation_fingerprint"],
                    ),
                )

            if cursor.fetchone() is None:
                self.connection.rollback()
                raise RetryCheckpointConflictError("checkpoint changed while reconciliation was recorded")

            cursor.execute(
                """
                UPDATE maitu_execution_retry_tasks
                SET status = 'pending', updated_at = now()
                WHERE retry_task_code = %s AND deleted_at IS NULL
                    AND status IN ('pending', 'manual_required', 'failed')
                RETURNING retry_task_code
                """,
                (retry_task_code,),
            )
            if cursor.fetchone() is None:
                self.connection.rollback()
                raise RetryCheckpointConflictError("retry task changed while reconciliation was recorded")

        self.connection.commit()
        return self._normalize_retry_reconciliation(receipt)

    def create_retry_task_execution_result(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._assert_retry_execution_payload_token_free(payload)
        serializable_payload = json.loads(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True))
        receipt_payload = {key: value for key, value in serializable_payload.items() if key != "claim_token"}
        fingerprint = hashlib.sha256(
            json.dumps(serializable_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        retry_execution_id = payload["retry_execution_id"]

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT rt.*, rt.claim_expires_at >= now() AS lease_active
                FROM maitu_execution_retry_tasks rt
                WHERE rt.retry_task_code = %s AND rt.deleted_at IS NULL
                FOR UPDATE
                """,
                (retry_task_code,),
            )
            task = cursor.fetchone()
            if task is None:
                self.connection.commit()
                return None

            cursor.execute(
                """
                SELECT retry_task_code, result_fingerprint
                FROM maitu_retry_execution_receipts
                WHERE retry_execution_id = %s
                """,
                (retry_execution_id,),
            )
            receipt = cursor.fetchone()
            if receipt is not None:
                if receipt["retry_task_code"] == retry_task_code and receipt["result_fingerprint"] == fingerprint:
                    self.connection.commit()
                    task.pop("lease_active", None)
                    return self._normalize_retry_task(task)
                self.connection.rollback()
                raise RetryExecutionConflictError("retry_execution_id was reused with different content")

            lease_matches = (
                task.get("status") == "in_progress"
                and task.get("lease_active") is True
                and task.get("claimed_by") == payload["claimed_by"]
                and str(task.get("claim_token")) == str(payload["claim_token"])
                and task.get("lease_version") == payload["lease_version"]
            )
            if not lease_matches:
                self.connection.rollback()
                raise RetryLeaseConflictError("lease is expired or owned by another claim")

            if payload["retry_execution_status"] == "succeeded":
                cursor.execute(
                    """
                    SELECT operation_key, operation_fingerprint, state, attempt_id,
                           completion_id, completion_fingerprint, completion_summary,
                           completed_by, completion_evidence,
                           completed_lease_version, completion_source, completion_reconciliation_id
                    FROM maitu_retry_operation_checkpoints
                    WHERE retry_task_code = %s
                    FOR UPDATE
                    """,
                    (retry_task_code,),
                )
                checkpoints = cursor.fetchall()
                required_keys = (
                    {"save_project"}
                    if self._retry_operation_type_for_failure(task.get("failure_type")) == "retry_save_project"
                    else {"primary", "save_project"}
                )
                completed_by_key = {
                    checkpoint["operation_key"]: checkpoint
                    for checkpoint in checkpoints
                    if checkpoint.get("state") == "completed"
                }
                if set(completed_by_key) != required_keys:
                    self.connection.rollback()
                    raise RetryCheckpointConflictError(
                        "all authoritative retry operation checkpoints must be completed before success"
                    )
                for operation_key in sorted(required_keys):
                    completed_checkpoint = completed_by_key[operation_key]
                    self._assert_verified_secret_free_evidence(
                        completed_checkpoint.get("completion_evidence") or {},
                        payload["claim_token"],
                    )
                    completion_source = completed_checkpoint.get("completion_source")
                    if completion_source == "worker":
                        if (
                            completed_checkpoint.get("completed_lease_version") is None
                            or completed_checkpoint.get("completion_reconciliation_id") is not None
                        ):
                            self.connection.rollback()
                            raise RetryCheckpointConflictError("worker checkpoint completion source is inconsistent")
                    elif completion_source == "reconciliation":
                        reconciliation_id = completed_checkpoint.get("completion_reconciliation_id")
                        if (
                            reconciliation_id is None
                            or completed_checkpoint.get("completed_lease_version") is not None
                            or UUID(str(completed_checkpoint.get("completion_id"))) != UUID(str(reconciliation_id))
                        ):
                            self.connection.rollback()
                            raise RetryCheckpointConflictError("reconciliation checkpoint completion source is inconsistent")
                        cursor.execute(
                            """
                            SELECT * FROM maitu_retry_operation_reconciliations
                            WHERE reconciliation_id = %s
                            """,
                            (reconciliation_id,),
                        )
                        reconciliation = cursor.fetchone()
                        stored_result_fingerprint = self._reconciliation_receipt_fingerprint(reconciliation or {})
                        if reconciliation is None or not (
                            UUID(str(reconciliation["reconciliation_id"])) == UUID(str(reconciliation_id))
                            and stored_result_fingerprint is not None
                            and reconciliation["retry_task_code"] == retry_task_code
                            and reconciliation["operation_key"] == operation_key
                            and UUID(str(reconciliation["reconciled_attempt_id"]))
                            == UUID(str(completed_checkpoint["attempt_id"]))
                            and reconciliation["operation_fingerprint"]
                            == completed_checkpoint["operation_fingerprint"]
                            and reconciliation["resolution"] == "confirmed_completed"
                            and reconciliation["resulting_state"] == "completed"
                            and reconciliation["result_fingerprint"] == stored_result_fingerprint
                            and reconciliation["result_fingerprint"]
                            == completed_checkpoint["completion_fingerprint"]
                            and reconciliation["resolved_by"] == completed_checkpoint["completed_by"]
                            and reconciliation["resolution_summary"]
                            == completed_checkpoint["completion_summary"]
                            and reconciliation.get("evidence") == completed_checkpoint.get("completion_evidence")
                        ):
                            self.connection.rollback()
                            raise RetryCheckpointConflictError("reconciliation receipt does not prove checkpoint completion")
                        self._assert_reconciliation_evidence(
                            {
                                "resolution": reconciliation["resolution"],
                                "evidence": reconciliation.get("evidence"),
                            }
                        )
                    else:
                        self.connection.rollback()
                        raise RetryCheckpointConflictError("checkpoint completion source is missing or unsupported")
                    authoritative_operation = self._find_authoritative_retry_operation(
                        cursor,
                        task,
                        operation_key,
                    )
                    if (
                        completed_by_key[operation_key]["operation_fingerprint"]
                        != authoritative_operation["operation_fingerprint"]
                    ):
                        self.connection.rollback()
                        raise RetryCheckpointConflictError(
                            f"completed checkpoint fingerprint drifted for operation {operation_key}"
                        )
            else:
                cursor.execute(
                    """
                    UPDATE maitu_retry_operation_checkpoints
                    SET state = 'reconcile_required', updated_at = now()
                    WHERE retry_task_code = %s
                        AND state = 'begun'
                        AND begun_by = %s
                        AND begun_lease_version = %s
                    """,
                    (retry_task_code, payload["claimed_by"], payload["lease_version"]),
                )

            optional_fields = (
                "last_retry_execution_code",
                "result_summary",
                "error_message",
                "screenshot_asset_code",
                "retry_instruction",
            )
            assignments = ["status = %s"]
            values: list[Any] = [self._retry_task_status_from_execution(payload["retry_execution_status"])]
            if payload["retry_execution_status"] != "released":
                assignments.append("retry_attempt_count = retry_attempt_count + 1")
            assignments.extend(
                [
                    "last_retry_execution_id = %s",
                    "claimed_by = NULL",
                    "claimed_at = NULL",
                    "claim_expires_at = NULL",
                    "claim_token = NULL",
                ]
            )
            values.append(retry_execution_id)
            for field in optional_fields:
                if field in payload:
                    assignments.append(f"{field} = %s")
                    values.append(payload[field])
            values.extend(
                [
                    retry_task_code,
                    payload["claimed_by"],
                    payload["claim_token"],
                    payload["lease_version"],
                ]
            )
            cursor.execute(
                f"""
                UPDATE maitu_execution_retry_tasks
                SET {', '.join(assignments)}, updated_at = now()
                WHERE retry_task_code = %s
                    AND deleted_at IS NULL
                    AND status = 'in_progress'
                    AND claimed_by = %s
                    AND claim_token = %s
                    AND lease_version = %s
                    AND claim_expires_at IS NOT NULL
                    AND claim_expires_at >= now()
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
            if row is None:
                self.connection.rollback()
                raise RetryLeaseConflictError("lease expired while writing the execution result")

            cursor.execute(
                """
                INSERT INTO maitu_retry_execution_receipts (
                    retry_execution_id, retry_task_code, claimed_by, lease_version,
                    retry_execution_status, result_fingerprint, result_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (retry_execution_id) DO NOTHING
                RETURNING retry_execution_id
                """,
                (
                    retry_execution_id,
                    retry_task_code,
                    payload["claimed_by"],
                    payload["lease_version"],
                    payload["retry_execution_status"],
                    fingerprint,
                    Jsonb(receipt_payload),
                ),
            )
            inserted_receipt = cursor.fetchone()
            if inserted_receipt is None:
                self.connection.rollback()
                raise RetryExecutionConflictError("retry_execution_id was concurrently used by another result")

        self.connection.commit()
        return self._normalize_retry_task(row)

    def _next_slot_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.MAITU_SLOT.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_maitu_slot_code(sequence_date, sequence)

    def _next_plan_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.MAITU_PLAN.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_maitu_plan_code(sequence_date, sequence)

    def _next_build_plan_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.MAITU_BUILD_PLAN.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_maitu_build_plan_code(sequence_date, sequence)

    def _next_layout_adjustment_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.MAITU_LAYOUT_ADJUSTMENT.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_maitu_layout_adjustment_code(sequence_date, sequence)

    def _next_execution_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.MAITU_EXECUTION.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_maitu_execution_code(sequence_date, sequence)

    def _next_retry_task_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.MAITU_RETRY_TASK.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_maitu_retry_task_code(sequence_date, sequence)

    def _next_jd_live_metric_session_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = BusinessObjectType.JD_LIVE_METRIC_SESSION.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_jd_live_metric_session_code(sequence_date, sequence)

    def resolve_plan_slots(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return self._resolve_plan_slots(payload)

    def _resolve_plan_slots(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        slot_codes = payload.get("slot_codes") or []
        if slot_codes:
            slots = []
            for slot_code in slot_codes:
                slot = self.get_by_code(slot_code)
                if slot is not None:
                    slots.append(slot)
            return slots
        return self.list(
            maitu_project_code=payload.get("maitu_project_code"),
            scene_name=payload.get("scene_name"),
            limit=500,
        )

    def _fetch_plan_items(self, plan_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT slot_code, slot_name, required_category, selected_asset_code,
                    selected_asset_title, match_score, match_reasons, replacement_policy,
                    sort_order, status
                FROM maitu_replacement_plan_items
                WHERE plan_code = %s
                ORDER BY sort_order ASC, created_at ASC
                """,
                (plan_code,),
            )
            rows = cursor.fetchall()
        return [self._normalize_plan_item(row) for row in rows]

    def _fetch_live_room_build_plan_operations(self, build_plan_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT operation_type, operation_name, sort_order, status, scene_name,
                    layer_name, layer_role, required_category, accepted_asset_types,
                    replacement_policy, selected_asset_code, selected_asset_title,
                    selected_asset_display_code, selected_asset_local_file_code,
                    selected_asset_original_filename, selected_asset_local_relative_path,
                    selected_asset_browser_use_hint, match_score, match_reasons,
                    selection_source, script_block_code, script_block_content,
                    instruction, details
                FROM maitu_live_room_build_plan_operations
                WHERE build_plan_code = %s
                ORDER BY sort_order ASC, created_at ASC
                """,
                (build_plan_code,),
            )
            rows = cursor.fetchall()
        return [self._normalize_live_room_build_plan_operation(row) for row in rows]

    def _build_live_room_operations_from_blueprint(
        self,
        blueprint: dict[str, Any],
        *,
        auto_select_assets: bool = False,
        selection_query: str | None = None,
    ) -> list[dict[str, Any]]:
        script_context = self._build_live_room_script_context(blueprint, selection_query)
        operations: list[dict[str, Any]] = [
            {
                "operation_type": "preflight_build_plan",
                "operation_name": "只读预检直播间蓝图",
                "sort_order": 1,
                "status": "ready",
                "instruction": (
                    f"预检蓝图 {blueprint['blueprint_code']}：确认当前麦兔页面、登录态、"
                    "直播间和场景仍匹配；默认不点击正式开播。"
                ),
                "details": {"safety_gate": True},
            }
        ]
        sort_order = 10
        for scene in blueprint.get("scenes", []):
            scene_name = scene.get("scene_name")
            operations.append(
                {
                    "operation_type": "select_scene",
                    "operation_name": f"选择场景 {scene_name}",
                    "sort_order": sort_order,
                    "status": "ready",
                    "scene_name": scene_name,
                    "instruction": (
                        f"在麦兔直播间 {blueprint.get('reference_room_id') or '当前直播间'} 中选择场景 {scene_name}，"
                        "只做定位不保存。"
                    ),
                    "details": {"scene_code": scene.get("scene_code"), "scene_type": scene.get("scene_type")},
                }
            )
            sort_order += 10
            for layer in scene.get("layers", []):
                layer_name = layer.get("layer_name")
                replacement_policy = layer.get("replacement_policy") or "keep_layout"
                operation = {
                    "operation_type": "replace_layer_asset",
                    "operation_name": f"规划图层 {layer_name}",
                    "sort_order": sort_order,
                    "status": "planned",
                    "scene_name": scene_name,
                    "layer_name": layer_name,
                    "layer_role": layer.get("layer_role"),
                    "required_category": layer.get("required_category"),
                    "accepted_asset_types": layer.get("accepted_asset_types") or [],
                    "replacement_policy": replacement_policy,
                    "instruction": (
                        f"在场景 {scene_name} 定位图层 {layer_name}，后续按 {replacement_policy} "
                        "策略匹配素材并保持原布局。"
                    ),
                    "details": {"layer_code": layer.get("layer_code"), "material_tab": layer.get("material_tab")},
                }
                if auto_select_assets:
                    self._attach_selected_asset_to_build_operation(operation, layer, scene, script_context)
                operations.append(operation)
                sort_order += 10
        for block in blueprint.get("script_blocks", []):
            operations.append(
                {
                    "operation_type": "add_script_block",
                    "operation_name": f"写入脚本块 {block.get('script_block_code')}",
                    "sort_order": sort_order,
                    "status": "planned",
                    "scene_name": block.get("scene_name"),
                    "script_block_code": block.get("script_block_code"),
                    "script_block_content": block.get("content"),
                    "instruction": (
                        f"在场景 {block.get('scene_name')} 的直播脚本区域写入脚本块 "
                        f"{block.get('script_block_code')}，写入后需要重新 Observe 验证。"
                    ),
                    "details": {"source": block.get("source")},
                }
            )
            sort_order += 10
        operations.append(
            {
                "operation_type": "save_live_room",
                "operation_name": "保存直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "instruction": "仅在所有前置操作验证通过后保存直播间草稿；默认不点击正式开播。",
                "details": {"requires_human_or_preflight_pass": True},
            }
        )
        return operations

    @staticmethod
    def _build_single_scene_template_operations(
        scene: dict[str, Any],
        components: list[dict[str, Any]],
        *,
        script_query: str,
        target_script_content: str | None = None,
        target_live_room_id: str | None = None,
    ) -> list[dict[str, Any]]:
        scene_name = scene["scene_name"]
        scene_template_code = scene["scene_template_code"]
        script_content = target_script_content or scene.get("script_content") or script_query
        operations: list[dict[str, Any]] = [
            {
                "operation_type": "preflight_scene_build_plan",
                "operation_name": "只读预检单场景搭建计划",
                "sort_order": 1,
                "status": "ready",
                "instruction": (
                    f"预检单场景模板 {scene_template_code} / {scene_name}：确认目标直播间草稿、登录态、"
                    "组件数量和禁开播规则；此计划为 dry-run，不直接操作麦兔。"
                ),
                "details": {
                    "safety_gate": True,
                    "target_live_room_id": target_live_room_id,
                    "scene_template_code": scene_template_code,
                    "template_library_code": scene.get("template_library_code"),
                    "script_query": script_query,
                },
            },
            {
                "operation_type": "create_scene_from_template",
                "operation_name": f"按模板创建单场景 {scene_name}",
                "sort_order": 10,
                "status": "planned",
                "scene_name": scene_name,
                "instruction": (
                    f"在新直播间草稿中创建/选择一个新场景，按模板场景 {scene_name} "
                    f"({scene_template_code}) 复刻结构；只生成计划，不点击正式开播。"
                ),
                "details": {
                    "scene_template_code": scene_template_code,
                    "template_library_code": scene.get("template_library_code"),
                    "scene_type": scene.get("scene_type"),
                    "reference_product_name": scene.get("reference_product_name"),
                    "reference_item_id": scene.get("reference_item_id"),
                    "reference_clip_id": scene.get("reference_clip_id"),
                    "component_count": len(components),
                },
            },
        ]
        sort_order = 20
        for component in components:
            component_name = component.get("component_name") or component.get("layer_name")
            layer_role = component.get("layer_role") or component.get("component_role")
            replacement_policy = component.get("replacement_policy") or "keep_layout"
            operations.append(
                {
                    "operation_type": "insert_template_component",
                    "operation_name": f"插入模板组件 {component_name}",
                    "sort_order": sort_order,
                    "status": "planned",
                    "scene_name": scene_name,
                    "layer_name": component.get("layer_name") or component_name,
                    "layer_role": layer_role,
                    "required_category": component.get("required_category"),
                    "accepted_asset_types": component.get("accepted_asset_types") or [],
                    "replacement_policy": replacement_policy,
                    "instruction": (
                        f"在单场景 {scene_name} 中插入/配置组件 {component_name}，角色 {layer_role}，"
                        f"保持模板坐标、尺寸和层级；替换策略 {replacement_policy}。"
                    ),
                    "details": {
                        "scene_template_code": scene_template_code,
                        "component_template_code": component.get("component_template_code"),
                        "component_type": component.get("component_type"),
                        "component_role": component.get("component_role"),
                        "material_id": component.get("material_id"),
                        "material_tab": component.get("material_tab"),
                        "source_material_type": component.get("source_material_type"),
                        "geometry": component.get("geometry") or {},
                        "z_index": component.get("z_index"),
                        "speaker_id": component.get("speaker_id"),
                        "digital_human_image_id": component.get("digital_human_image_id"),
                        "source_material_url": component.get("source_material_url"),
                        "source_cover_url": component.get("source_cover_url"),
                    },
                }
            )
            sort_order += 10
        operations.append(
            {
                "operation_type": "add_script_block",
                "operation_name": f"写入单场景脚本 {scene.get('script_block_code')}",
                "sort_order": sort_order,
                "status": "planned",
                "scene_name": scene_name,
                "script_block_code": scene.get("script_block_code"),
                "script_block_content": script_content,
                "instruction": f"在单场景 {scene_name} 的直播脚本区域写入目标脚本，并回读确认文本一致。",
                "details": {
                    "scene_template_code": scene_template_code,
                    "script_query": script_query,
                    "source_template_script_content": scene.get("script_content"),
                    "script_sort_order": scene.get("script_sort_order"),
                },
            }
        )
        operations.append(
            {
                "operation_type": "save_live_room",
                "operation_name": "保存单场景直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "scene_name": scene_name,
                "instruction": "只在组件和脚本回读验证通过后保存草稿；禁止点击正式开播。",
                "details": {"requires_human_or_preflight_pass": True, "scene_template_code": scene_template_code},
            }
        )
        return operations

    @staticmethod
    def _build_live_room_script_context(blueprint: dict[str, Any], selection_query: str | None = None) -> str:
        parts: list[str] = [selection_query or "", blueprint.get("title") or "", blueprint.get("description") or ""]
        for scene in blueprint.get("scenes", []) or []:
            parts.extend([scene.get("scene_name") or "", scene.get("goal") or "", scene.get("scene_type") or ""])
            for layer in scene.get("layers", []) or []:
                parts.extend([
                    layer.get("layer_name") or "",
                    layer.get("layer_role") or "",
                    layer.get("required_category") or "",
                    layer.get("material_tab") or "",
                ])
        for block in blueprint.get("script_blocks", []) or []:
            parts.extend([block.get("scene_name") or "", block.get("content") or ""])
        return "；".join(str(part).strip() for part in parts if str(part or "").strip())

    def _attach_selected_asset_to_build_operation(
        self,
        operation: dict[str, Any],
        layer: dict[str, Any],
        scene: dict[str, Any],
        script_context: str,
    ) -> None:
        candidate = self._select_asset_for_live_room_layer(layer, scene, script_context)
        if candidate is None:
            operation["status"] = "missing_asset"
            operation["selection_source"] = "script_context_rule_filter"
            operation["match_reasons"] = []
            operation["details"] = {**operation.get("details", {}), "asset_selection": {"status": "missing_asset"}}
            operation["instruction"] += " 当前素材库未找到匹配素材；请补充素材或人工选择后再执行。"
            return

        selected_fields = {
            "selected_asset_code": candidate.get("asset_code"),
            "selected_asset_title": candidate.get("title"),
            "selected_asset_display_code": candidate.get("display_code"),
            "selected_asset_local_file_code": candidate.get("local_file_code"),
            "selected_asset_original_filename": candidate.get("original_filename"),
            "selected_asset_local_relative_path": candidate.get("local_relative_path"),
            "selected_asset_browser_use_hint": candidate.get("browser_use_hint"),
            "selected_asset_maitu_material_id": candidate.get("maitu_material_id"),
            "selected_asset_source_material_type": candidate.get("source_material_type"),
            "selected_asset_source_material_url": candidate.get("source_material_url"),
            "selected_asset_source_cover_url": candidate.get("source_cover_url"),
            "selected_asset_speaker_id": candidate.get("speaker_id"),
            "selected_asset_digital_human_image_id": candidate.get("digital_human_image_id"),
            "match_score": candidate.get("match_score"),
            "match_reasons": candidate.get("match_reasons") or [],
            "selection_source": "script_context_rule_filter",
        }
        operation.update(selected_fields)
        operation["status"] = "asset_selected"
        display_code = candidate.get("display_code") or candidate.get("local_file_code") or candidate.get("asset_code")
        title = candidate.get("title") or "未命名素材"
        operation["instruction"] = (
            f"在场景 {operation.get('scene_name')} 定位图层 {operation.get('layer_name')}，"
            f"计划替换为 {display_code}（{title}；AssetGraph编号 {candidate.get('asset_code')}），"
            f"替换策略为 {operation.get('replacement_policy') or 'keep_layout'}；保持原图层位置和尺寸不变。"
        )
        if candidate.get("original_filename"):
            operation["instruction"] += f" 素材文件名：{candidate['original_filename']}。"
        if candidate.get("browser_use_hint"):
            operation["instruction"] += f" 选择提示：{candidate['browser_use_hint']}。"
        operation["details"] = {
            **operation.get("details", {}),
            "asset_selection": {
                "status": "selected",
                "source": "script_context_rule_filter",
                "asset_code": candidate.get("asset_code"),
                "display_code": display_code,
                "match_score": candidate.get("match_score"),
                "match_reasons": candidate.get("match_reasons") or [],
            },
        }

    def select_assets_for_script_asset_need(
        self,
        need: dict[str, Any],
        scene: dict[str, Any],
        *,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        required_category = need.get("required_category")
        if not required_category:
            return []
        accepted_asset_types = [str(item) for item in (need.get("accepted_asset_types") or []) if str(item) != "TEXT"]
        where_clauses = ["deleted_at IS NULL", "maitu_category = %s"]
        values: list[Any] = [required_category]
        if accepted_asset_types:
            placeholders = ", ".join(["%s"] * len(accepted_asset_types))
            where_clauses.append(f"asset_type IN ({placeholders})")
            values.extend(accepted_asset_types)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT asset_code, asset_type, title, original_filename, display_code,
                    local_file_code, local_relative_path, browser_use_hint,
                    maitu_material_id, source_material_type, source_material_url,
                    source_cover_url, speaker_id, digital_human_image_id,
                    maitu_category, maitu_type, maitu_project_code, maitu_scene_name,
                    maitu_layer_name, maitu_slot_name, subject, usage,
                    replacement_policy, description
                FROM assets
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT 200
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        candidates = [
            self._score_script_asset_need_candidate(dict(row), need, scene)
            for row in rows
            if not self._is_direct_layer_forbidden_template_asset(dict(row), need)
        ]
        candidates.sort(key=lambda candidate: (candidate["match_score"], str(candidate.get("asset_code") or "")), reverse=True)
        return candidates[:limit]

    def select_asset_for_template_component(
        self,
        component: dict[str, Any],
        template_scene: dict[str, Any],
        script_context: str,
    ) -> dict[str, Any] | None:
        return self._select_asset_for_live_room_layer(component, template_scene, script_context)

    def _select_asset_for_live_room_layer(
        self,
        layer: dict[str, Any],
        scene: dict[str, Any],
        script_context: str,
    ) -> dict[str, Any] | None:
        required_category = layer.get("required_category")
        if not required_category:
            return None
        accepted_asset_types = [str(item) for item in (layer.get("accepted_asset_types") or [])]
        where_clauses = ["deleted_at IS NULL", "maitu_category = %s"]
        values: list[Any] = [required_category]
        if accepted_asset_types:
            placeholders = ", ".join(["%s"] * len(accepted_asset_types))
            where_clauses.append(f"asset_type IN ({placeholders})")
            values.extend(accepted_asset_types)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT asset_code, asset_type, title, original_filename, display_code,
                    local_file_code, local_relative_path, browser_use_hint,
                    maitu_material_id, source_material_type, source_material_url,
                    source_cover_url, speaker_id, digital_human_image_id,
                    maitu_category, maitu_type, maitu_project_code, maitu_scene_name,
                    maitu_layer_name, maitu_slot_name, subject, usage,
                    replacement_policy, description
                FROM assets
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT 100
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        selectable_rows = [
            dict(row)
            for row in rows
            if not self._is_direct_layer_forbidden_template_asset(dict(row), layer)
        ]
        scored = [self._score_live_room_asset_candidate(row, layer, scene, script_context) for row in selectable_rows]
        if not scored:
            return None
        scored.sort(key=lambda candidate: (candidate["match_score"], str(candidate.get("asset_code") or "")), reverse=True)
        return scored[0]

    @staticmethod
    def _is_direct_layer_forbidden_template_asset(asset: dict[str, Any], layer: dict[str, Any]) -> bool:
        """Return True when an asset is a template/style preview, not a direct layer module.

        Maitu templates (MT-TPL / 模板预览) are style/structure indexes.  They can
        help choose the component assets that make up a room, but they must not be
        inserted as a background/sticker/video layer themselves.
        """
        layer_role = str(layer.get("layer_role") or "").lower()
        required_category = str(layer.get("required_category") or "").lower()
        if "template" in layer_role or required_category in {"template", "template_style", "template_index"}:
            return False
        marker_text = " ".join(
            str(asset.get(field) or "")
            for field in (
                "display_code",
                "local_file_code",
                "maitu_type",
                "usage",
                "title",
                "original_filename",
                "local_relative_path",
                "browser_use_hint",
            )
        ).lower()
        return "mt-tpl" in marker_text or ("模板" in marker_text and "预览" in marker_text)

    def _score_script_asset_need_candidate(
        self,
        asset: dict[str, Any],
        need: dict[str, Any],
        scene: dict[str, Any],
    ) -> dict[str, Any]:
        score = 0.0
        reasons: list[str] = []
        required_category = need.get("required_category")
        accepted_asset_types = [str(item) for item in (need.get("accepted_asset_types") or []) if str(item) != "TEXT"]
        if asset.get("maitu_category") == required_category:
            score += 0.55
            reasons.append(f"maitu_category matches required_category: {required_category}")
        if not accepted_asset_types or asset.get("asset_type") in accepted_asset_types:
            score += 0.20
            reasons.append(f"asset_type accepted: {asset.get('asset_type')}")

        asset_text = " ".join(
            str(asset.get(field) or "")
            for field in (
                "title",
                "original_filename",
                "display_code",
                "local_file_code",
                "browser_use_hint",
                "subject",
                "usage",
                "description",
            )
        )
        keyword_hits = []
        for keyword in need.get("keywords") or []:
            token = str(keyword).strip()
            if token and token in asset_text:
                keyword_hits.append(token)
        for keyword in self._dedupe_texts(keyword_hits)[:3]:
            score += 0.10
            reasons.append(f"keyword matches asset: {keyword}")

        scene_keywords = " ".join(str(item) for item in (scene.get("keywords") or []))
        for token in self._selection_tokens("；".join([scene.get("script") or "", scene_keywords])):
            if token and token in asset_text and token not in keyword_hits:
                score += 0.05
                reasons.append(f"scene context matches asset: {token}")
                break

        if need.get("priority") == "high":
            score += 0.02
        asset["match_score"] = round(min(score, 1.0), 4)
        asset["match_reasons"] = self._dedupe_texts(reasons)
        return asset

    @staticmethod
    def _dedupe_texts(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def _score_live_room_asset_candidate(
        self,
        asset: dict[str, Any],
        layer: dict[str, Any],
        scene: dict[str, Any],
        script_context: str,
    ) -> dict[str, Any]:
        score = 0.0
        reasons: list[str] = []
        required_category = layer.get("required_category")
        accepted_asset_types = [str(item) for item in (layer.get("accepted_asset_types") or [])]
        if asset.get("maitu_category") == required_category:
            score += 0.55
            reasons.append(f"maitu_category matches required_category: {required_category}")
        if not accepted_asset_types or asset.get("asset_type") in accepted_asset_types:
            score += 0.20
            reasons.append(f"asset_type accepted: {asset.get('asset_type')}")
        if scene.get("scene_name") and asset.get("maitu_scene_name") == scene.get("scene_name"):
            score += 0.05
            reasons.append(f"scene_name matches: {scene.get('scene_name')}")
        if layer.get("layer_name") and asset.get("maitu_layer_name") == layer.get("layer_name"):
            score += 0.05
            reasons.append(f"layer_name matches: {layer.get('layer_name')}")

        asset_text = " ".join(
            str(asset.get(field) or "")
            for field in ("title", "original_filename", "display_code", "local_file_code", "browser_use_hint", "subject", "usage", "description")
        ).lower()
        for token in self._selection_tokens(script_context):
            if token.lower() in asset_text:
                score += 0.15
                reasons.append(f"script context mentions {token}")
                break
        layer_role = str(layer.get("layer_role") or "").lower()
        if "product" in layer_role and ("product" in asset_text or "商品" in asset_text):
            score += 0.05
            reasons.append("layer_role product matches asset usage/title")
        if "digital_human" in layer_role and asset.get("asset_type") in {"VID", "IMG"}:
            score += 0.03
            reasons.append("digital human layer accepts avatar material")

        asset["match_score"] = round(min(score, 1.0), 4)
        asset["match_reasons"] = reasons
        return asset

    @staticmethod
    def _selection_tokens(text: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z]+\d*|\d+[A-Za-z]*", text or "")
        priority = []
        for token in tokens:
            normalized = token.strip()
            if len(normalized) >= 2 and normalized.upper() not in {"MT", "IMG", "VID", "PROD"}:
                priority.append(normalized)
        for keyword in ("品酒大师PRO", "品酒大师MASTER", "品酒大师SUPER", "品酒大师PLUS", "张裕", "解百纳"):
            if keyword in (text or ""):
                priority.insert(0, keyword)
        seen: set[str] = set()
        result: list[str] = []
        for token in priority:
            key = token.lower()
            if key not in seen:
                seen.add(key)
                result.append(token)
        return result[:8]

    def _fetch_asset_operation_metadata(self, asset_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, title, original_filename, display_code, local_file_code,
                    local_relative_path, browser_use_hint
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (asset_code,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def _fetch_operation_results(self, execution_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, slot_code, operation_type, asset_code, status, failure_type,
                    retryable, retry_instruction, error_message, screenshot_asset_code,
                    details, sort_order
                FROM maitu_replacement_plan_operation_results
                WHERE execution_code = %s
                ORDER BY sort_order ASC, created_at ASC
                """,
                (execution_code,),
            )
            rows = cursor.fetchall()
        return [self._normalize_operation_result(row) for row in rows]

    def _fetch_live_room_build_plan_operation_results(self, execution_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, operation_index, operation_type, operation_name, scene_name,
                    layer_name, action_type, status, failure_type, retryable,
                    retry_instruction, error_message, screenshot_asset_code,
                    dom_snapshot_asset_code, details, sort_order
                FROM maitu_live_room_build_plan_operation_results
                WHERE execution_code = %s
                ORDER BY sort_order ASC, created_at ASC
                """,
                (execution_code,),
            )
            rows = cursor.fetchall()
        return [self._normalize_live_room_build_plan_operation_result(row) for row in rows]

    def _create_retry_tasks_for_execution(
        self,
        cursor: Any,
        execution_code: str,
        plan_code: str,
        payload: dict[str, Any],
    ) -> None:
        retryable_operations = [operation for operation in payload.get("operation_results", []) if operation.get("retryable")]
        if retryable_operations:
            for operation in retryable_operations:
                self._insert_retry_task(cursor, execution_code, plan_code, payload, operation)
            return
        if payload.get("retryable"):
            self._insert_retry_task(cursor, execution_code, plan_code, payload, None)

    def _insert_retry_task(
        self,
        cursor: Any,
        execution_code: str,
        plan_code: str,
        execution_payload: dict[str, Any],
        operation_payload: dict[str, Any] | None,
    ) -> None:
        retry_task_code = self._next_retry_task_code()
        source = operation_payload or execution_payload
        cursor.execute(
            """
            INSERT INTO maitu_execution_retry_tasks (
                retry_task_code, plan_code, execution_code, slot_code, asset_code,
                executor, failure_type, retryable, retry_instruction, status,
                error_message, screenshot_asset_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
            """,
            (
                retry_task_code,
                plan_code,
                execution_code,
                operation_payload.get("slot_code") if operation_payload else None,
                operation_payload.get("asset_code") if operation_payload else None,
                execution_payload.get("executor", "browser_use"),
                source.get("failure_type"),
                True,
                source.get("retry_instruction"),
                source.get("error_message"),
                source.get("screenshot_asset_code"),
            ),
        )

    @staticmethod
    def _plan_status_from_execution(execution_status: str) -> str:
        if execution_status == "succeeded":
            return "executed"
        if execution_status == "partial_failed":
            return "partial_failed"
        if execution_status == "failed":
            return "execution_failed"
        return "execution_reported"

    @staticmethod
    def _build_plan_status_from_execution(execution_status: str) -> str:
        if execution_status in {"succeeded", "completed"}:
            return "executed"
        if execution_status == "partial_failed":
            return "partial_failed"
        if execution_status == "failed":
            return "execution_failed"
        if execution_status == "blocked":
            return "execution_blocked"
        return "execution_reported"

    @staticmethod
    def _operation_fingerprint(intent: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _build_retry_operations(
        cls,
        task: dict[str, Any],
        plan: dict[str, Any],
        slot: dict[str, Any],
        plan_item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        retry_task_code = task["retry_task_code"]
        scene_name = slot.get("scene_name") or plan.get("scene_name")
        layer_name = slot.get("layer_name")
        slot_name = plan_item.get("slot_name") or slot.get("slot_name")
        asset_title = plan_item.get("selected_asset_title")
        policy = plan_item.get("replacement_policy") or slot.get("replacement_policy") or "keep_layout"
        status = "ready" if task.get("retryable") and task.get("status") in {"pending", "in_progress"} else "blocked"
        primary_operation_type = cls._retry_operation_type_for_failure(task.get("failure_type"))
        instruction = (
            f"执行重试任务 {retry_task_code}：{task.get('retry_instruction') or '按失败原因重试'}；"
            f"进入麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
            f"只重试槽位 {task.get('slot_code') or '整体执行'}，找到 {layer_name or slot_name or '目标图层/槽位'}，"
            f"将素材替换为 {task.get('asset_code') or '原计划素材'}（{asset_title or '未命名素材'}），"
            f"替换策略为 {policy}；保持原图层位置和尺寸不变。"
        )
        fingerprint_base = {
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": scene_name,
            "slot_code": task.get("slot_code"),
            "layer_name": layer_name,
            "asset_code": task.get("asset_code"),
            "replacement_policy": policy,
            "primary_operation_type": primary_operation_type,
        }

        def operation(operation_key: str, operation_type: str, operation_instruction: str) -> dict[str, Any]:
            fingerprint_intent = {**fingerprint_base, "operation_key": operation_key, "operation_type": operation_type}
            return {
                "operation_key": operation_key,
                "operation_fingerprint": cls._operation_fingerprint(fingerprint_intent),
                "operation_type": operation_type,
                "retry_task_code": retry_task_code,
                "slot_code": task.get("slot_code"),
                "slot_name": slot_name,
                "scene_name": scene_name,
                "layer_name": layer_name,
                "asset_code": task.get("asset_code"),
                "asset_title": asset_title,
                "replacement_policy": policy,
                "failure_type": task.get("failure_type"),
                "status": status,
                "instruction": operation_instruction,
            }

        save_instruction = (
            f"保存麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
            "并以权威持久化状态确认保存完成。"
        )
        if primary_operation_type == "retry_save_project":
            return [operation("save_project", "retry_save_project", save_instruction)]
        return [
            operation("primary", primary_operation_type, instruction),
            operation("save_project", "retry_save_project", save_instruction),
        ]

    @staticmethod
    def _assert_current_retry_lease(task: dict[str, Any], payload: dict[str, Any]) -> None:
        if not (
            task.get("status") == "in_progress"
            and task.get("lease_active") is True
            and task.get("claimed_by") == payload["claimed_by"]
            and str(task.get("claim_token")) == str(payload["claim_token"])
            and task.get("lease_version") == payload["lease_version"]
        ):
            raise RetryLeaseConflictError("lease is expired or owned by another claim")

    @staticmethod
    def _lock_retry_task_for_checkpoint(cursor: Any, retry_task_code: str) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT rt.*, rt.claim_expires_at >= now() AS lease_active
            FROM maitu_execution_retry_tasks rt
            WHERE rt.retry_task_code = %s AND rt.deleted_at IS NULL
            FOR UPDATE
            """,
            (retry_task_code,),
        )
        return cursor.fetchone()

    def _find_authoritative_retry_operation(
        self,
        cursor: Any,
        task: dict[str, Any],
        operation_key: str,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT rp.maitu_project_code, rp.scene_name AS plan_scene_name,
                   ms.scene_name AS slot_scene_name, ms.layer_name, ms.slot_name,
                   ms.replacement_policy AS slot_replacement_policy,
                   rpi.slot_name AS item_slot_name,
                   rpi.selected_asset_title,
                   rpi.replacement_policy AS item_replacement_policy
            FROM (SELECT 1) AS anchor
            LEFT JOIN maitu_replacement_plans rp
                ON rp.plan_code = %s AND rp.deleted_at IS NULL
            LEFT JOIN maitu_material_slots ms
                ON ms.slot_code = %s AND ms.deleted_at IS NULL
            LEFT JOIN maitu_replacement_plan_items rpi
                ON rpi.plan_code = %s AND rpi.slot_code = %s
            """,
            (task["plan_code"], task.get("slot_code"), task["plan_code"], task.get("slot_code")),
        )
        context = cursor.fetchone() or {}
        plan = {
            "maitu_project_code": context.get("maitu_project_code"),
            "scene_name": context.get("plan_scene_name"),
        }
        slot = {
            "scene_name": context.get("slot_scene_name"),
            "layer_name": context.get("layer_name"),
            "slot_name": context.get("slot_name"),
            "replacement_policy": context.get("slot_replacement_policy"),
        }
        plan_item = {
            "slot_name": context.get("item_slot_name"),
            "selected_asset_title": context.get("selected_asset_title"),
            "replacement_policy": context.get("item_replacement_policy"),
        }
        operation = next(
            (
                candidate
                for candidate in self._build_retry_operations(task, plan, slot, plan_item)
                if candidate["operation_key"] == operation_key
            ),
            None,
        )
        if operation is None:
            raise RetryCheckpointConflictError("operation key is not present in the authoritative retry plan")
        return operation

    @staticmethod
    def _reconciliation_payload_fingerprint(payload: dict[str, Any]) -> str:
        durable_payload = {
            "reconciliation_id": str(UUID(str(payload["reconciliation_id"]))),
            "expected_attempt_id": str(UUID(str(payload["expected_attempt_id"]))),
            "operation_fingerprint": payload["operation_fingerprint"],
            "resolution": payload["resolution"],
            "resolved_by": payload["resolved_by"],
            "resolution_summary": payload["resolution_summary"],
            "evidence": payload["evidence"],
        }
        return hashlib.sha256(
            json.dumps(durable_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _reconciliation_receipt_fingerprint(cls, receipt: dict[str, Any]) -> str | None:
        try:
            return cls._reconciliation_payload_fingerprint(
                {
                    "reconciliation_id": receipt["reconciliation_id"],
                    "expected_attempt_id": receipt["reconciled_attempt_id"],
                    "operation_fingerprint": receipt["operation_fingerprint"],
                    "resolution": receipt["resolution"],
                    "resolved_by": receipt["resolved_by"],
                    "resolution_summary": receipt["resolution_summary"],
                    "evidence": receipt["evidence"],
                }
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _assert_reconciliation_evidence(payload: dict[str, Any]) -> None:
        evidence = payload.get("evidence")
        expected_applied = payload.get("resolution") == "confirmed_completed"
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            raise RetryCheckpointConflictError("reconciliation evidence must be an authoritative verified readback")
        if evidence.get("operation_applied") is not expected_applied:
            raise RetryCheckpointConflictError("reconciliation evidence operation_applied must match resolution")

        if contains_durable_secret(
            {
                "resolution_summary": payload.get("resolution_summary"),
                "evidence": evidence,
            }
        ):
            raise RetryCheckpointConflictError("reconciliation durable fields must not contain credentials")

    @staticmethod
    def _completion_payload_fingerprint(payload: dict[str, Any]) -> str:
        durable_payload = {
            "attempt_id": str(payload["attempt_id"]),
            "completion_id": str(payload["completion_id"]),
            "operation_fingerprint": payload["operation_fingerprint"],
            "result_summary": payload.get("result_summary"),
            "evidence": payload.get("evidence", {}),
        }
        return hashlib.sha256(
            json.dumps(durable_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _assert_retry_execution_payload_token_free(payload: dict[str, Any]) -> None:
        claim_token = str(payload["claim_token"]).lower()

        def contains_claim_token(candidate: Any) -> bool:
            if isinstance(candidate, dict):
                return any(contains_claim_token(value) for value in candidate.values())
            if isinstance(candidate, list):
                return any(contains_claim_token(value) for value in candidate)
            return isinstance(candidate, str) and claim_token in candidate.lower()

        durable_payload = {key: value for key, value in payload.items() if key != "claim_token"}
        if contains_claim_token(durable_payload):
            raise RetryExecutionConflictError(
                "retry execution result durable fields must not contain the active claim token"
            )

    @staticmethod
    def _assert_verified_secret_free_evidence(evidence: Any, claim_token: Any) -> None:
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            raise RetryCheckpointConflictError("checkpoint evidence must be an authoritative verified readback")

        token_text = str(claim_token).lower()

        def contains_secret(candidate: Any) -> bool:
            if isinstance(candidate, dict):
                for key, value in candidate.items():
                    key_text = str(key).lower()
                    if token_text in key_text:
                        return True
                    normalized_key = re.sub(r"[^a-z0-9]", "", key_text)
                    if any(
                        marker in normalized_key
                        for marker in ("authorization", "credential", "password", "secret", "cookie", "token")
                    ):
                        return True
                    if contains_secret(value):
                        return True
                return False
            if isinstance(candidate, list):
                return any(contains_secret(value) for value in candidate)
            return isinstance(candidate, str) and token_text in candidate.lower()

        if contains_secret(evidence):
            raise RetryCheckpointConflictError(
                "checkpoint evidence must not contain credentials or the active claim token"
            )

    def _lock_slot_retry_intent_for_mutation(self, cursor: Any, slot_code: str) -> None:
        cursor.execute(
            """
            SELECT retry_task_code, status
            FROM maitu_execution_retry_tasks
            WHERE slot_code = %s AND deleted_at IS NULL
            ORDER BY retry_task_code
            FOR UPDATE
            """,
            (slot_code,),
        )
        retry_tasks = cursor.fetchall()
        if any(task.get("status") == "in_progress" for task in retry_tasks):
            self.connection.rollback()
            raise RetryLeaseConflictError(
                "slot authoritative intent cannot change while a related retry worker lease is active"
            )

    @staticmethod
    def _retry_operation_type_for_failure(failure_type: str | None) -> str:
        mapping = {
            "missing_layer": "retry_replace_layer_asset",
            "selector_changed": "retry_replace_layer_asset",
            "asset_upload_failed": "retry_asset_upload_and_replace",
            "save_failed": "retry_save_project",
            "login_expired": "recover_login_then_retry",
            "missing_asset": "resolve_missing_slot_asset",
            "manual_required": "manual_retry_required",
        }
        return mapping.get(failure_type, "retry_browser_use_operation")

    @staticmethod
    def _retry_task_status_from_execution(retry_execution_status: str) -> str:
        mapping = {
            "succeeded": "succeeded",
            "failed": "failed",
            "manual_required": "manual_required",
            "released": "pending",
        }
        return mapping.get(retry_execution_status, retry_execution_status)

    def _rebuild_live_room_template_component_index(
        self,
        cursor: Any,
        blueprint_row: dict[str, Any] | None,
        blueprint: dict[str, Any],
        profile: dict[str, Any],
    ) -> None:
        if blueprint_row is None:
            return
        blueprint_code = str(blueprint_row["blueprint_code"])
        template_library_code = blueprint.get("template_library_code") or profile.get("template_library_code")
        script_blocks_by_scene = self._script_blocks_by_scene(blueprint.get("script_blocks"))

        cursor.execute("DELETE FROM maitu_live_room_template_components WHERE blueprint_code = %s", (blueprint_code,))
        cursor.execute("DELETE FROM maitu_live_room_template_scenes WHERE blueprint_code = %s", (blueprint_code,))

        for scene_index, scene in enumerate(self._dict_list(blueprint.get("scenes"))):
            scene_name = str(scene.get("scene_name") or f"场景{scene_index + 1:02d}")
            scene_template_code = self._scene_template_code(blueprint_code, scene, scene_index)
            scene_code = scene.get("scene_code") or scene_template_code
            script_block = script_blocks_by_scene.get(scene_name) or {}
            layers = self._dict_list(scene.get("layers"))
            cursor.execute(
                """
                INSERT INTO maitu_live_room_template_scenes (
                    blueprint_id, blueprint_code, template_library_code, scene_template_code,
                    scene_code, scene_name, scene_type, sort_order, reference_product_name,
                    reference_item_id, reference_clip_id, script_block_code, script_sort_order,
                    script_content, component_count, raw_scene
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    blueprint_row["id"],
                    blueprint_code,
                    template_library_code,
                    scene_template_code,
                    scene_code,
                    scene_name,
                    scene.get("scene_type"),
                    scene.get("sort_order") if scene.get("sort_order") is not None else scene_index + 1,
                    scene.get("reference_product_name"),
                    self._optional_str(scene.get("reference_item_id")),
                    self._optional_str(scene.get("reference_clip_id")),
                    script_block.get("script_block_code"),
                    script_block.get("sort_order"),
                    script_block.get("content"),
                    len(layers),
                    Jsonb(scene),
                ),
            )
            scene_row = cursor.fetchone()
            for layer_index, layer in enumerate(layers):
                component_template_code = self._component_template_code(scene_template_code, layer, layer_index)
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_template_components (
                        scene_template_id, blueprint_code, template_library_code,
                        scene_template_code, component_template_code, scene_code, scene_name,
                        scene_type, reference_product_name, reference_item_id, reference_clip_id,
                        component_name, component_type, component_role, layer_code, layer_name,
                        layer_role, material_id, material_tab, source_material_type,
                        required_category, accepted_asset_types, replacement_policy, geometry,
                        z_index, speaker_id, digital_human_image_id, source_material_url,
                        source_cover_url, sort_order, raw_layer
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        scene_row["id"],
                        blueprint_code,
                        template_library_code,
                        scene_template_code,
                        component_template_code,
                        scene_code,
                        scene_name,
                        scene.get("scene_type"),
                        scene.get("reference_product_name"),
                        self._optional_str(scene.get("reference_item_id")),
                        self._optional_str(scene.get("reference_clip_id")),
                        layer.get("component_name") or layer.get("layer_name"),
                        layer.get("component_type") or layer.get("source_material_type"),
                        layer.get("component_role") or layer.get("layer_role"),
                        layer.get("layer_code") or component_template_code,
                        layer.get("layer_name"),
                        layer.get("layer_role"),
                        layer.get("material_id"),
                        layer.get("material_tab"),
                        layer.get("source_material_type"),
                        layer.get("required_category"),
                        Jsonb(layer.get("accepted_asset_types") or []),
                        layer.get("replacement_policy"),
                        Jsonb(self._layer_geometry(layer)),
                        layer.get("z_index"),
                        layer.get("speaker_id"),
                        layer.get("digital_human_image_id"),
                        layer.get("source_material_url"),
                        layer.get("source_cover_url"),
                        layer.get("sort_order") if layer.get("sort_order") is not None else layer_index + 1,
                        Jsonb(layer),
                    ),
                )

    def _search_live_room_scene_components_by_script_from_index(
        self,
        *,
        q: str,
        reference_room_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["s.deleted_at IS NULL", "b.deleted_at IS NULL", "s.script_content ILIKE %s"]
        values: list[Any] = [f"%{q}%"]
        if reference_room_id is not None:
            where_clauses.append("b.reference_room_id = %s")
            values.append(reference_room_id)
        if status is not None:
            where_clauses.append("b.status = %s")
            values.append(status)
        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT s.*, b.title AS blueprint_title, b.reference_room_id,
                    b.reference_room_name, b.platform AS blueprint_platform,
                    b.status AS blueprint_status, b.room_type AS blueprint_room_type
                FROM maitu_live_room_template_scenes s
                JOIN maitu_live_room_blueprints b ON b.blueprint_code = s.blueprint_code
                WHERE {' AND '.join(where_clauses)}
                ORDER BY b.created_at DESC, s.sort_order ASC NULLS LAST, s.scene_template_code ASC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            scene_rows = cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in scene_rows:
            scene = self._normalize_live_room_template_scene(row)
            components = self.list_live_room_template_scene_components(scene["scene_template_code"]) or []
            results.append(self._scene_component_search_index_result(scene, components, dict(row)))
        return results

    @classmethod
    def _scene_component_search_index_result(
        cls,
        scene: dict[str, Any],
        components: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        component_map: dict[tuple[Any, ...], dict[str, Any]] = {}
        component_placements: list[dict[str, Any]] = []
        for component_row in components:
            placement = cls._template_component_placement(component_row)
            component_placements.append(placement)
            key = (
                placement.get("layer_name"),
                placement.get("material_id"),
                placement.get("source_material_type"),
                placement.get("layer_role"),
            )
            component = component_map.setdefault(
                key,
                {
                    "component_name": placement.get("layer_name"),
                    "component_type": placement.get("source_material_type"),
                    "component_role": placement.get("layer_role"),
                    "material_id": placement.get("material_id"),
                    "required_category": placement.get("required_category"),
                    "material_tab": placement.get("material_tab"),
                    "source_material_type": placement.get("source_material_type"),
                    "source_material_url": placement.get("source_material_url"),
                    "source_cover_url": placement.get("source_cover_url"),
                    "placements": 0,
                    "scene_names": [],
                    "geometry_examples": [],
                },
            )
            component["placements"] += 1
            placement_scene_name = placement.get("scene_name")
            if placement_scene_name and placement_scene_name not in component["scene_names"]:
                component["scene_names"].append(placement_scene_name)
            geometry = placement.get("geometry") or {}
            if geometry and geometry not in component["geometry_examples"] and len(component["geometry_examples"]) < 5:
                component["geometry_examples"].append(geometry)

        matched_script_blocks = []
        if scene.get("script_content"):
            matched_script_blocks.append(
                {
                    "script_block_code": scene.get("script_block_code"),
                    "scene_name": scene.get("scene_name"),
                    "sort_order": scene.get("script_sort_order"),
                    "content": scene.get("script_content"),
                }
            )
        matched_scene_names = [scene["scene_name"]] if scene.get("scene_name") else []
        return {
            "blueprint_code": scene["blueprint_code"],
            "title": metadata.get("blueprint_title") or scene["blueprint_code"],
            "reference_room_id": metadata.get("reference_room_id"),
            "reference_room_name": metadata.get("reference_room_name"),
            "platform": metadata.get("blueprint_platform"),
            "status": metadata.get("blueprint_status") or "template_baseline",
            "room_type": metadata.get("blueprint_room_type") or "template_library_baseline",
            "template_library_code": scene.get("template_library_code"),
            "component_index_source": "template_component_index",
            "matched_script_blocks": matched_script_blocks,
            "matched_scene_names": matched_scene_names,
            "matched_scene_count": len(matched_scene_names),
            "scene_count": 1,
            "script_block_count": len(matched_script_blocks),
            "unique_component_count": len(component_map),
            "component_placement_count": len(component_placements),
            "components": list(component_map.values()),
            "component_placements": component_placements,
        }

    @classmethod
    def _template_component_placement(cls, component: dict[str, Any]) -> dict[str, Any]:
        return {
            "scene_template_code": component.get("scene_template_code"),
            "component_template_code": component.get("component_template_code"),
            "scene_name": component.get("scene_name"),
            "scene_type": component.get("scene_type"),
            "reference_product_name": component.get("reference_product_name"),
            "reference_item_id": component.get("reference_item_id"),
            "reference_clip_id": component.get("reference_clip_id"),
            "layer_code": component.get("layer_code"),
            "layer_name": component.get("layer_name") or component.get("component_name"),
            "layer_role": component.get("layer_role") or component.get("component_role"),
            "material_id": component.get("material_id"),
            "material_tab": component.get("material_tab"),
            "source_material_type": component.get("source_material_type") or component.get("component_type"),
            "required_category": component.get("required_category"),
            "accepted_asset_types": component.get("accepted_asset_types") or [],
            "replacement_policy": component.get("replacement_policy"),
            "geometry": component.get("geometry") or {},
            "z_index": component.get("z_index"),
            "speaker_id": component.get("speaker_id"),
            "digital_human_image_id": component.get("digital_human_image_id"),
            "source_material_url": component.get("source_material_url"),
            "source_cover_url": component.get("source_cover_url"),
        }

    @staticmethod
    def _scene_template_code(blueprint_code: str, scene: dict[str, Any], scene_index: int) -> str:
        return str(scene.get("scene_code") or f"{blueprint_code}-SCENE-{scene_index + 1:03d}")[:128]

    @staticmethod
    def _component_template_code(scene_template_code: str, layer: dict[str, Any], layer_index: int) -> str:
        return str(layer.get("layer_code") or f"{scene_template_code}-COMP-{layer_index + 1:03d}")[:128]

    @staticmethod
    def _script_blocks_by_scene(value: Any) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for block in MaituMaterialSlotRepository._dict_list(value):
            scene_name = str(block.get("scene_name") or "")
            if scene_name and scene_name not in result:
                result[scene_name] = block
        return result

    @staticmethod
    def _layer_geometry(layer: dict[str, Any]) -> dict[str, Any]:
        return {
            "left": layer.get("left_position"),
            "top": layer.get("top_position"),
            "width": layer.get("width"),
            "height": layer.get("height"),
            "scale": layer.get("scale"),
        }

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        return None if value is None else str(value)

    @classmethod
    def _scene_component_search_result(cls, blueprint: dict[str, Any], query: str) -> list[dict[str, Any]]:
        needle = query.lower()
        blocks_by_scene: dict[str | None, list[dict[str, Any]]] = {}
        for block in cls._dict_list(blueprint.get("script_blocks")):
            content = str(block.get("content") or "")
            if needle not in content.lower():
                continue
            scene_name = str(block.get("scene_name") or "") or None
            blocks_by_scene.setdefault(scene_name, []).append(
                {
                    "script_block_code": block.get("script_block_code"),
                    "scene_name": scene_name,
                    "sort_order": block.get("sort_order"),
                    "content": content,
                }
            )
        if not blocks_by_scene:
            return []

        scenes_by_name = {
            str(scene.get("scene_name") or ""): scene
            for scene in cls._dict_list(blueprint.get("scenes"))
            if scene.get("scene_name")
        }
        return [
            cls._scene_component_search_scene_result(blueprint, scene_name, blocks, scenes_by_name.get(scene_name or ""))
            for scene_name, blocks in blocks_by_scene.items()
        ]

    @classmethod
    def _scene_component_search_scene_result(
        cls,
        blueprint: dict[str, Any],
        scene_name: str | None,
        matched_script_blocks: list[dict[str, Any]],
        matched_scene: dict[str, Any] | None,
    ) -> dict[str, Any]:
        component_map: dict[tuple[Any, ...], dict[str, Any]] = {}
        component_placements: list[dict[str, Any]] = []
        if matched_scene is not None:
            for layer in cls._dict_list(matched_scene.get("layers")):
                placement = cls._scene_component_placement(matched_scene, layer)
                component_placements.append(placement)
                key = (
                    placement.get("layer_name"),
                    placement.get("material_id"),
                    placement.get("source_material_type"),
                    placement.get("layer_role"),
                )
                component = component_map.setdefault(
                    key,
                    {
                        "component_name": placement.get("layer_name"),
                        "component_type": placement.get("source_material_type"),
                        "component_role": placement.get("layer_role"),
                        "material_id": placement.get("material_id"),
                        "required_category": placement.get("required_category"),
                        "material_tab": placement.get("material_tab"),
                        "source_material_type": placement.get("source_material_type"),
                        "source_material_url": placement.get("source_material_url"),
                        "source_cover_url": placement.get("source_cover_url"),
                        "placements": 0,
                        "scene_names": [],
                        "geometry_examples": [],
                    },
                )
                component["placements"] += 1
                placement_scene_name = placement.get("scene_name")
                if placement_scene_name and placement_scene_name not in component["scene_names"]:
                    component["scene_names"].append(placement_scene_name)
                geometry = placement.get("geometry") or {}
                if geometry and geometry not in component["geometry_examples"] and len(component["geometry_examples"]) < 5:
                    component["geometry_examples"].append(geometry)

        reference_profile = blueprint.get("reference_profile") if isinstance(blueprint.get("reference_profile"), dict) else {}
        matched_scene_names = [scene_name] if scene_name else []
        return {
            "blueprint_code": blueprint["blueprint_code"],
            "title": blueprint["title"],
            "reference_room_id": blueprint.get("reference_room_id"),
            "reference_room_name": blueprint.get("reference_room_name"),
            "platform": blueprint.get("platform"),
            "status": blueprint["status"],
            "room_type": blueprint["room_type"],
            "template_library_code": blueprint.get("template_library_code") or reference_profile.get("template_library_code"),
            "matched_script_blocks": matched_script_blocks,
            "matched_scene_names": matched_scene_names,
            "matched_scene_count": len(matched_scene_names),
            "scene_count": 1 if matched_scene is not None else 0,
            "script_block_count": len(matched_script_blocks),
            "unique_component_count": len(component_map),
            "component_placement_count": len(component_placements),
            "components": list(component_map.values()),
            "component_placements": component_placements,
        }

    @staticmethod
    def _scene_component_placement(scene: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
        geometry = {
            "left": layer.get("left_position"),
            "top": layer.get("top_position"),
            "width": layer.get("width"),
            "height": layer.get("height"),
            "scale": layer.get("scale"),
        }
        return {
            "scene_name": scene.get("scene_name"),
            "scene_type": scene.get("scene_type"),
            "reference_product_name": scene.get("reference_product_name"),
            "reference_item_id": scene.get("reference_item_id"),
            "reference_clip_id": scene.get("reference_clip_id"),
            "layer_code": layer.get("layer_code"),
            "layer_name": layer.get("layer_name"),
            "layer_role": layer.get("layer_role"),
            "material_id": layer.get("material_id"),
            "material_tab": layer.get("material_tab"),
            "source_material_type": layer.get("source_material_type"),
            "required_category": layer.get("required_category"),
            "accepted_asset_types": layer.get("accepted_asset_types") or [],
            "replacement_policy": layer.get("replacement_policy"),
            "geometry": geometry,
            "z_index": layer.get("z_index"),
            "speaker_id": layer.get("speaker_id"),
            "digital_human_image_id": layer.get("digital_human_image_id"),
            "source_material_url": layer.get("source_material_url"),
            "source_cover_url": layer.get("source_cover_url"),
        }

    @staticmethod
    def _dict_list(value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _normalize_live_room_blueprint(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.pop("reference_profile_id", None)
        converted.pop("raw_blueprint", None)
        for key in ("scenes", "script_blocks", "material_tabs", "workbench_tabs", "safety_rules"):
            if converted.get(key) is None:
                converted[key] = []
        if converted.get("reference_profile") is None:
            converted["reference_profile"] = {}
        return converted

    @staticmethod
    def _normalize_live_room_template_scene(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.pop("blueprint_id", None)
        converted.pop("raw_scene", None)
        converted.pop("deleted_at", None)
        return converted

    @staticmethod
    def _normalize_live_room_template_component(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.pop("scene_template_id", None)
        converted.pop("raw_layer", None)
        converted.pop("deleted_at", None)
        if converted.get("accepted_asset_types") is None:
            converted["accepted_asset_types"] = []
        if converted.get("geometry") is None:
            converted["geometry"] = {}
        return converted

    @staticmethod
    def _normalize_live_room_build_plan(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.setdefault("operations", [])
        return converted

    @staticmethod
    def _normalize_live_room_build_plan_operation(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if converted.get("accepted_asset_types") is None:
            converted["accepted_asset_types"] = []
        if converted.get("match_reasons") is None:
            converted["match_reasons"] = []
        if isinstance(converted.get("match_score"), Decimal):
            converted["match_score"] = float(converted["match_score"])
        if converted.get("details") is None:
            converted["details"] = {}
        return converted

    @staticmethod
    def _normalize_layout_adjustment(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        if converted.get("checks") is None:
            converted["checks"] = []
        if converted.get("operation") is None:
            converted["operation"] = {}
        return converted

    @staticmethod
    def _normalize_plan(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.setdefault("items", [])
        return converted

    @staticmethod
    def _normalize_plan_item(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if isinstance(converted.get("match_score"), Decimal):
            converted["match_score"] = float(converted["match_score"])
        if converted.get("match_reasons") is None:
            converted["match_reasons"] = []
        return converted

    @staticmethod
    def _normalize_execution(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.setdefault("operation_results", [])
        return converted

    @staticmethod
    def _normalize_live_room_build_plan_execution(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.setdefault("operation_results", [])
        return converted

    @staticmethod
    def _normalize_operation_result(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        if converted.get("details") is None:
            converted["details"] = {}
        return converted

    @staticmethod
    def _normalize_live_room_build_plan_operation_result(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        if converted.get("details") is None:
            converted["details"] = {}
        return converted

    @staticmethod
    def _normalize_jd_live_metric_session(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.pop("deleted_at", None)
        if converted.get("metric_names") is None:
            converted["metric_names"] = []
        if converted.get("scene_schedule") is None:
            converted["scene_schedule"] = []
        if converted.get("config") is None:
            converted["config"] = {}
        return converted

    @staticmethod
    def _normalize_jd_live_metric_sample(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted.pop("capture_session_id", None)
        for field in (
            "average_stay_seconds",
            "product_click_rate",
            "product_conversion_rate",
            "gmv",
            "uv_value",
            "transaction_amount",
        ):
            if isinstance(converted.get(field), Decimal):
                converted[field] = float(converted[field])
        if converted.get("traffic_sources") is None:
            converted["traffic_sources"] = {}
        if converted.get("interaction_data") is None:
            converted["interaction_data"] = {}
        if converted.get("raw_metrics") is None:
            converted["raw_metrics"] = {}
        return converted

    @staticmethod
    def _normalize_retry_reconciliation(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        converted["reconciliation_id"] = str(converted["reconciliation_id"])
        converted["reconciled_attempt_id"] = str(converted["reconciled_attempt_id"])
        converted["evidence"] = converted.get("evidence") or {}
        return converted

    @staticmethod
    def _normalize_retry_checkpoint(row: dict[str, Any], decision: str | None) -> dict[str, Any]:
        converted = dict(row)
        for field in ("attempt_id", "completion_id", "completion_reconciliation_id"):
            if converted.get(field) is not None:
                converted[field] = str(converted[field])
        converted["evidence"] = converted.pop("completion_evidence", {}) or {}
        converted["result_summary"] = converted.pop("completion_summary", None)
        converted["decision"] = decision
        return converted

    @staticmethod
    def _normalize_retry_task(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in ("id", "claim_token", "last_retry_execution_id"):
            if field in converted and converted[field] is not None:
                converted[field] = str(converted[field])
        return converted

    def _normalize_retry_queue_item(self, row: dict[str, Any]) -> dict[str, Any]:
        converted = self._normalize_retry_task(row)
        retry_task_code = converted["retry_task_code"]
        converted["next_operation_type"] = self._retry_operation_type_for_failure(converted.get("failure_type"))
        converted["browser_use_operations_url"] = f"/api/maitu/retry-tasks/{retry_task_code}/browser-use-operations"
        return converted

    def _filter_writable(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {field: payload[field] for field in self.writable_fields if field in payload}

    @staticmethod
    def _serialize_asset_types(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return ",".join(str(item) for item in value)

    @classmethod
    def _normalize_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        converted["accepted_asset_types"] = cls._parse_asset_types(converted.get("accepted_asset_types"))
        for field in ("left_position", "top_position", "width", "height"):
            if isinstance(converted.get(field), Decimal):
                converted[field] = float(converted[field])
        return converted

    @classmethod
    def _normalize_candidate_asset(cls, row: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in ("layer_width", "layer_height"):
            if isinstance(converted.get(field), Decimal):
                converted[field] = float(converted[field])

        score = 0.5
        reasons = [f"maitu_category matches required_category: {slot['required_category']}"]
        if converted.get("asset_type") in slot.get("accepted_asset_types", []):
            score += 0.2
            reasons.append(f"asset_type accepted: {converted['asset_type']}")
        if slot.get("maitu_project_code") and converted.get("maitu_project_code") == slot.get("maitu_project_code"):
            score += 0.1
            reasons.append(f"maitu_project_code matches: {slot['maitu_project_code']}")
        if slot.get("scene_name") and converted.get("maitu_scene_name") == slot.get("scene_name"):
            score += 0.1
            reasons.append(f"scene_name matches: {slot['scene_name']}")
        if converted.get("maitu_slot_code") == slot.get("slot_code"):
            score += 0.1
            reasons.append(f"maitu_slot_code matches: {slot['slot_code']}")
        elif slot.get("slot_name") and converted.get("maitu_slot_name") == slot.get("slot_name"):
            score += 0.1
            reasons.append(f"slot_name matches: {slot['slot_name']}")

        converted.pop("created_at", None)
        converted["match_score"] = min(round(score, 4), 1.0)
        converted["match_reasons"] = reasons
        return converted

    @staticmethod
    def _parse_asset_types(value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [item.strip() for item in str(value).split(",") if item.strip()]
