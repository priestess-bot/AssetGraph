from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.core.maitu_retry_intent import (
    is_canonical_retry_before_state,
    is_canonical_retry_operation_intent,
)
from app.core.secret_hygiene import contains_durable_secret
from app.services.maitu_asset_taxonomy import (
    asset_matches_product_identity,
    asset_matches_required_category,
    asset_product_identity_mentioned_in_text,
    product_identity_keywords,
    required_category_variants,
)
from app.services.maitu_binding_identity import canonical_maitu_binding_identity
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


class BuildPlanCheckpointConflictError(RuntimeError):
    """A script-layout BuildPlan checkpoint conflicts with persisted execution state."""


class MaituMaterialSlotRepository:
    SCRIPT_LAYOUT_LEASE_SECONDS = 180
    SCRIPT_LAYOUT_RECONCILE_GRACE_SECONDS = 130
    SCRIPT_LAYOUT_MUTATING_OPERATIONS = {
        "fill_default_scene",
        "create_scene",
        "insert_asset_layer",
        "position_asset_layer",
        "write_script",
    }
    SCRIPT_LAYOUT_READ_ONLY_OPERATIONS = {
        "preflight_content_build_plan",
        "verify_scene",
        "verify_draft_persisted",
    }
    SCRIPT_LAYOUT_MANUAL_NOOP_OPERATIONS = {"placeholder_required", "save_draft"}
    SCRIPT_LAYOUT_RESOLVER_MUTABLE_FIELDS = {
        "maitu_material_id",
        "maitu_source_material_id",
        "material_id",
        "source_material_type",
        "source_material_url",
        "source_cover_url",
        "speaker_id",
        "digital_human_image_id",
        "material_resolution_status",
        "material_resolution_reason",
    }

    writable_fields = (
        "slot_name",
        "maitu_project_code",
        "scene_name",
        "scene_index",
        "layer_name",
        "layer_index",
        "target_live_room_id",
        "target_clip_id",
        "target_layer_id",
        "expected_before_state",
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

    def create_script_layout_build_plan(
        self,
        build_plan: dict[str, Any],
        *,
        plan_name: str,
    ) -> dict[str, Any]:
        """Persist a script-driven BuildPlan without requiring a reference blueprint."""
        build_plan_code = self._next_build_plan_code()
        normalized_plan_name = str(plan_name or "剧本驱动 BuildPlan").strip()[:255]
        metadata = {key: value for key, value in build_plan.items() if key != "operations"}
        operations = [dict(operation) for operation in (build_plan.get("operations") or [])]
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_build_plans (
                        build_plan_code, blueprint_code, plan_name, target_app, executor,
                        status, strategy, description, details
                    )
                    VALUES (%s, %s, %s, 'maitu', 'browser_use', %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        build_plan_code,
                        None,
                        normalized_plan_name,
                        str(build_plan.get("status") or "draft"),
                        "script_driven_layout_v1",
                        "由直播剧本、素材需求、真实素材选择和布局计划生成。",
                        Jsonb(
                            {
                                "contract_version": "script_layout_build_plan_v1",
                                "script_layout_build_plan": metadata,
                            }
                        ),
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
                            operation.get("operation_name") or operation["operation_type"],
                            int(operation.get("sort_order") or 0),
                            operation.get("status") or "planned",
                            operation.get("scene_name"),
                            operation.get("layer_id") or operation.get("layer_name"),
                            operation.get("layer_type") or operation.get("layer_role"),
                            operation.get("required_category"),
                            Jsonb(operation.get("accepted_asset_types") or []),
                            operation.get("replacement_policy"),
                            operation.get("asset_code"),
                            operation.get("asset_title"),
                            operation.get("asset_display_code"),
                            operation.get("asset_local_file_code"),
                            operation.get("asset_original_filename"),
                            operation.get("asset_local_relative_path"),
                            operation.get("asset_browser_use_hint"),
                            operation.get("match_score"),
                            Jsonb(operation.get("match_reasons") or []),
                            operation.get("selection_source"),
                            operation.get("script_block_code"),
                            operation.get("script_text"),
                            operation.get("instruction") or "按剧本驱动 BuildPlan 执行并回读验证。",
                            Jsonb(
                                {
                                    "contract_version": "script_layout_operation_v1",
                                    "script_layout_operation": operation,
                                }
                            ),
                        ),
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {
            **build_plan,
            "build_plan_code": build_plan_code,
            "plan_name": normalized_plan_name,
            "browser_use_operations_url": (
                f"/api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations"
            ),
        }

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
        raw_plan_details = plan.get("details") if isinstance(plan.get("details"), dict) else {}
        namespaced_plan_details = raw_plan_details.get("script_layout_build_plan")
        plan_details = (
            namespaced_plan_details
            if raw_plan_details.get("contract_version") == "script_layout_build_plan_v1"
            and isinstance(namespaced_plan_details, dict)
            else raw_plan_details
        )
        response = {
            **plan_details,
            "build_plan_code": plan["build_plan_code"],
            "blueprint_code": plan["blueprint_code"],
            "reference_room_id": blueprint.get("reference_room_id") if blueprint else None,
            "reference_room_name": blueprint.get("reference_room_name") if blueprint else None,
            "target_live_room_id": (
                plan_details.get("target_live_room_id")
                or preflight_details.get("target_live_room_id")
            ),
            "executor": plan["executor"],
            "target_app": plan["target_app"],
            "source": plan_details.get("source"),
            "status": plan.get("status") or plan_details.get("status"),
            "build_mode": plan_details.get("build_mode"),
            "can_execute": plan_details.get("can_execute"),
            "manual_review_required": bool(plan_details.get("manual_review_required", False)),
            "blocked_reasons": list(plan_details.get("blocked_reasons") or []),
            "operations": operations,
        }
        response["checkpoint_source_fingerprint"] = self._script_layout_checkpoint_source_fingerprint(
            plan["build_plan_code"],
            plan_details,
            operations,
        )
        return response

    def create_live_room_build_plan_execution_result(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.get_live_room_build_plan_by_code(build_plan_code)
        if plan is None:
            return None
        plan_details = plan.get("details") if isinstance(plan.get("details"), dict) else {}
        if plan_details.get("contract_version") == "script_layout_build_plan_v1":
            raise BuildPlanCheckpointConflictError(
                "script-layout BuildPlans require the fenced checkpoint execution protocol"
            )

        execution_code = self._next_execution_code()
        operation_results = payload.get("operation_results", [])
        execution_details = {
            **(payload.get("details") or {}),
            "ready_for_go_live": bool(payload.get("ready_for_go_live", False)),
            "manual_review_required": bool(payload.get("manual_review_required", False)),
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_live_room_build_plan_executions (
                    execution_code, build_plan_code, blueprint_code, executor,
                    execution_status, mode, started_at, finished_at, failure_type,
                    retryable, retry_instruction, error_message, screenshot_asset_code,
                    dom_snapshot_asset_code, result_summary, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    Jsonb(execution_details),
                ),
            )
            execution = cursor.fetchone()

            for sort_order, operation in enumerate(operation_results):
                operation_details = {
                    **(operation.get("details") or {}),
                    **{
                        key: operation[key]
                        for key in ("scene_index", "clip_id", "layer_id", "layer_type", "asset_code")
                        if operation.get(key) is not None
                    },
                }
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
                        Jsonb(operation_details),
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

    def _lock_script_layout_execution(self, cursor: Any, build_plan_code: str, execution_code: str) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT *
            FROM maitu_live_room_build_plan_executions
            WHERE build_plan_code = %s AND execution_code = %s
                AND checkpoint_contract = 'script_layout_checkpoint_v1'
                AND mode = 'script_layout_draft' AND deleted_at IS NULL
            FOR UPDATE
            """,
            (build_plan_code, execution_code),
        )
        return cursor.fetchone()

    def _script_layout_operation_at_index(
        self,
        cursor: Any,
        build_plan_code: str,
        operation_index: int,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT *
            FROM maitu_live_room_build_plan_operations
            WHERE build_plan_code = %s
            ORDER BY sort_order ASC, created_at ASC
            OFFSET %s LIMIT 1
            """,
            (build_plan_code, operation_index),
        )
        row = cursor.fetchone()
        return self._normalize_live_room_build_plan_operation(row) if row is not None else None

    @staticmethod
    def _script_layout_checkpoint_source_fingerprint(
        build_plan_code: str,
        plan_details: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> str:
        durable_source = {
            "build_plan_code": build_plan_code,
            "source": plan_details.get("source"),
            "status": plan_details.get("status"),
            "target_live_room_id": plan_details.get("target_live_room_id"),
            "build_mode": plan_details.get("build_mode"),
            "can_execute": plan_details.get("can_execute"),
            "manual_review_required": bool(plan_details.get("manual_review_required", False)),
            "blocked_reasons": list(plan_details.get("blocked_reasons") or []),
            "operations": operations,
        }
        encoded = json.dumps(
            durable_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _script_layout_effect_class(cls, operation_type: str) -> str:
        if operation_type in cls.SCRIPT_LAYOUT_MUTATING_OPERATIONS:
            return "mutating"
        if operation_type in cls.SCRIPT_LAYOUT_READ_ONLY_OPERATIONS:
            return "read_only"
        if operation_type in cls.SCRIPT_LAYOUT_MANUAL_NOOP_OPERATIONS:
            return "manual_noop"
        raise BuildPlanCheckpointConflictError(f"unsupported script-layout operation type: {operation_type}")

    @staticmethod
    def _require_readback_attestation(attested_payload: dict[str, Any], evidence: dict[str, Any]) -> None:
        configured = settings.maitu_readback_attestation_key
        key = configured.get_secret_value() if configured is not None else ""
        supplied = evidence.get("readback_attestation")
        if (
            len(key) < 32
            or evidence.get("readback_attestation_algorithm") != "hmac-sha256-v1"
            or not isinstance(supplied, str)
            or len(supplied) != 64
        ):
            raise BuildPlanCheckpointConflictError("authoritative readback attestation is missing or unavailable")
        encoded = json.dumps(
            attested_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = hmac.new(key.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise BuildPlanCheckpointConflictError("authoritative readback attestation is invalid")

    @classmethod
    def _validate_completion_readback_attestation(
        cls,
        *,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        checkpoint: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        evidence = payload.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        unsigned_evidence = {
            key: value
            for key, value in evidence.items()
            if key not in {"readback_attestation", "readback_attestation_algorithm"}
        }
        cls._require_readback_attestation(
            {
                "build_plan_code": build_plan_code,
                "execution_code": execution_code,
                "operation_index": operation_index,
                "operation_fingerprint": checkpoint.get("operation_fingerprint"),
                "attempt_id": str(payload.get("attempt_id")),
                "lease_token": str(payload.get("lease_token")),
                "lease_version": payload.get("lease_version"),
                "completion_id": str(payload.get("completion_id")),
                "evidence": unsigned_evidence,
            },
            evidence,
        )

    @classmethod
    def _validate_reconciliation_readback_attestation(
        cls,
        *,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        checkpoint: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        evidence = payload.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        unsigned_evidence = {
            key: value
            for key, value in evidence.items()
            if key not in {"readback_attestation", "readback_attestation_algorithm"}
        }
        cls._require_readback_attestation(
            {
                "build_plan_code": build_plan_code,
                "execution_code": execution_code,
                "operation_index": operation_index,
                "operation_fingerprint": checkpoint.get("operation_fingerprint"),
                "reconciliation_id": str(payload.get("reconciliation_id")),
                "reconciled_attempt_id": str(payload.get("reconciled_attempt_id")),
                "resolution": payload.get("resolution"),
                "evidence": unsigned_evidence,
            },
            evidence,
        )

    @classmethod
    def _validate_script_layout_terminal_evidence(
        cls,
        checkpoint: dict[str, Any],
        evidence: dict[str, Any],
        operation_result: dict[str, Any],
    ) -> None:
        effect_class = checkpoint.get("effect_class")
        operation_type = str(checkpoint.get("operation_type") or "")
        intent = checkpoint.get("intent_snapshot")
        intent = intent if isinstance(intent, dict) else {}
        if evidence.get("verified") is not True:
            raise BuildPlanCheckpointConflictError("checkpoint evidence must be an authoritative verified readback")
        expected_status = "skipped" if effect_class == "manual_noop" else "completed"
        if operation_result.get("status") != expected_status or operation_result.get("operation_type") != operation_type:
            raise BuildPlanCheckpointConflictError("operation result terminal status or type differs from frozen policy")
        if effect_class == "mutating" and evidence.get("verification_source") != "working_room_readback":
            raise BuildPlanCheckpointConflictError("mutating completion requires trusted working-room readback")
        if operation_type == "verify_scene" and evidence.get("verification_source") != "working_room_readback":
            raise BuildPlanCheckpointConflictError("scene verification requires trusted working-room readback")

        def require_equal(field_name: str, expected: Any) -> None:
            if evidence.get(field_name) != expected:
                raise BuildPlanCheckpointConflictError(
                    f"checkpoint evidence {field_name} differs from frozen operation intent"
                )

        if operation_type == "preflight_content_build_plan":
            if evidence.get("verification_source") != "working_room_readback":
                raise BuildPlanCheckpointConflictError("preflight requires trusted working-room readback")
            require_equal("environment", "working")
            require_equal("not_live", True)
            default_clip_id = evidence.get("default_clip_id")
            if not isinstance(default_clip_id, int) or isinstance(default_clip_id, bool) or default_clip_id <= 0:
                raise BuildPlanCheckpointConflictError("preflight requires an authoritative default_clip_id")
            if evidence.get("clip_id") != default_clip_id:
                raise BuildPlanCheckpointConflictError("preflight clip identity differs from default clip readback")
        elif operation_type in {"fill_default_scene", "create_scene"}:
            if not isinstance(evidence.get("clip_id"), int) or isinstance(evidence.get("clip_id"), bool):
                raise BuildPlanCheckpointConflictError("scene completion requires authoritative clip_id")
            require_equal("scene_index", intent.get("scene_index"))
            require_equal("scene_name", intent.get("scene_name"))
        elif operation_type in {"insert_asset_layer", "position_asset_layer"}:
            for identity_field in ("clip_id", "material_id"):
                if not isinstance(evidence.get(identity_field), int) or isinstance(evidence.get(identity_field), bool):
                    raise BuildPlanCheckpointConflictError(
                        f"{operation_type} completion requires authoritative {identity_field}"
                    )
            for field_name in ("scene_index", "scene_name", "asset_code", "layer_id", "layer_type"):
                require_equal(field_name, intent.get(field_name))
            if "sound_enabled" in intent:
                require_equal("sound_enabled", intent.get("sound_enabled") is True)
            expected_source_type = (
                "video" if intent.get("source_material_type") == "decorative_video" else intent.get("source_material_type")
            )
            require_equal("source_material_type", expected_source_type)
            if expected_source_type == "digital_human":
                require_equal("speaker_id", intent.get("speaker_id"))
                require_equal("digital_human_image_id", intent.get("digital_human_image_id"))
                if evidence.get("source_material_id") is not None:
                    raise BuildPlanCheckpointConflictError("digital-human evidence must not invent a source material id")
            else:
                source_material_id = evidence.get("source_material_id")
                if not isinstance(source_material_id, int) or isinstance(source_material_id, bool):
                    raise BuildPlanCheckpointConflictError(
                        f"{operation_type} completion requires authoritative source_material_id"
                    )
                require_equal("source_material_id", intent.get("material_id") or intent.get("maitu_material_id"))
                require_equal("source_material_url", intent.get("source_material_url"))
            if operation_type == "position_asset_layer":
                for evidence_field, intent_field in (
                    ("left", "x"),
                    ("top", "y"),
                    ("width", "width"),
                    ("height", "height"),
                    ("z_index", "z_index"),
                ):
                    require_equal(evidence_field, intent.get(intent_field))
        elif operation_type == "write_script":
            for identity_field in ("clip_id", "text_material_id"):
                if not isinstance(evidence.get(identity_field), int) or isinstance(evidence.get(identity_field), bool):
                    raise BuildPlanCheckpointConflictError(
                        f"script completion requires authoritative {identity_field}"
                    )
            require_equal("scene_index", intent.get("scene_index"))
            require_equal("scene_name", intent.get("scene_name"))
            expected_hash = hashlib.sha256(str(intent.get("script_text") or "").encode("utf-8")).hexdigest()
            require_equal("script_sha256", expected_hash)
        elif operation_type == "verify_scene":
            for identity_field in ("clip_id", "text_material_id"):
                if not isinstance(evidence.get(identity_field), int) or isinstance(evidence.get(identity_field), bool):
                    raise BuildPlanCheckpointConflictError(
                        f"scene verification requires authoritative {identity_field}"
                    )
            require_equal("scene_index", intent.get("scene_index"))
            require_equal("scene_name", intent.get("scene_name"))
            for field_name in ("expected_visual_count", "expected_text_count", "expected_script_sha256"):
                require_equal(field_name, intent.get(field_name))
            require_equal("verified_script_text", intent.get("expected_script_text"))
            verified_layers = evidence.get("verified_layers")
            expected_layers = intent.get("expected_layers")
            if not isinstance(verified_layers, list) or not isinstance(expected_layers, list):
                raise BuildPlanCheckpointConflictError("scene verification requires exact verified layer evidence")
            normalized_layers: list[dict[str, Any]] = []
            material_ids: set[int] = set()
            for layer in verified_layers:
                if not isinstance(layer, dict):
                    raise BuildPlanCheckpointConflictError("scene verification layer evidence must be objects")
                material_id = layer.get("material_id")
                if not isinstance(material_id, int) or isinstance(material_id, bool) or material_id in material_ids:
                    raise BuildPlanCheckpointConflictError("scene verification requires unique material ids")
                material_ids.add(material_id)
                normalized_layers.append({key: value for key, value in layer.items() if key != "material_id"})
            if normalized_layers != expected_layers:
                raise BuildPlanCheckpointConflictError("scene verification layers differ from frozen expected state")

    @staticmethod
    def _validate_script_layout_dynamic_lineage(
        cursor: Any,
        execution_code: str,
        checkpoint: dict[str, Any],
        evidence: dict[str, Any],
    ) -> None:
        operation_type = checkpoint.get("operation_type")
        if operation_type in {
            "preflight_content_build_plan",
            "verify_draft_persisted",
            "placeholder_required",
            "save_draft",
        }:
            return
        intent = checkpoint.get("intent_snapshot")
        intent = intent if isinstance(intent, dict) else {}
        cursor.execute(
            """
            SELECT operation_type, intent_snapshot, completion_evidence
            FROM maitu_live_room_build_plan_operation_results
            WHERE execution_code = %s
              AND operation_index < %s
              AND checkpoint_state IN ('completed', 'observed')
            ORDER BY operation_index ASC
            """,
            (execution_code, checkpoint["operation_index"]),
        )
        dependencies = cursor.fetchall()
        preflight = next(
            (item for item in dependencies if item.get("operation_type") == "preflight_content_build_plan"),
            None,
        )
        if operation_type == "fill_default_scene":
            preflight_evidence = preflight.get("completion_evidence") if isinstance(preflight, dict) else None
            if not isinstance(preflight_evidence, dict) or evidence.get("clip_id") != preflight_evidence.get(
                "default_clip_id"
            ):
                raise BuildPlanCheckpointConflictError("default-scene fill does not target the preflight default clip")
            return

        scene_index = intent.get("scene_index")
        scene_name = intent.get("scene_name")
        scene_dependencies: list[dict[str, Any]] = []
        for item in dependencies:
            if item.get("operation_type") not in {"fill_default_scene", "create_scene"}:
                continue
            candidate_intent = item.get("intent_snapshot")
            if not isinstance(candidate_intent, dict):
                continue
            if candidate_intent.get("scene_index") == scene_index and candidate_intent.get("scene_name") == scene_name:
                scene_dependencies.append(item)
        if operation_type == "create_scene":
            used_clip_ids = {
                candidate_evidence.get("clip_id")
                for item in dependencies
                if isinstance((candidate_evidence := item.get("completion_evidence")), dict)
            }
            if evidence.get("clip_id") in used_clip_ids:
                raise BuildPlanCheckpointConflictError("created scene reused an existing dynamic clip id")
            return
        if len(scene_dependencies) != 1:
            raise BuildPlanCheckpointConflictError("operation has no unique completed scene dependency")
        scene_evidence = scene_dependencies[0].get("completion_evidence")
        if not isinstance(scene_evidence, dict) or evidence.get("clip_id") != scene_evidence.get("clip_id"):
            raise BuildPlanCheckpointConflictError("operation clip id differs from completed scene dependency")

        inserts: list[dict[str, Any]] = []
        for candidate in dependencies:
            if candidate.get("operation_type") != "insert_asset_layer":
                continue
            candidate_intent = candidate.get("intent_snapshot")
            if not isinstance(candidate_intent, dict) or candidate_intent.get("scene_index") != scene_index:
                continue
            inserts.append(candidate)
        if operation_type == "position_asset_layer":
            matching = [
                candidate
                for candidate in inserts
                if isinstance(candidate.get("intent_snapshot"), dict)
                and all(
                    candidate["intent_snapshot"].get(field_name) == intent.get(field_name)
                    for field_name in ("asset_code", "layer_id", "layer_type")
                )
            ]
            if len(matching) != 1:
                raise BuildPlanCheckpointConflictError("position completion has no unique completed insert dependency")
            inserted_evidence = matching[0].get("completion_evidence")
            inserted_evidence = inserted_evidence if isinstance(inserted_evidence, dict) else {}
            for field_name in (
                "clip_id",
                "material_id",
                "source_material_id",
                "source_material_type",
                "source_material_url",
                "speaker_id",
                "digital_human_image_id",
            ):
                if evidence.get(field_name) != inserted_evidence.get(field_name):
                    raise BuildPlanCheckpointConflictError(
                        f"position completion {field_name} differs from completed insert dependency"
                    )
        if operation_type == "verify_scene":
            verified_layers = evidence.get("verified_layers")
            if not isinstance(verified_layers, list) or len(verified_layers) != len(inserts):
                raise BuildPlanCheckpointConflictError("scene verification dynamic material set is incomplete")
            for verified_layer in verified_layers:
                if not isinstance(verified_layer, dict):
                    raise BuildPlanCheckpointConflictError("scene verification dynamic layer must be an object")
                matching = [
                    candidate
                    for candidate in inserts
                    if isinstance(candidate.get("intent_snapshot"), dict)
                    and candidate["intent_snapshot"].get("layer_id") == verified_layer.get("layer_id")
                    and candidate["intent_snapshot"].get("asset_code") == verified_layer.get("asset_code")
                ]
                inserted_evidence = matching[0].get("completion_evidence") if len(matching) == 1 else None
                if not isinstance(inserted_evidence, dict) or verified_layer.get("material_id") != inserted_evidence.get(
                    "material_id"
                ):
                    raise BuildPlanCheckpointConflictError(
                        "scene verification material id differs from completed insert dependency"
                    )
            writes = [
                candidate
                for candidate in dependencies
                if candidate.get("operation_type") == "write_script"
                and isinstance(candidate.get("intent_snapshot"), dict)
                and candidate["intent_snapshot"].get("scene_index") == scene_index
                and candidate["intent_snapshot"].get("scene_name") == scene_name
            ]
            write_evidence = writes[0].get("completion_evidence") if len(writes) == 1 else None
            if not isinstance(write_evidence, dict) or evidence.get("text_material_id") != write_evidence.get(
                "text_material_id"
            ):
                raise BuildPlanCheckpointConflictError(
                    "scene verification text material id differs from completed script dependency"
                )

    @classmethod
    def _canonical_script_layout_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise BuildPlanCheckpointConflictError("script-layout intent contains a non-finite number")
            return value
        if isinstance(value, list):
            return [cls._canonical_script_layout_value(item) for item in value]
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise BuildPlanCheckpointConflictError("script-layout intent contains a non-string key")
                normalized[key] = cls._canonical_script_layout_value(item)
            return normalized
        raise BuildPlanCheckpointConflictError("script-layout intent contains a non-JSON value")

    @classmethod
    def _script_layout_fingerprint(cls, payload: dict[str, Any]) -> str:
        canonical = cls._canonical_script_layout_value(payload)
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _freeze_script_layout_manifest(
        self,
        *,
        cursor: Any,
        build_plan_code: str,
        checkpoint_contract: str,
        source_plan_fingerprint: str,
        target_live_room_id: str,
        source_operations: list[dict[str, Any]],
        requested_operations: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str, str]:
        if not source_operations:
            raise BuildPlanCheckpointConflictError("checkpoint manifest cannot be empty")
        first_operation = source_operations[0]
        if (
            first_operation.get("operation_type") != "preflight_content_build_plan"
            or first_operation.get("status") != "ready"
            or str(first_operation.get("target_live_room_id") or target_live_room_id) != target_live_room_id
        ):
            raise BuildPlanCheckpointConflictError("checkpoint manifest must start with target-bound ready preflight")
        if len(requested_operations) != len(source_operations):
            raise BuildPlanCheckpointConflictError("checkpoint manifest must cover every persisted operation")
        manifest: list[dict[str, Any]] = []
        for operation_index, source_operation in enumerate(source_operations):
            requested = requested_operations[operation_index]
            if int(requested.get("operation_index", -1)) != operation_index:
                raise BuildPlanCheckpointConflictError("checkpoint manifest operation indexes are not exact")
            intent = requested.get("intent")
            if not isinstance(intent, dict):
                raise BuildPlanCheckpointConflictError("checkpoint manifest intent must be an object")
            operation_type = str(source_operation.get("operation_type") or "")
            if str(intent.get("operation_type") or "") != operation_type:
                raise BuildPlanCheckpointConflictError("resolved operation type differs from persisted BuildPlan")
            durable_source = {
                key: self._canonical_script_layout_value(value)
                for key, value in source_operation.items()
                if key not in self.SCRIPT_LAYOUT_RESOLVER_MUTABLE_FIELDS
            }
            durable_intent = {
                key: self._canonical_script_layout_value(value)
                for key, value in intent.items()
                if key not in self.SCRIPT_LAYOUT_RESOLVER_MUTABLE_FIELDS
            }
            if durable_intent != durable_source:
                raise BuildPlanCheckpointConflictError("resolved operation changed non-material BuildPlan intent")
            canonical_intent = dict(durable_source)
            if operation_type in {"insert_asset_layer", "position_asset_layer"}:
                asset_code = str(source_operation.get("asset_code") or "").strip()
                if not asset_code:
                    if str(source_operation.get("layer_type") or "") != "digital_human":
                        raise BuildPlanCheckpointConflictError(
                            "material operation is missing persisted asset_code"
                        )
                    if operation_type == "insert_asset_layer":
                        native_source = source_operation
                    else:
                        native_source = next(
                            (
                                item["intent"]
                                for item in reversed(manifest)
                                if item["intent"].get("operation_type")
                                == "insert_asset_layer"
                                and item["intent"].get("scene_index")
                                == source_operation.get("scene_index")
                                and item["intent"].get("layer_id")
                                == source_operation.get("layer_id")
                                and not item["intent"].get("asset_code")
                            ),
                            None,
                        )
                    if not isinstance(native_source, dict):
                        raise BuildPlanCheckpointConflictError(
                            "native digital-human position has no matching insert intent"
                        )
                    raw_source_material_id = (
                        native_source.get("maitu_source_material_id")
                        or native_source.get("material_id")
                        or native_source.get("maitu_material_id")
                    )
                    raw_speaker_id = native_source.get("speaker_id")
                    raw_digital_human_image_id = native_source.get(
                        "digital_human_image_id"
                    )
                    try:
                        if any(
                            isinstance(value, bool)
                            for value in (
                                raw_source_material_id,
                                raw_speaker_id,
                                raw_digital_human_image_id,
                            )
                        ):
                            raise ValueError("boolean identity")
                        source_material_id = int(raw_source_material_id)
                        speaker_id = int(raw_speaker_id)
                        digital_human_image_id = int(
                            raw_digital_human_image_id
                        )
                    except (TypeError, ValueError) as exc:
                        raise BuildPlanCheckpointConflictError(
                            "native digital-human operation has incomplete persisted identity"
                        ) from exc
                    if (
                        native_source.get("source_material_type") != "digital_human"
                        or source_material_id < 1
                        or speaker_id < 1
                        or digital_human_image_id < 1
                    ):
                        raise BuildPlanCheckpointConflictError(
                            "native digital-human operation has incomplete persisted identity"
                        )
                    authoritative_binding = {
                        "maitu_material_id": None,
                        "maitu_source_material_id": source_material_id,
                        "material_id": None,
                        "source_material_type": "digital_human",
                        "source_material_url": native_source.get(
                            "source_material_url"
                        ),
                        "source_cover_url": native_source.get("source_cover_url"),
                        "speaker_id": speaker_id,
                        "digital_human_image_id": digital_human_image_id,
                        "material_resolution_status": "native_maitu_digital_human_binding",
                    }
                    for field_name, expected_value in authoritative_binding.items():
                        if intent.get(field_name) != expected_value:
                            raise BuildPlanCheckpointConflictError(
                                f"native digital-human {field_name} differs from persisted binding"
                            )
                    canonical_intent.update(authoritative_binding)
                    canonical_intent = self._canonical_script_layout_value(
                        canonical_intent
                    )
                    effect_class = self._script_layout_effect_class(operation_type)
                    operation_fingerprint = self._script_layout_fingerprint(
                        {
                            "checkpoint_contract": checkpoint_contract,
                            "source_plan_fingerprint": source_plan_fingerprint,
                            "target_live_room_id": target_live_room_id,
                            "operation_index": operation_index,
                            "effect_class": effect_class,
                            "intent": canonical_intent,
                        }
                    )
                    manifest.append(
                        {
                            "operation_index": operation_index,
                            "operation_type": operation_type,
                            "effect_class": effect_class,
                            "intent": canonical_intent,
                            "operation_fingerprint": operation_fingerprint,
                        }
                    )
                    continue
                cursor.execute(
                    """
                    SELECT asset_code, maitu_material_id, maitu_source_material_id,
                           source_material_type,
                           source_material_url, source_cover_url, speaker_id,
                           digital_human_image_id, maitu_binding_verification_source,
                           maitu_binding_verified_at, maitu_binding_scope,
                           maitu_binding_inventory_fingerprint,
                           maitu_binding_readback_nonce, maitu_binding_attestation,
                           maitu_binding_evidence
                    FROM assets
                    WHERE asset_code = %s AND deleted_at IS NULL
                    FOR SHARE
                    """,
                    (asset_code,),
                )
                asset = cursor.fetchone()
                if asset is None:
                    raise BuildPlanCheckpointConflictError("resolved operation asset is absent from AssetGraph")
                verified_at = asset.get("maitu_binding_verified_at")
                verification_source = asset.get("maitu_binding_verification_source")
                receipt_evidence = (
                    asset.get("maitu_binding_evidence")
                    if isinstance(asset.get("maitu_binding_evidence"), dict)
                    else {}
                )
                worker_readback_test_job = (
                    verification_source == "worker_maitu_inventory_readback"
                    and receipt_evidence.get("source")
                    == "active_functional_worker_inventory_readback"
                    and receipt_evidence.get("build_plan_code") == build_plan_code
                    and receipt_evidence.get("source_plan_fingerprint")
                    == source_plan_fingerprint
                    and self._active_functional_worker_readback_test_job(
                        cursor,
                        execution_job_code=str(
                            receipt_evidence.get("execution_job_code") or ""
                        ),
                        build_plan_code=build_plan_code,
                        target_live_room_id=target_live_room_id,
                    )
                )
                if (
                    verification_source
                    not in (
                        {"backend_maitu_inventory_readback", "worker_maitu_inventory_readback"}
                        if worker_readback_test_job
                        else {"backend_maitu_inventory_readback"}
                    )
                    or asset.get("maitu_binding_scope") != "assetgraph_script_layout_material_binding_v2"
                    or not isinstance(verified_at, datetime)
                ):
                    raise BuildPlanCheckpointConflictError(
                        "resolved operation requires an authenticated, authoritative material binding receipt"
                    )
                observed_at = verified_at if verified_at.tzinfo is not None else verified_at.replace(tzinfo=UTC)
                age = datetime.now(UTC) - observed_at.astimezone(UTC)
                if age < timedelta(minutes=-1) or age > timedelta(minutes=15):
                    raise BuildPlanCheckpointConflictError(
                        "resolved operation requires a fresh authoritative material binding receipt"
                    )
                material_id = asset.get("maitu_material_id")
                source_material_id = asset.get("maitu_source_material_id")
                source_type = asset.get("source_material_type")
                source_url = asset.get("source_material_url")
                speaker_id = asset.get("speaker_id")
                digital_human_image_id = asset.get("digital_human_image_id")
                inventory_fingerprint = asset.get("maitu_binding_inventory_fingerprint")
                readback_nonce = asset.get("maitu_binding_readback_nonce")
                binding_attestation = asset.get("maitu_binding_attestation")
                if not isinstance(inventory_fingerprint, str) or len(inventory_fingerprint) != 64:
                    raise BuildPlanCheckpointConflictError(
                        "resolved operation material binding lacks an inventory receipt"
                    )
                binding_identity = {
                    "maitu_material_id": material_id,
                    "maitu_source_material_id": source_material_id,
                    "source_material_type": source_type,
                    "source_material_url": source_url,
                    "source_cover_url": asset.get("source_cover_url"),
                    "speaker_id": speaker_id,
                    "digital_human_image_id": digital_human_image_id,
                }
                if verification_source == "worker_maitu_inventory_readback" and (
                    receipt_evidence.get("inventory_item_fingerprint")
                    != inventory_fingerprint
                    or receipt_evidence.get("binding_identity_fingerprint")
                    != self._script_layout_fingerprint(
                        canonical_maitu_binding_identity(asset_code, binding_identity)
                    )
                ):
                    raise BuildPlanCheckpointConflictError(
                        "resolved operation worker receipt does not match the frozen material identity"
                    )
                if verification_source == "backend_maitu_inventory_readback":
                    if readback_nonce is None:
                        raise BuildPlanCheckpointConflictError(
                            "resolved operation material binding lacks a signed inventory receipt"
                        )
                    self._require_readback_attestation(
                        {
                            "asset_code": asset_code,
                            "binding": binding_identity,
                            "inventory_snapshot_sha256": inventory_fingerprint,
                            "readback_nonce": str(readback_nonce),
                        },
                        {
                            "readback_attestation_algorithm": "hmac-sha256-v1",
                            "readback_attestation": binding_attestation,
                        },
                    )
                regular_binding = (
                    isinstance(material_id, int)
                    and not isinstance(material_id, bool)
                    and material_id > 0
                    and source_material_id == material_id
                    and source_type in {"image", "video", "decorative_video"}
                    and bool(source_url)
                )
                digital_human_binding = (
                    source_type == "digital_human"
                    and material_id is None
                    and isinstance(source_material_id, int)
                    and not isinstance(source_material_id, bool)
                    and source_material_id > 0
                    and bool(speaker_id)
                    and bool(digital_human_image_id)
                )
                if not regular_binding and not digital_human_binding:
                    raise BuildPlanCheckpointConflictError(
                        "resolved operation requires a complete backend-authoritative material binding"
                    )
                authoritative_binding = {
                    "maitu_material_id": material_id,
                    "maitu_source_material_id": source_material_id,
                    "material_id": material_id,
                    "source_material_type": source_type,
                    "source_material_url": source_url,
                    "source_cover_url": asset.get("source_cover_url"),
                    "speaker_id": speaker_id,
                    "digital_human_image_id": digital_human_image_id,
                    "material_resolution_status": (
                        "worker_verified_test_binding"
                        if verification_source == "worker_maitu_inventory_readback"
                        else "backend_verified_asset_binding"
                    ),
                }
                for field_name, expected_value in authoritative_binding.items():
                    supplied_value = intent.get(field_name)
                    if field_name == "material_resolution_status":
                        continue
                    if supplied_value != expected_value:
                        raise BuildPlanCheckpointConflictError(
                            f"resolved operation {field_name} differs from backend asset binding"
                        )
                canonical_intent.update(authoritative_binding)
            if operation_type == "verify_scene":
                scene_index = canonical_intent.get("scene_index")
                prior_scene_intents = [
                    item["intent"]
                    for item in manifest
                    if item["intent"].get("scene_index") == scene_index
                ]
                expected_layers: list[dict[str, Any]] = []
                for prior_intent in prior_scene_intents:
                    if prior_intent.get("operation_type") != "insert_asset_layer":
                        continue
                    matching_position = next(
                        (
                            candidate
                            for candidate in prior_scene_intents
                            if candidate.get("operation_type") == "position_asset_layer"
                            and candidate.get("layer_id") == prior_intent.get("layer_id")
                            and candidate.get("asset_code") == prior_intent.get("asset_code")
                        ),
                        prior_intent,
                    )
                    source_type = prior_intent.get("source_material_type")
                    expected_layers.append(
                        {
                            "asset_code": prior_intent.get("asset_code"),
                            "layer_id": prior_intent.get("layer_id"),
                            "layer_type": prior_intent.get("layer_type"),
                            "source_material_id": prior_intent.get("maitu_source_material_id")
                            or prior_intent.get("material_id")
                            or prior_intent.get("maitu_material_id"),
                            "source_material_type": "video" if source_type == "decorative_video" else source_type,
                            "source_material_url": prior_intent.get("source_material_url"),
                            "speaker_id": prior_intent.get("speaker_id"),
                            "digital_human_image_id": prior_intent.get("digital_human_image_id"),
                            "left": matching_position.get("x"),
                            "top": matching_position.get("y"),
                            "width": matching_position.get("width"),
                            "height": matching_position.get("height"),
                            "z_index": matching_position.get("z_index"),
                            "sound_enabled": prior_intent.get("sound_enabled") is True,
                        }
                    )
                script_intent = next(
                    (
                        item
                        for item in reversed(prior_scene_intents)
                        if item.get("operation_type") == "write_script"
                    ),
                    None,
                )
                expected_script_text = str((script_intent or {}).get("script_text") or "")
                canonical_intent.update(
                    {
                        "expected_layers": expected_layers,
                        "expected_visual_count": len(expected_layers),
                        "expected_text_count": 1,
                        "expected_script_text": expected_script_text,
                        "expected_script_sha256": hashlib.sha256(
                            expected_script_text.encode("utf-8")
                        ).hexdigest(),
                    }
                )
            canonical_intent = self._canonical_script_layout_value(canonical_intent)
            effect_class = self._script_layout_effect_class(operation_type)
            operation_fingerprint = self._script_layout_fingerprint(
                {
                    "checkpoint_contract": checkpoint_contract,
                    "source_plan_fingerprint": source_plan_fingerprint,
                    "target_live_room_id": target_live_room_id,
                    "operation_index": operation_index,
                    "effect_class": effect_class,
                    "intent": canonical_intent,
                }
            )
            manifest.append(
                {
                    "operation_index": operation_index,
                    "operation_type": operation_type,
                    "effect_class": effect_class,
                    "intent": canonical_intent,
                    "operation_fingerprint": operation_fingerprint,
                }
            )
        manifest_fingerprint = self._script_layout_fingerprint(
            {
                "checkpoint_contract": checkpoint_contract,
                "operations": [item["operation_fingerprint"] for item in manifest],
            }
        )
        plan_fingerprint = self._script_layout_fingerprint(
            {
                "checkpoint_contract": checkpoint_contract,
                "source_plan_fingerprint": source_plan_fingerprint,
                "target_live_room_id": target_live_room_id,
                "manifest_fingerprint": manifest_fingerprint,
            }
        )
        return manifest, manifest_fingerprint, plan_fingerprint

    @staticmethod
    def _lease_is_active(execution: dict[str, Any], now: datetime) -> bool:
        expires_at = execution.get("lease_expires_at")
        return execution.get("lease_token") is not None and isinstance(expires_at, datetime) and expires_at > now

    @staticmethod
    def _require_script_layout_lease(execution: dict[str, Any], payload: dict[str, Any], now: datetime) -> None:
        if not MaituMaterialSlotRepository._lease_is_active(execution, now):
            raise BuildPlanCheckpointConflictError("script-layout execution lease is not active")
        if (
            str(execution.get("lease_token")) != str(payload.get("lease_token"))
            or int(execution.get("lease_version") or 0) != int(payload.get("lease_version") or 0)
            or str(execution.get("run_attempt_id")) != str(payload.get("attempt_id") or payload.get("run_attempt_id"))
            or str(execution.get("lease_owner")) != str(payload.get("lease_owner"))
        ):
            raise BuildPlanCheckpointConflictError("script-layout execution lease fence does not match")

    def start_script_layout_execution(
        self,
        build_plan_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(seconds=self.SCRIPT_LAYOUT_LEASE_SECONDS)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_live_room_build_plans
                WHERE build_plan_code = %s AND deleted_at IS NULL
                FOR UPDATE
                """,
                (build_plan_code,),
            )
            plan = cursor.fetchone()
            if plan is None:
                self.connection.commit()
                return None
            try:
                self._require_functional_live_room_execution_request(cursor, build_plan_code)
            except BuildPlanCheckpointConflictError:
                self.connection.rollback()
                raise
            raw_details = plan.get("details") if isinstance(plan.get("details"), dict) else {}
            namespaced = raw_details.get("script_layout_build_plan")
            if raw_details.get("contract_version") != "script_layout_build_plan_v1" or not isinstance(namespaced, dict):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("checkpoint execution requires a script-layout BuildPlan")
            if (
                namespaced.get("status") != "ready"
                or namespaced.get("can_execute") is not True
                or namespaced.get("manual_review_required") is True
                or list(namespaced.get("blocked_reasons") or [])
            ):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("persisted script-layout BuildPlan is not executable")
            authoritative_target = str(namespaced.get("target_live_room_id") or "").strip()
            if authoritative_target != payload["target_live_room_id"]:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("target live room differs from persisted BuildPlan intent")
            source_operations = self._fetch_live_room_build_plan_operations(build_plan_code)
            expected_source_fingerprint = self._script_layout_checkpoint_source_fingerprint(
                build_plan_code,
                namespaced,
                source_operations,
            )
            if payload["source_plan_fingerprint"] != expected_source_fingerprint:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("source BuildPlan fingerprint differs from persisted intent")
            manifest, manifest_fingerprint, plan_fingerprint = self._freeze_script_layout_manifest(
                cursor=cursor,
                build_plan_code=build_plan_code,
                checkpoint_contract=payload["checkpoint_contract"],
                source_plan_fingerprint=expected_source_fingerprint,
                target_live_room_id=payload["target_live_room_id"],
                source_operations=source_operations,
                requested_operations=list(payload["operations"]),
            )
            cursor.execute(
                """
                SELECT * FROM maitu_live_room_build_plan_executions
                WHERE build_plan_code = %s AND checkpoint_contract = %s AND deleted_at IS NULL
                FOR UPDATE
                """,
                (build_plan_code, payload["checkpoint_contract"]),
            )
            execution = cursor.fetchone()
            if execution is not None:
                if (
                    execution.get("manifest_fingerprint") != manifest_fingerprint
                    or execution.get("plan_fingerprint") != plan_fingerprint
                    or int(execution.get("expected_operation_count") or -1) != len(manifest)
                ):
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("checkpoint execution manifest differs from frozen intent")
                if execution.get("finalized_at") is not None:
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("finalized checkpoint execution cannot be reopened")
                if self._lease_is_active(execution, now):
                    same_request = (
                        str(execution.get("start_request_id")) == str(payload["start_request_id"])
                        and str(execution.get("run_attempt_id")) == str(payload["run_attempt_id"])
                        and str(execution.get("lease_owner")) == str(payload["lease_owner"])
                    )
                    if not same_request:
                        self.connection.rollback()
                        raise BuildPlanCheckpointConflictError("script-layout execution already has an active lease")
                    self.connection.commit()
                    return self.get_live_room_build_plan_execution_result_by_code(build_plan_code, execution["execution_code"])
                previous_expiry = execution.get("lease_expires_at")
                reconcile_not_before = execution.get("lease_reconcile_not_before")
                if isinstance(previous_expiry, datetime):
                    fenced_until = previous_expiry + timedelta(seconds=self.SCRIPT_LAYOUT_RECONCILE_GRACE_SECONDS)
                    reconcile_not_before = max(reconcile_not_before, fenced_until) if isinstance(reconcile_not_before, datetime) else fenced_until
                lease_version = int(execution.get("lease_version") or 0) + 1
                lease_token = uuid4()
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_executions
                    SET start_request_id = %s, run_attempt_id = %s, lease_owner = %s,
                        lease_token = %s, lease_version = %s, lease_acquired_at = %s,
                        lease_expires_at = %s, lease_reconcile_not_before = %s,
                        execution_status = 'in_progress', finished_at = NULL, updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        payload["start_request_id"], payload["run_attempt_id"], payload["lease_owner"],
                        lease_token, lease_version, now, lease_expires_at,
                        reconcile_not_before, execution["id"],
                    ),
                )
                execution_code = execution["execution_code"]
            else:
                execution_code = self._next_execution_code()
                execution_attempt_id = uuid4()
                lease_token = uuid4()
                execution_details = {
                    "target_live_room_id": payload["target_live_room_id"],
                    "source_plan_fingerprint": expected_source_fingerprint,
                    "ready_for_go_live": False,
                    "manual_review_required": False,
                }
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_build_plan_executions (
                        execution_code, build_plan_code, blueprint_code, executor,
                        execution_status, mode, started_at, retryable, details,
                        execution_attempt_id, start_request_id, run_attempt_id,
                        plan_fingerprint, manifest_fingerprint, expected_operation_count,
                        checkpoint_contract, lease_owner, lease_token, lease_version,
                        lease_acquired_at, lease_expires_at
                    ) VALUES (
                        %s, %s, %s, 'browser_use', 'in_progress', %s, %s, false, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        execution_code, build_plan_code, plan.get("blueprint_code"), payload["mode"], now,
                        Jsonb(execution_details), execution_attempt_id, payload["start_request_id"],
                        payload["run_attempt_id"], plan_fingerprint, manifest_fingerprint, len(manifest),
                        payload["checkpoint_contract"], payload["lease_owner"], lease_token,
                        now, lease_expires_at,
                    ),
                )
                execution = cursor.fetchone()
                for item in manifest:
                    intent = item["intent"]
                    cursor.execute(
                        """
                        INSERT INTO maitu_live_room_build_plan_operation_results (
                            execution_id, execution_code, build_plan_code, operation_index,
                            operation_type, operation_name, scene_name, layer_name,
                            status, retryable, details, sort_order, operation_fingerprint,
                            effect_class, intent_snapshot, checkpoint_state
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            'not_started', false, %s, %s, %s, %s, %s, 'not_started'
                        )
                        """,
                        (
                            execution["id"], execution_code, build_plan_code, item["operation_index"],
                            item["operation_type"], intent.get("operation_name"), intent.get("scene_name"),
                            intent.get("layer_name") or intent.get("layer_id"), Jsonb({}), item["operation_index"],
                            item["operation_fingerprint"], item["effect_class"], Jsonb(intent),
                        ),
                    )
        self.connection.commit()
        return self.get_live_room_build_plan_execution_result_by_code(build_plan_code, execution_code)

    @staticmethod
    def _active_functional_worker_readback_test_job(
        cursor: Any,
        *,
        execution_job_code: str,
        build_plan_code: str,
        target_live_room_id: str,
    ) -> bool:
        if not execution_job_code:
            return False
        cursor.execute(
            """
            SELECT 1
            FROM maitu_workbench_draft_execution_jobs
            WHERE execution_job_code = %s
              AND source_kind = 'functional_live_room_plan'
              AND execution_mode = 'replace_test_draft'
              AND authority_mode = 'worker_readback'
              AND status = 'running'
              AND claimed_by IS NOT NULL
              AND lease_token IS NOT NULL
              AND lease_expires_at > now()
              AND payload->'build_plan'->>'build_plan_code' = %s
              AND payload->'build_plan'->>'target_live_room_id' = %s
              AND payload->'build_plan'->>'expected_title' = 'asser测试'
              AND payload->>'test_use_acknowledged' = 'true'
              AND payload->>'non_releasable' = 'true'
            LIMIT 1
            """,
            (execution_job_code, build_plan_code, target_live_room_id),
        )
        return cursor.fetchone() is not None

    def get_functional_worker_readback_completion_context(
        self,
        *,
        build_plan_code: str,
        execution_code: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        """Return the exact active test-only job allowed to attest worker readback."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT job.execution_job_code,
                       job.claimed_by AS worker_id,
                       execution.details->>'target_live_room_id' AS target_live_room_id,
                       plan.expected_title,
                       execution.details->>'source_plan_fingerprint' AS source_plan_fingerprint
                FROM maitu_live_room_build_plan_executions AS execution
                JOIN maitu_workbench_draft_execution_jobs AS job
                  ON job.payload->'build_plan'->>'build_plan_code' = execution.build_plan_code
                JOIN functional_live_room_plans AS plan
                  ON plan.id = job.functional_plan_id
                 AND plan.plan_code = job.functional_plan_code
                 AND plan.execution_job_code = job.execution_job_code
                WHERE execution.build_plan_code = %s
                  AND execution.execution_code = %s
                  AND execution.checkpoint_contract = 'script_layout_checkpoint_v1'
                  AND execution.execution_status = 'in_progress'
                  AND execution.finalized_at IS NULL
                  AND execution.lease_owner = %s
                  AND execution.lease_token IS NOT NULL
                  AND execution.lease_expires_at > now()
                  AND execution.details->>'target_live_room_id' = '41172'
                  AND job.source_kind = 'functional_live_room_plan'
                  AND job.execution_mode = 'replace_test_draft'
                  AND job.authority_mode = 'worker_readback'
                  AND job.status = 'running'
                  AND job.claimed_by = %s
                  AND job.lease_token IS NOT NULL
                  AND job.lease_expires_at > now()
                  AND job.payload->>'test_use_acknowledged' = 'true'
                  AND job.payload->>'non_releasable' = 'true'
                  AND job.payload->>'ready_for_go_live' = 'false'
                  AND job.payload->'build_plan'->>'target_live_room_id' = '41172'
                  AND job.payload->'build_plan'->>'expected_title' = 'asser测试'
                  AND job.payload->'build_plan'->>'source_plan_fingerprint'
                      = execution.details->>'source_plan_fingerprint'
                  AND plan.execution_status = 'maitu_running'
                  AND plan.target_live_room_id = '41172'
                  AND plan.expected_title = 'asser测试'
                  AND plan.build_plan->>'build_plan_code' = execution.build_plan_code
                LIMIT 2
                """,
                (build_plan_code, execution_code, worker_id, worker_id),
            )
            rows = cursor.fetchall()
        if len(rows) != 1:
            return None
        return dict(rows[0])

    @staticmethod
    def _require_functional_live_room_execution_request(cursor: Any, build_plan_code: str) -> None:
        """Require the functional-plan confirmation only when this BuildPlan has one.

        Standalone legacy Maitu plans retain their existing worker contract. A
        BuildPlan generated from a FunctionalLiveRoomPlan cannot be started by
        a worker until the operator has made the plan-local empty-draft choice.
        """
        cursor.execute(
            """
            SELECT plan_code, execution_status
            FROM functional_live_room_plans
            WHERE build_plan->>'build_plan_code' = %s
            FOR UPDATE
            """,
            (build_plan_code,),
        )
        functional_plan = cursor.fetchone()
        if functional_plan is not None and functional_plan["execution_status"] not in {
            "requested",
            "maitu_running",
            "maitu_reconcile_required",
        }:
            raise BuildPlanCheckpointConflictError(
                "functional live-room execution requires explicit operator confirmation"
            )

    def renew_script_layout_execution(
        self,
        build_plan_code: str,
        execution_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(seconds=self.SCRIPT_LAYOUT_LEASE_SECONDS)
        reconcile_not_before = lease_expires_at + timedelta(
            seconds=self.SCRIPT_LAYOUT_RECONCILE_GRACE_SECONDS
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            if execution.get("finalized_at") is not None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("finalized execution cannot renew a lease")
            self._require_script_layout_lease(execution, payload, now)
            cursor.execute(
                """
                UPDATE maitu_live_room_build_plan_executions
                SET lease_acquired_at = %s, lease_expires_at = %s,
                    lease_reconcile_not_before = GREATEST(
                        COALESCE(lease_reconcile_not_before, %s), %s
                    ), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (now, lease_expires_at, reconcile_not_before, reconcile_not_before, execution["id"]),
            )
        self.connection.commit()
        return self.get_live_room_build_plan_execution_result_by_code(build_plan_code, execution_code)

    def _lock_script_layout_checkpoint(
        self,
        cursor: Any,
        execution_code: str,
        operation_index: int,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT * FROM maitu_live_room_build_plan_operation_results
            WHERE execution_code = %s AND operation_index = %s
            FOR UPDATE
            """,
            (execution_code, operation_index),
        )
        return cursor.fetchone()

    @staticmethod
    def _require_prior_script_layout_operations_terminal(
        cursor: Any,
        execution_code: str,
        operation_index: int,
    ) -> None:
        if operation_index <= 0:
            return
        cursor.execute(
            """
            SELECT operation_index, effect_class, checkpoint_state
            FROM maitu_live_room_build_plan_operation_results
            WHERE execution_code = %s AND operation_index < %s
            ORDER BY operation_index ASC
            FOR UPDATE
            """,
            (execution_code, operation_index),
        )
        prior = cursor.fetchall()
        terminal_by_effect = {
            "mutating": "completed",
            "read_only": "observed",
            "manual_noop": "manual_required",
        }
        if [int(item["operation_index"]) for item in prior] != list(range(operation_index)) or any(
            item.get("checkpoint_state") != terminal_by_effect.get(item.get("effect_class"))
            for item in prior
        ):
            raise BuildPlanCheckpointConflictError(
                "script-layout operations must complete in frozen manifest order"
            )

    def begin_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            if execution.get("finalized_at") is not None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("finalized execution cannot begin more operations")
            self._require_script_layout_lease(execution, payload, now)
            self._require_prior_script_layout_operations_terminal(cursor, execution_code, operation_index)
            checkpoint = self._lock_script_layout_checkpoint(cursor, execution_code, operation_index)
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is absent from frozen checkpoint manifest")
            if checkpoint.get("operation_fingerprint") != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation fingerprint differs from frozen manifest")
            state = checkpoint.get("checkpoint_state")
            if state in {"completed", "observed", "manual_required"}:
                decision = "skip"
            elif state == "reconcile_required":
                decision = "reconcile"
            elif state == "dispatched":
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_operation_results
                    SET checkpoint_state = 'reconcile_required', status = 'reconcile_required', updated_at = now()
                    WHERE id = %s AND checkpoint_state = 'dispatched'
                    RETURNING *
                    """,
                    (checkpoint["id"],),
                )
                checkpoint = cursor.fetchone()
                decision = "reconcile"
            elif state == "prepared" and str(checkpoint.get("attempt_id")) == str(payload["attempt_id"]):
                decision = "execute"
            elif state in {"not_started", "prepared", "retry_authorized"}:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_operation_results
                    SET checkpoint_state = 'prepared', status = 'prepared', attempt_id = %s,
                        dispatched_at = NULL, completion_id = NULL, completion_evidence = '{}'::jsonb,
                        completed_at = NULL, reconciliation_resolution = NULL,
                        reconciliation_evidence = '{}'::jsonb, reconciled_at = NULL, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (payload["attempt_id"], checkpoint["id"]),
                )
                checkpoint = cursor.fetchone()
                decision = "execute"
            else:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError(f"unsupported checkpoint state: {state}")
        self.connection.commit()
        result = self._normalize_live_room_build_plan_operation_result(checkpoint)
        result["decision"] = decision
        return result

    def dispatch_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            self._require_script_layout_lease(execution, payload, now)
            self._require_prior_script_layout_operations_terminal(cursor, execution_code, operation_index)
            checkpoint = self._lock_script_layout_checkpoint(cursor, execution_code, operation_index)
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is absent from frozen checkpoint manifest")
            if checkpoint.get("operation_fingerprint") != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation fingerprint differs from frozen manifest")
            if checkpoint.get("effect_class") != "mutating":
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("only mutating operations may enter dispatched state")
            state = checkpoint.get("checkpoint_state")
            same_attempt = str(checkpoint.get("attempt_id")) == str(payload["attempt_id"])
            if state == "prepared" and same_attempt:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_operation_results
                    SET checkpoint_state = 'dispatched', status = 'dispatched', dispatched_at = %s, updated_at = now()
                    WHERE id = %s AND checkpoint_state = 'prepared'
                    RETURNING *
                    """,
                    (now, checkpoint["id"]),
                )
                checkpoint = cursor.fetchone()
                fenced_until = execution["lease_expires_at"] + timedelta(
                    seconds=self.SCRIPT_LAYOUT_RECONCILE_GRACE_SECONDS
                )
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_executions
                    SET lease_reconcile_not_before = GREATEST(
                        COALESCE(lease_reconcile_not_before, %s), %s
                    ), updated_at = now()
                    WHERE id = %s
                    """,
                    (fenced_until, fenced_until, execution["id"]),
                )
            elif state == "dispatched" and same_attempt:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError(
                    "operation dispatch authorization was already consumed; reconcile before any retry"
                )
            else:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is not prepared for this fenced attempt")
        self.connection.commit()
        result = self._normalize_live_room_build_plan_operation_result(checkpoint)
        result["decision"] = "execute"
        return result

    def invalidate_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            self._require_script_layout_lease(execution, payload, now)
            checkpoint = self._lock_script_layout_checkpoint(cursor, execution_code, operation_index)
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is absent from frozen checkpoint manifest")
            if (
                checkpoint.get("operation_fingerprint") != payload["operation_fingerprint"]
                or checkpoint.get("effect_class") != "mutating"
                or checkpoint.get("checkpoint_state") != "completed"
            ):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("only completed mutating checkpoints may be invalidated")
            details = execution.get("details") if isinstance(execution.get("details"), dict) else {}
            evidence = payload["evidence"]
            expected_identity = {
                "operation_index": operation_index,
                "operation_type": checkpoint["operation_type"],
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "target_live_room_id": details.get("target_live_room_id"),
            }
            if any(evidence.get(key) != value for key, value in expected_identity.items()):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("checkpoint invalidation evidence identity differs from frozen intent")
            cursor.execute(
                """
                UPDATE maitu_live_room_build_plan_operation_results
                SET checkpoint_state = 'reconcile_required', status = 'reconcile_required',
                    reconciliation_evidence = %s, updated_at = now()
                WHERE id = %s AND checkpoint_state = 'completed'
                RETURNING *
                """,
                (Jsonb(evidence), checkpoint["id"]),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("checkpoint invalidation lost a concurrent race")
            fenced_until = execution["lease_expires_at"] + timedelta(
                seconds=self.SCRIPT_LAYOUT_RECONCILE_GRACE_SECONDS
            )
            cursor.execute(
                """
                UPDATE maitu_live_room_build_plan_executions
                SET lease_reconcile_not_before = GREATEST(
                    COALESCE(lease_reconcile_not_before, %s), %s
                ), updated_at = now()
                WHERE id = %s
                """,
                (fenced_until, fenced_until, execution["id"]),
            )
        self.connection.commit()
        result = self._normalize_live_room_build_plan_operation_result(checkpoint)
        result["decision"] = "reconcile"
        return result

    def complete_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            self._require_script_layout_lease(execution, payload, now)
            checkpoint = self._lock_script_layout_checkpoint(cursor, execution_code, operation_index)
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is absent from frozen checkpoint manifest")
            if checkpoint.get("operation_fingerprint") != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation fingerprint differs from frozen manifest")
            semantic_evidence = dict(payload["evidence"])
            for field_name in (
                "readback_attestation",
                "readback_attestation_algorithm",
                "backend_authority_observation",
            ):
                semantic_evidence.pop(field_name, None)
            completion_fingerprint = self._script_layout_fingerprint(
                {
                    "execution_code": execution_code,
                    "operation_index": operation_index,
                    "result_summary": payload.get("result_summary"),
                    "evidence": semantic_evidence,
                    "operation_result": payload["operation_result"],
                }
            )
            if checkpoint.get("checkpoint_state") in {"completed", "observed", "manual_required"}:
                checkpoint_details = checkpoint.get("details") if isinstance(checkpoint.get("details"), dict) else {}
                if (
                    str(checkpoint.get("completion_id")) == str(payload["completion_id"])
                    and checkpoint_details.get("completion_fingerprint") == completion_fingerprint
                ):
                    self.connection.commit()
                    result = self._normalize_live_room_build_plan_operation_result(checkpoint)
                    result["decision"] = "skip"
                    return result
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation was completed by another completion identity")
            effect_class = checkpoint.get("effect_class")
            required_state = "dispatched" if effect_class == "mutating" else "prepared"
            if (
                checkpoint.get("checkpoint_state") != required_state
                or str(checkpoint.get("attempt_id")) != str(payload["attempt_id"])
            ):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is not completable by this fenced attempt")
            evidence = payload["evidence"]
            details = execution.get("details") if isinstance(execution.get("details"), dict) else {}
            expected_identity = {
                "operation_index": operation_index,
                "operation_type": checkpoint["operation_type"],
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "target_live_room_id": details.get("target_live_room_id"),
            }
            if any(evidence.get(key) != value for key, value in expected_identity.items()):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("completion evidence identity differs from frozen intent")
            if effect_class == "mutating":
                terminal_state = "completed"
                if evidence.get("operation_applied") is not True:
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("mutating completion requires operation_applied=true")
            elif effect_class == "read_only":
                terminal_state = "observed"
                if evidence.get("no_side_effect") is not True or evidence.get("operation_applied") is not False:
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("read-only completion requires no_side_effect evidence")
            else:
                terminal_state = "manual_required"
                if evidence.get("no_side_effect") is not True or evidence.get("operation_applied") is not False:
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("manual/noop completion requires no_side_effect evidence")
            operation_result = payload["operation_result"]
            self._validate_completion_readback_attestation(
                build_plan_code=build_plan_code,
                execution_code=execution_code,
                operation_index=operation_index,
                checkpoint=checkpoint,
                payload=payload,
            )
            self._validate_script_layout_terminal_evidence(checkpoint, evidence, operation_result)
            self._validate_script_layout_dynamic_lineage(
                cursor, execution_code, checkpoint, evidence
            )
            result_details = {
                **(operation_result.get("details") or {}),
                **{
                    key: operation_result[key]
                    for key in ("scene_index", "clip_id", "layer_id", "layer_type", "asset_code")
                    if operation_result.get(key) is not None
                },
                "result_summary": payload.get("result_summary"),
                "completion_fingerprint": completion_fingerprint,
            }
            cursor.execute(
                """
                UPDATE maitu_live_room_build_plan_operation_results
                SET operation_type = %s, operation_name = %s, scene_name = %s,
                    layer_name = %s, action_type = %s, status = %s,
                    failure_type = %s, retryable = %s, retry_instruction = %s,
                    error_message = %s, screenshot_asset_code = %s,
                    dom_snapshot_asset_code = %s, details = %s,
                    checkpoint_state = %s, completion_id = %s,
                    completion_evidence = %s, completed_at = %s, updated_at = now()
                WHERE id = %s AND checkpoint_state = %s AND attempt_id = %s
                RETURNING *
                """,
                (
                    operation_result["operation_type"], operation_result.get("operation_name"),
                    operation_result.get("scene_name"), operation_result.get("layer_name") or operation_result.get("layer_id"),
                    operation_result.get("action_type"), operation_result["status"],
                    operation_result.get("failure_type"), operation_result.get("retryable", False),
                    operation_result.get("retry_instruction"), operation_result.get("error_message"),
                    operation_result.get("screenshot_asset_code"), operation_result.get("dom_snapshot_asset_code"),
                    Jsonb(result_details), terminal_state, payload["completion_id"], Jsonb(evidence), now,
                    checkpoint["id"], required_state, payload["attempt_id"],
                ),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation completion lost a concurrent race")
        self.connection.commit()
        result = self._normalize_live_room_build_plan_operation_result(checkpoint)
        result["decision"] = "skip"
        return result

    def reconcile_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            if self._lease_is_active(execution, now):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("cannot reconcile while a script-layout lease is active")
            not_before = execution.get("lease_reconcile_not_before")
            if isinstance(not_before, datetime) and now < not_before:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("reconciliation grace period has not elapsed")
            checkpoint = self._lock_script_layout_checkpoint(cursor, execution_code, operation_index)
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation is absent from frozen checkpoint manifest")
            receipt_fingerprint = self._script_layout_fingerprint(
                {
                    "execution_code": execution_code,
                    "operation_index": operation_index,
                    "payload": payload,
                }
            )
            cursor.execute(
                """
                SELECT * FROM maitu_live_room_build_plan_reconciliations
                WHERE reconciliation_id = %s
                """,
                (payload["reconciliation_id"],),
            )
            receipt = cursor.fetchone()
            if receipt is not None:
                same_receipt = receipt.get("receipt_fingerprint") == receipt_fingerprint
                if not same_receipt:
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("reconciliation identity was reused with different intent")
                self.connection.commit()
                result = self._normalize_live_room_build_plan_operation_result(checkpoint)
                result["decision"] = "skip" if checkpoint.get("checkpoint_state") == "completed" else "execute"
                return result
            if checkpoint.get("operation_fingerprint") != payload["operation_fingerprint"]:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("reconciliation fingerprint differs from frozen manifest")
            prior_checkpoint_state = checkpoint.get("checkpoint_state")
            if prior_checkpoint_state not in {"dispatched", "reconcile_required"}:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation checkpoint is not awaiting reconciliation")
            if str(checkpoint.get("attempt_id")) != str(payload["reconciled_attempt_id"]):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("reconciled attempt differs from uncertain dispatched attempt")
            evidence = payload["evidence"]
            details = execution.get("details") if isinstance(execution.get("details"), dict) else {}
            expected_identity = {
                "operation_index": operation_index,
                "operation_type": checkpoint["operation_type"],
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "target_live_room_id": details.get("target_live_room_id"),
            }
            if any(evidence.get(key) != value for key, value in expected_identity.items()):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("reconciliation evidence identity differs from frozen intent")
            self._validate_reconciliation_readback_attestation(
                build_plan_code=build_plan_code,
                execution_code=execution_code,
                operation_index=operation_index,
                checkpoint=checkpoint,
                payload=payload,
            )
            resulting_state = "completed" if payload["resolution"] == "confirmed_completed" else "retry_authorized"
            operation_result = payload.get("operation_result") if resulting_state == "completed" else None
            if resulting_state == "completed" and not isinstance(operation_result, dict):
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("confirmed completion requires an operation result")
            if resulting_state == "completed" and checkpoint.get("effect_class") != "mutating":
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("only uncertain mutating operations may reconcile as completed")
            if resulting_state == "completed":
                self._validate_script_layout_terminal_evidence(checkpoint, evidence, operation_result)
                self._validate_script_layout_dynamic_lineage(
                    cursor, execution_code, checkpoint, evidence
                )
            cursor.execute(
                """
                INSERT INTO maitu_live_room_build_plan_reconciliations (
                    reconciliation_id, receipt_fingerprint, operation_result_id,
                    execution_code, operation_index, operation_fingerprint,
                    reconciled_attempt_id, resolution, resolution_summary, evidence,
                    operation_result, prior_completion_id, prior_completion_evidence,
                    prior_completed_at, reconciled_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["reconciliation_id"], receipt_fingerprint, checkpoint["id"],
                    execution_code, operation_index, checkpoint["operation_fingerprint"],
                    payload["reconciled_attempt_id"], payload["resolution"],
                    payload["resolution_summary"], Jsonb(evidence),
                    Jsonb(operation_result) if operation_result is not None else None,
                    checkpoint.get("completion_id"),
                    Jsonb(checkpoint.get("completion_evidence") or {}),
                    checkpoint.get("completed_at"), payload["reconciled_by"],
                ),
            )
            history_record = {
                "reconciliation_id": str(payload["reconciliation_id"]),
                "resolution": payload["resolution"],
                "resolution_summary": payload["resolution_summary"],
                "reconciled_by": payload["reconciled_by"],
                "evidence": evidence,
            }
            old_details = checkpoint.get("details") if isinstance(checkpoint.get("details"), dict) else {}
            history = list(old_details.get("reconciliations") or [])
            history.append(history_record)
            result_details = {
                **old_details,
                **((operation_result or {}).get("details") or {}),
                "reconciliation": history_record,
                "reconciliations": history,
            }
            completion_id = uuid4() if resulting_state == "completed" else None
            cursor.execute(
                """
                UPDATE maitu_live_room_build_plan_operation_results
                SET checkpoint_state = %s, status = %s, details = %s,
                    operation_name = COALESCE(%s, operation_name),
                    scene_name = COALESCE(%s, scene_name), layer_name = COALESCE(%s, layer_name),
                    action_type = COALESCE(%s, action_type), completion_id = %s,
                    completion_evidence = %s,
                    completed_at = CASE WHEN %s = 'completed' THEN %s ELSE NULL END,
                    reconciled_attempt_id = %s, reconciliation_resolution = %s,
                    reconciliation_evidence = %s, reconciled_at = %s, updated_at = now()
                WHERE id = %s AND checkpoint_state IN ('dispatched', 'reconcile_required')
                RETURNING *
                """,
                (
                    resulting_state,
                    (operation_result or {}).get("status") if resulting_state == "completed" else "retry_authorized",
                    Jsonb(result_details), (operation_result or {}).get("operation_name"),
                    (operation_result or {}).get("scene_name"),
                    (operation_result or {}).get("layer_name") or (operation_result or {}).get("layer_id"),
                    (operation_result or {}).get("action_type"), completion_id,
                    Jsonb(evidence if resulting_state == "completed" else {}), resulting_state, now,
                    payload["reconciled_attempt_id"], payload["resolution"], Jsonb(evidence), now,
                    checkpoint["id"],
                ),
            )
            checkpoint = cursor.fetchone()
            if checkpoint is None:
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("operation reconciliation lost a concurrent race")
        self.connection.commit()
        result = self._normalize_live_room_build_plan_operation_result(checkpoint)
        result["decision"] = "skip" if resulting_state == "completed" else "execute"
        return result

    def finalize_script_layout_execution(
        self,
        build_plan_code: str,
        execution_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        semantic_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"finalization_id", "run_attempt_id", "lease_token", "lease_version", "lease_owner"}
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id FROM maitu_live_room_build_plans
                WHERE build_plan_code = %s AND deleted_at IS NULL
                FOR UPDATE
                """,
                (build_plan_code,),
            )
            if cursor.fetchone() is None:
                self.connection.commit()
                return None
            execution = self._lock_script_layout_execution(cursor, build_plan_code, execution_code)
            if execution is None:
                self.connection.commit()
                return None
            finalization_fingerprint = self._script_layout_fingerprint(
                {
                    "execution_code": execution_code,
                    "manifest_fingerprint": execution.get("manifest_fingerprint"),
                    "payload": semantic_payload,
                }
            )
            if execution.get("finalized_at") is not None:
                if (
                    str(execution.get("finalization_id")) == str(payload["finalization_id"])
                    and execution.get("finalization_fingerprint") == finalization_fingerprint
                ):
                    self.connection.commit()
                    return self.get_live_room_build_plan_execution_result_by_code(build_plan_code, execution_code)
                self.connection.rollback()
                raise BuildPlanCheckpointConflictError("execution was finalized by another immutable identity")
            self._require_script_layout_lease(execution, payload, now)
            cursor.execute(
                """
                SELECT * FROM maitu_live_room_build_plan_operation_results
                WHERE execution_code = %s
                ORDER BY operation_index ASC
                FOR UPDATE
                """,
                (execution_code,),
            )
            checkpoints = cursor.fetchall()
            successful = payload["execution_status"] in {"completed", "completed_with_manual_review"}
            if successful:
                expected_count = int(execution.get("expected_operation_count") or -1)
                if len(checkpoints) != expected_count:
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("successful finalize requires exact frozen manifest cardinality")
                expected_indexes = list(range(expected_count))
                actual_indexes = [int(item["operation_index"]) for item in checkpoints]
                allowed_state = {
                    "mutating": "completed",
                    "read_only": "observed",
                    "manual_noop": "manual_required",
                }
                if actual_indexes != expected_indexes or any(
                    item.get("checkpoint_state") != allowed_state.get(item.get("effect_class"))
                    for item in checkpoints
                ):
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("successful finalize requires every manifest policy terminal")
                has_manual_gate = any(item.get("effect_class") == "manual_noop" for item in checkpoints)
                expected_status = "completed_with_manual_review" if has_manual_gate else "completed"
                if (
                    payload["execution_status"] != expected_status
                    or bool(payload.get("manual_review_required")) is not has_manual_gate
                    or bool(payload.get("ready_for_go_live"))
                ):
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError(
                        "finalization status and safety flags differ from frozen checkpoint policy"
                    )
                recomputed_manifest = self._script_layout_fingerprint(
                    {
                        "checkpoint_contract": execution["checkpoint_contract"],
                        "operations": [item["operation_fingerprint"] for item in checkpoints],
                    }
                )
                if recomputed_manifest != execution.get("manifest_fingerprint"):
                    self.connection.rollback()
                    raise BuildPlanCheckpointConflictError("checkpoint manifest fingerprint no longer matches frozen execution")
            execution_details = {
                **(execution.get("details") or {}),
                **(payload.get("details") or {}),
                "ready_for_go_live": bool(payload.get("ready_for_go_live", False)),
                "manual_review_required": bool(payload.get("manual_review_required", False)),
            }
            if successful:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_executions
                    SET executor = %s, execution_status = %s, failure_type = %s,
                        retryable = %s, retry_instruction = %s, finished_at = %s,
                        error_message = %s, screenshot_asset_code = %s,
                        dom_snapshot_asset_code = %s, result_summary = %s, details = %s,
                        finalization_id = %s, finalization_fingerprint = %s, finalized_at = %s,
                        run_attempt_id = NULL, lease_owner = NULL, lease_token = NULL,
                        lease_acquired_at = NULL, lease_expires_at = NULL, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        payload.get("executor", "browser_use"), payload["execution_status"],
                        payload.get("failure_type"), payload.get("retryable", False),
                        payload.get("retry_instruction"), payload.get("finished_at") or now,
                        payload.get("error_message"), payload.get("screenshot_asset_code"),
                        payload.get("dom_snapshot_asset_code"), payload.get("result_summary"),
                        Jsonb(execution_details), payload["finalization_id"], finalization_fingerprint,
                        now, execution["id"],
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
            else:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_executions
                    SET executor = %s, execution_status = %s, failure_type = %s,
                        retryable = %s, retry_instruction = %s, finished_at = %s,
                        error_message = %s, screenshot_asset_code = %s,
                        dom_snapshot_asset_code = %s, result_summary = %s, details = %s,
                        updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        payload.get("executor", "browser_use"), payload["execution_status"],
                        payload.get("failure_type"), payload.get("retryable", False),
                        payload.get("retry_instruction"), payload.get("finished_at") or now,
                        payload.get("error_message"), payload.get("screenshot_asset_code"),
                        payload.get("dom_snapshot_asset_code"), payload.get("result_summary"),
                        Jsonb(execution_details), execution["id"],
                    ),
                )
                has_uncertain_side_effect = any(
                    item.get("checkpoint_state") in {"dispatched", "reconcile_required"}
                    for item in checkpoints
                )
                if not has_uncertain_side_effect:
                    cursor.execute(
                        """
                        UPDATE maitu_live_room_build_plan_executions
                        SET run_attempt_id = NULL, lease_owner = NULL, lease_token = NULL,
                            lease_acquired_at = NULL, lease_expires_at = NULL,
                            lease_reconcile_not_before = NULL, updated_at = now()
                        WHERE id = %s
                        """,
                        (execution["id"],),
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
        if "expected_before_state" in data:
            data["expected_before_state"] = Jsonb(data["expected_before_state"])
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
        if "expected_before_state" in data:
            data["expected_before_state"] = Jsonb(data["expected_before_state"])
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
            "target_live_room_id": payload.get("target_live_room_id"),
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
                    plan_code, plan_name, maitu_project_code, target_live_room_id,
                    scene_name, status, strategy, description
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    plan_data["plan_code"],
                    plan_data["plan_name"],
                    plan_data["maitu_project_code"],
                    plan_data["target_live_room_id"],
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
        self._assert_secret_free_claimed_by(payload)
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
        self._assert_secret_free_claimed_by(payload)
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
        self._assert_secret_free_claimed_by(payload)
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
        self._assert_secret_free_claimed_by(payload)
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
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT operation_key, contract_version, operation_type, target_app, intent_fingerprint,
                       intent_payload, readiness_status, blocked_reasons
                FROM maitu_retry_operation_intents
                WHERE retry_task_code = %s
                ORDER BY CASE operation_key WHEN 'primary' THEN 0 ELSE 1 END, operation_key
                """,
                (retry_task_code,),
            )
            snapshots = cursor.fetchall()
            if snapshots:
                operations = [
                    self._operation_from_snapshot_row(
                        snapshot,
                        retry_task_code=retry_task_code,
                        operation_key=snapshot.get("operation_key"),
                    )
                    for snapshot in snapshots
                ]
            else:
                operations = []
                for candidate in self._build_retry_operations_from_current_context(cursor, task):
                    legacy = dict(candidate)
                    legacy["status"] = "blocked"
                    legacy["blocked_reasons"] = [
                        *legacy.get("blocked_reasons", []),
                        "missing_immutable_intent_snapshot",
                    ]
                    operations.append(legacy)
        authoritative_plan = (
            operations[0]["authoritative_intent"]
            if snapshots and operations
            else {}
        )
        return {
            "retry_task_code": retry_task_code,
            "plan_code": task["plan_code"],
            "execution_code": task["execution_code"],
            "executor": task.get("executor", "browser_use"),
            "target_app": "maitu",
            "maitu_project_code": (
                authoritative_plan.get("maitu_project_code")
                if snapshots
                else plan.get("maitu_project_code")
            ),
            "scene_name": (
                authoritative_plan.get("target_scene_name")
                if snapshots
                else (slot or {}).get("scene_name") or plan.get("scene_name")
            ),
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
        self._assert_secret_free_claimed_by(payload)
        if UUID(str(payload["attempt_id"])) == UUID(str(payload["claim_token"])):
            raise RetryCheckpointConflictError("checkpoint attempt_id must not equal the active claim token")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            task = self._lock_retry_task_for_checkpoint(cursor, retry_task_code)
            if task is None:
                self.connection.commit()
                return None
            self._assert_current_retry_lease(task, payload)
            operation = self._find_authoritative_retry_operation(cursor, task, operation_key)
            if operation.get("status") != "ready":
                self.connection.rollback()
                raise RetryCheckpointConflictError("authoritative retry operation is not ready for execution")
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
        self._assert_secret_free_claimed_by(payload)
        if UUID(str(payload["attempt_id"])) == UUID(str(payload["claim_token"])):
            raise RetryCheckpointConflictError("checkpoint attempt_id must not equal the active claim token")
        if UUID(str(payload["completion_id"])) == UUID(str(payload["claim_token"])):
            raise RetryCheckpointConflictError("checkpoint completion_id must not equal the active claim token")
        self._assert_verified_secret_free_evidence(
            payload.get("evidence", {}),
            payload["claim_token"],
            result_summary=payload.get("result_summary"),
        )
        completion_fingerprint = self._completion_payload_fingerprint(payload)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            task = self._lock_retry_task_for_checkpoint(cursor, retry_task_code)
            if task is None:
                self.connection.commit()
                return None
            self._assert_current_retry_lease(task, payload)
            operation = self._find_authoritative_retry_operation(cursor, task, operation_key)
            if operation.get("status") != "ready":
                self.connection.rollback()
                raise RetryCheckpointConflictError("authoritative retry operation is not ready for execution")
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
                    result_summary=checkpoint.get("completion_summary"),
                )
                stored_completion_fingerprint = self._completion_checkpoint_fingerprint(checkpoint)
                if (
                    stored_completion_fingerprint is None
                    or checkpoint.get("completion_fingerprint") != stored_completion_fingerprint
                ):
                    self.connection.rollback()
                    raise RetryCheckpointConflictError("stored checkpoint completion is inconsistent")
                if (
                    str(checkpoint["completion_id"]) == str(payload["completion_id"])
                    and stored_completion_fingerprint == completion_fingerprint
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
        receipt_payload = self._retry_execution_receipt_payload(payload)
        fingerprint = self._retry_execution_receipt_payload_fingerprint(receipt_payload)
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
                SELECT *
                FROM maitu_retry_execution_receipts
                WHERE retry_execution_id = %s
                """,
                (retry_execution_id,),
            )
            receipt = cursor.fetchone()
            if receipt is not None:
                stored_fingerprint = self._retry_execution_receipt_fingerprint(receipt)
                if (
                    receipt.get("retry_task_code") == retry_task_code
                    and receipt.get("result_payload") == receipt_payload
                    and stored_fingerprint is not None
                    and receipt.get("result_fingerprint") == stored_fingerprint
                    and stored_fingerprint == fingerprint
                ):
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
                        result_summary=completed_checkpoint.get("completion_summary"),
                    )
                    completion_source = completed_checkpoint.get("completion_source")
                    if completion_source == "worker":
                        stored_completion_fingerprint = self._completion_checkpoint_fingerprint(
                            completed_checkpoint
                        )
                        if (
                            stored_completion_fingerprint is None
                            or completed_checkpoint.get("completion_fingerprint")
                            != stored_completion_fingerprint
                            or completed_checkpoint.get("completed_by") != payload["claimed_by"]
                            or completed_checkpoint.get("completed_lease_version")
                            != payload["lease_version"]
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
                    if authoritative_operation.get("status") != "ready":
                        self.connection.rollback()
                        raise RetryCheckpointConflictError(
                            f"completed checkpoint belongs to blocked operation {operation_key}"
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

    @staticmethod
    def _required_category_filter(required_category: str) -> tuple[str, list[Any]]:
        variant_clauses: list[str] = []
        values: list[Any] = []
        for variant in required_category_variants(required_category):
            clauses = ["maitu_category = %s"]
            values.append(variant.maitu_category)
            if variant.maitu_type is not None:
                clauses.append("maitu_type = %s")
                values.append(variant.maitu_type)
            if variant.usages:
                placeholders = ", ".join(["%s"] * len(variant.usages))
                clauses.append(f"usage IN ({placeholders})")
                values.extend(variant.usages)
            variant_clauses.append(f"({' AND '.join(clauses)})")
        if not variant_clauses:
            return "FALSE", []
        return f"({' OR '.join(variant_clauses)})", values

    def select_assets_for_script_asset_need(
        self,
        need: dict[str, Any],
        scene: dict[str, Any],
        *,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        required_category = str(need.get("required_category") or "").strip()
        if not required_category:
            return []
        need = {**need, "required_category": required_category}
        accepted_asset_types = [str(item) for item in (need.get("accepted_asset_types") or []) if str(item) != "TEXT"]
        category_clause, category_values = self._required_category_filter(required_category)
        where_clauses = ["deleted_at IS NULL", category_clause]
        values: list[Any] = list(category_values)
        if accepted_asset_types:
            placeholders = ", ".join(["%s"] * len(accepted_asset_types))
            where_clauses.append(f"asset_type IN ({placeholders})")
            values.extend(accepted_asset_types)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT assets.asset_code, assets.asset_type, assets.title, assets.original_filename,
                    assets.display_code, assets.local_file_code, assets.local_relative_path,
                    assets.browser_use_hint, assets.maitu_material_id, assets.source_material_type,
                    assets.source_material_url, assets.source_cover_url, assets.speaker_id,
                    assets.digital_human_image_id, assets.maitu_category, assets.maitu_type,
                    assets.maitu_project_code, assets.maitu_scene_name, assets.maitu_layer_name,
                    assets.maitu_slot_name, assets.subject, assets.usage, assets.replacement_policy,
                    assets.description, assets.material_roles,
                    constraint_revision.constraints AS constraint_rules
                FROM assets
                LEFT JOIN asset_constraint_profiles AS constraint_profile
                  ON constraint_profile.asset_id = assets.id
                LEFT JOIN asset_constraint_profile_revisions AS constraint_revision
                  ON constraint_revision.profile_id = constraint_profile.id
                 AND constraint_revision.revision_number = constraint_profile.current_revision
                WHERE {' AND '.join(f'assets.{clause}' if clause == 'deleted_at IS NULL' else clause for clause in where_clauses)}
                ORDER BY assets.created_at DESC
                LIMIT 200
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        selectable_rows = [dict(row) for row in rows]
        if str(required_category) == "product_image":
            identity_keywords = product_identity_keywords(need.get("keywords") or [])
            selectable_rows = [
                row
                for row in selectable_rows
                if asset_matches_product_identity(row, identity_keywords)
            ]
        candidates = [
            self._score_script_asset_need_candidate(row, need, scene)
            for row in selectable_rows
            if not self._is_direct_layer_forbidden_template_asset(row, need)
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
        required_category = str(layer.get("required_category") or "").strip()
        if not required_category:
            return None
        layer = {**layer, "required_category": required_category}
        accepted_asset_types = [str(item) for item in (layer.get("accepted_asset_types") or [])]
        category_clause, category_values = self._required_category_filter(required_category)
        where_clauses = ["deleted_at IS NULL", category_clause]
        values: list[Any] = list(category_values)
        if accepted_asset_types:
            placeholders = ", ".join(["%s"] * len(accepted_asset_types))
            where_clauses.append(f"asset_type IN ({placeholders})")
            values.extend(accepted_asset_types)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT assets.asset_code, assets.asset_type, assets.title, assets.original_filename,
                    assets.display_code, assets.local_file_code, assets.local_relative_path,
                    assets.browser_use_hint, assets.maitu_material_id, assets.source_material_type,
                    assets.source_material_url, assets.source_cover_url, assets.speaker_id,
                    assets.digital_human_image_id, assets.maitu_category, assets.maitu_type,
                    assets.maitu_project_code, assets.maitu_scene_name, assets.maitu_layer_name,
                    assets.maitu_slot_name, assets.subject, assets.usage, assets.replacement_policy,
                    assets.description, assets.material_roles,
                    constraint_revision.constraints AS constraint_rules
                FROM assets
                LEFT JOIN asset_constraint_profiles AS constraint_profile
                  ON constraint_profile.asset_id = assets.id
                LEFT JOIN asset_constraint_profile_revisions AS constraint_revision
                  ON constraint_revision.profile_id = constraint_profile.id
                 AND constraint_revision.revision_number = constraint_profile.current_revision
                WHERE {' AND '.join(f'assets.{clause}' if clause == 'deleted_at IS NULL' else clause for clause in where_clauses)}
                ORDER BY assets.created_at DESC
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
        if required_category == "product_image":
            identity_keywords = product_identity_keywords(layer.get("keywords") or [])
            selectable_rows = [
                row
                for row in selectable_rows
                if (
                    asset_matches_product_identity(row, identity_keywords)
                    if identity_keywords
                    else asset_product_identity_mentioned_in_text(row, script_context)
                )
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
        if asset_matches_required_category(asset, str(required_category or "")):
            score += 0.55
            if asset.get("maitu_category") == required_category:
                reasons.append(f"maitu_category matches required_category: {required_category}")
            else:
                reasons.append(
                    f"native Maitu taxonomy maps {asset.get('maitu_type')}/{asset.get('usage')} "
                    f"to required_category: {required_category}"
                )
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
        if asset_matches_required_category(asset, str(required_category or "")):
            score += 0.55
            if asset.get("maitu_category") == required_category:
                reasons.append(f"maitu_category matches required_category: {required_category}")
            else:
                reasons.append(
                    f"native Maitu taxonomy maps {asset.get('maitu_type')}/{asset.get('usage')} "
                    f"to required_category: {required_category}"
                )
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
                    dom_snapshot_asset_code, details, sort_order,
                    operation_fingerprint, effect_class, intent_snapshot,
                    checkpoint_state, attempt_id, completion_id,
                    completion_evidence, dispatched_at, completed_at,
                    reconciled_attempt_id, reconciliation_resolution,
                    reconciliation_evidence, reconciled_at
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
        self._snapshot_retry_operation_intents_for_task(cursor, {
            "retry_task_code": retry_task_code,
            "plan_code": plan_code,
            "execution_code": execution_code,
            "slot_code": operation_payload.get("slot_code") if operation_payload else None,
            "asset_code": operation_payload.get("asset_code") if operation_payload else None,
            "executor": execution_payload.get("executor", "browser_use"),
            "failure_type": source.get("failure_type"),
            "retryable": True,
            "retry_instruction": source.get("retry_instruction"),
            "status": "pending",
        })

    @staticmethod
    def _insert_retry_operation_intents(cursor: Any, operations: list[dict[str, Any]]) -> None:
        for operation in operations:
            durable_payload = {
                key: value for key, value in operation.items() if key != "operation_fingerprint"
            }
            operator_token = settings.maitu_reconciliation_operator_token
            forbidden_values = (
                (operator_token.get_secret_value(),)
                if operator_token is not None and operator_token.get_secret_value()
                else ()
            )
            if not is_canonical_retry_operation_intent(operation) or contains_durable_secret(
                durable_payload,
                forbidden_values=forbidden_values,
            ):
                raise ValueError("retry operation intent is incomplete or unsafe")
            cursor.execute(
                """
                INSERT INTO maitu_retry_operation_intents (
                    retry_task_code, operation_key, contract_version, operation_type,
                    target_app, intent_fingerprint, intent_payload,
                    readiness_status, blocked_reasons
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    operation["retry_task_code"],
                    operation["operation_key"],
                    operation["contract_version"],
                    operation["operation_type"],
                    operation["target_app"],
                    operation["operation_fingerprint"],
                    Jsonb(operation),
                    operation["status"],
                    Jsonb(operation["blocked_reasons"]),
                ),
            )

    def _snapshot_retry_operation_intents_for_task(self, cursor: Any, task: dict[str, Any]) -> None:
        operations = self._build_retry_operations_from_current_context(cursor, task)
        self._insert_retry_operation_intents(cursor, operations)

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
        if execution_status == "completed_with_manual_review":
            return "execution_manual_review"
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
        plan_scene_name = plan.get("scene_name")
        slot_scene_name = slot.get("scene_name")
        scene_name = slot_scene_name or plan_scene_name
        layer_name = slot.get("layer_name")
        slot_name = plan_item.get("slot_name") or slot.get("slot_name")
        asset_title = plan_item.get("selected_asset_title")
        policy = plan_item.get("replacement_policy") or slot.get("replacement_policy") or "keep_layout"
        primary_operation_type = cls._retry_operation_type_for_failure(task.get("failure_type"))
        target_live_room_id = plan.get("target_live_room_id")
        slot_target_live_room_id = slot.get("target_live_room_id")
        target_clip_id = slot.get("target_clip_id")
        target_layer_id = slot.get("target_layer_id")
        expected_before_state = slot.get("expected_before_state")
        accepted_asset_types_raw = slot.get("accepted_asset_types")
        if isinstance(accepted_asset_types_raw, str):
            accepted_asset_types = [
                value.strip() for value in accepted_asset_types_raw.split(",") if value.strip()
            ]
        elif isinstance(accepted_asset_types_raw, list):
            accepted_asset_types = [str(value).strip() for value in accepted_asset_types_raw if str(value).strip()]
        else:
            accepted_asset_types = []
        selected_asset_code = plan_item.get("selected_asset_code")
        binding_asset_code = plan_item.get("binding_asset_code")
        selected_asset_type = plan_item.get("selected_asset_type")
        selected_asset_status = plan_item.get("selected_asset_status")
        maitu_material_id = plan_item.get("selected_asset_maitu_material_id")
        source_material_type = plan_item.get("selected_asset_source_material_type")
        binding_verification_source = plan_item.get("selected_asset_binding_verification_source")
        binding_verified_at = plan_item.get("selected_asset_binding_verified_at")
        binding_scope = plan_item.get("selected_asset_binding_scope")
        base_ready = bool(task.get("retryable") and task.get("status") in {"pending", "in_progress"})
        instruction = (
            f"执行重试任务 {retry_task_code}：{task.get('retry_instruction') or '按失败原因重试'}；"
            f"进入麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
            f"只重试槽位 {task.get('slot_code') or '整体执行'}，找到 {layer_name or slot_name or '目标图层/槽位'}，"
            f"将素材替换为 {task.get('asset_code') or '原计划素材'}（{asset_title or '未命名素材'}），"
            f"替换策略为 {policy}；保持原图层位置和尺寸不变。"
        )
        material_binding_verified = bool(
            isinstance(maitu_material_id, int)
            and not isinstance(maitu_material_id, bool)
            and maitu_material_id > 0
            and source_material_type in {"image", "video"}
            and binding_verification_source == "maitu_readback"
            and isinstance(binding_verified_at, datetime)
            and binding_verified_at.utcoffset() is not None
            and binding_scope == f"live_room:{target_live_room_id}"
        )
        asset_identity_matches = bool(
            task.get("asset_code")
            and selected_asset_code
            and binding_asset_code
            and task.get("asset_code") == selected_asset_code == binding_asset_code
        )
        asset_is_stored = selected_asset_status == "stored"
        asset_type_is_accepted = bool(
            accepted_asset_types and selected_asset_type in accepted_asset_types
        )
        expected_source_material_type = {
            "IMG": "image",
            "VID": "video",
        }.get(selected_asset_type)
        asset_material_type_matches = (
            expected_source_material_type == source_material_type
            if expected_source_material_type is not None and source_material_type in {"image", "video"}
            else None
        )
        replacement_policy_supported = policy == "keep_layout"
        binding_verified_at_canonical = (
            binding_verified_at.astimezone(UTC).isoformat()
            if isinstance(binding_verified_at, datetime) and binding_verified_at.utcoffset() is not None
            else None
        )
        expected_before_state_missing = not isinstance(expected_before_state, dict) or not expected_before_state
        expected_before_state_verified = is_canonical_retry_before_state(
            expected_before_state,
            target_layer_id=target_layer_id,
        )
        desired_geometry = (
            {
                key: expected_before_state[key]
                for key in ("left", "top", "width", "height", "z_index")
            }
            if expected_before_state_verified
            else None
        )
        desired_after_state = {
            "maitu_material_id": maitu_material_id,
            "source_material_type": source_material_type,
            "replacement_policy": policy,
            "geometry": desired_geometry,
        }

        def blocked_reasons(operation_type: str) -> list[str]:
            reasons: list[str] = []
            if not plan.get("maitu_project_code"):
                reasons.append("missing_maitu_project_code")
            if not target_live_room_id:
                reasons.append("missing_target_live_room_id")
            elif not slot_target_live_room_id:
                reasons.append("missing_slot_target_live_room_id")
            elif slot_target_live_room_id != target_live_room_id:
                reasons.append("target_live_room_mismatch")
            if not scene_name:
                reasons.append("missing_target_scene_name")
            elif plan_scene_name and slot_scene_name and plan_scene_name != slot_scene_name:
                reasons.append("target_scene_mismatch")
            if not target_clip_id:
                reasons.append("missing_target_clip_id")
            if operation_type == "retry_replace_layer_asset":
                if not target_layer_id:
                    reasons.append("missing_target_layer_id")
                if expected_before_state_missing:
                    reasons.append("missing_expected_before_state")
                elif not expected_before_state_verified:
                    reasons.append("invalid_expected_before_state")
                if not asset_identity_matches:
                    reasons.append("asset_identity_mismatch")
                if not asset_is_stored:
                    reasons.append("asset_not_stored")
                if not accepted_asset_types:
                    reasons.append("missing_accepted_asset_types")
                elif not asset_type_is_accepted:
                    reasons.append("asset_type_not_accepted")
                if selected_asset_type is not None and asset_material_type_matches is not True:
                    reasons.append("asset_material_type_mismatch")
                if not replacement_policy_supported:
                    reasons.append("unsupported_replacement_policy")
                if not material_binding_verified:
                    reasons.append("missing_verified_maitu_material_binding")
            elif operation_type == "retry_save_project":
                reasons.append("save_project_not_implemented")
            else:
                reasons.append("unsupported_production_retry_operation")
            if not base_ready:
                reasons.append("retry_task_not_executable")
            return reasons

        fingerprint_base = {
            "contract_version": "maitu-retry-mutation-v1",
            "retry_task_code": retry_task_code,
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "target_live_room_id": target_live_room_id,
            "slot_target_live_room_id": slot_target_live_room_id,
            "target_clip_id": target_clip_id,
            "target_layer_id": target_layer_id,
            "plan_target_scene_name": plan_scene_name,
            "slot_target_scene_name": slot_scene_name,
            "expected_before_state": expected_before_state,
            "desired_after_state": desired_after_state,
            "target_scene_name": scene_name,
            "slot_code": task.get("slot_code"),
            "layer_name": layer_name,
            "asset_code": task.get("asset_code"),
            "selected_asset_code": selected_asset_code,
            "binding_asset_code": binding_asset_code,
            "selected_asset_type": selected_asset_type,
            "selected_asset_status": selected_asset_status,
            "accepted_asset_types": accepted_asset_types,
            "maitu_material_id": maitu_material_id,
            "source_material_type": source_material_type,
            "binding_verification_source": binding_verification_source,
            "binding_verified_at": binding_verified_at_canonical,
            "binding_scope": binding_scope,
            "replacement_policy": policy,
            "primary_operation_type": primary_operation_type,
            "retry_task_retryable": task.get("retryable"),
        }

        def operation(operation_key: str, operation_type: str, operation_instruction: str) -> dict[str, Any]:
            fingerprint_intent = {
                **fingerprint_base,
                "operation_key": operation_key,
                "operation_type": operation_type,
                "instruction": operation_instruction,
            }
            reasons = blocked_reasons(operation_type)
            return {
                "contract_version": "maitu-retry-mutation-v1",
                "target_app": "maitu",
                "operation_key": operation_key,
                "operation_fingerprint": cls._operation_fingerprint(fingerprint_intent),
                "operation_type": operation_type,
                "retry_task_code": retry_task_code,
                "authoritative_intent": fingerprint_intent,
                "target_live_room_id": target_live_room_id,
                "target_clip_id": target_clip_id,
                "target_scene_name": scene_name,
                "target_layer_id": target_layer_id,
                "expected_before_state": expected_before_state,
                "desired_after_state": desired_after_state,
                "slot_code": task.get("slot_code"),
                "slot_name": slot_name,
                "scene_name": scene_name,
                "layer_name": layer_name,
                "asset_code": task.get("asset_code"),
                "asset_title": asset_title,
                "selected_asset_type": selected_asset_type,
                "selected_asset_status": selected_asset_status,
                "accepted_asset_types": accepted_asset_types,
                "maitu_material_id": maitu_material_id,
                "source_material_type": source_material_type,
                "binding_verification_source": binding_verification_source,
                "binding_verified_at": binding_verified_at_canonical,
                "binding_scope": binding_scope,
                "replacement_policy": policy,
                "failure_type": task.get("failure_type"),
                "status": "ready" if not reasons else "blocked",
                "blocked_reasons": reasons,
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
    def _assert_secret_free_claimed_by(payload: dict[str, Any]) -> None:
        operator_token = settings.maitu_reconciliation_operator_token
        forbidden_values = (
            (operator_token.get_secret_value(),)
            if operator_token is not None and operator_token.get_secret_value()
            else ()
        )
        claimed_by = payload.get("claimed_by")
        if not isinstance(claimed_by, str) or contains_durable_secret(
            claimed_by,
            forbidden_values=forbidden_values,
        ):
            raise RetryLeaseConflictError("worker identity must not contain credentials")

    @staticmethod
    def _assert_current_retry_lease(task: dict[str, Any], payload: dict[str, Any]) -> None:
        MaituMaterialSlotRepository._assert_secret_free_claimed_by(payload)
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

    def _build_retry_operations_from_current_context(
        self,
        cursor: Any,
        task: dict[str, Any],
    ) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT rp.maitu_project_code, rp.target_live_room_id,
                   rp.scene_name AS plan_scene_name,
                   ms.scene_name AS slot_scene_name, ms.layer_name, ms.slot_name,
                   ms.target_live_room_id AS slot_target_live_room_id,
                   ms.target_clip_id, ms.target_layer_id, ms.expected_before_state,
                   ms.accepted_asset_types,
                   ms.replacement_policy AS slot_replacement_policy,
                   rpi.slot_name AS item_slot_name,
                   rpi.selected_asset_code AS item_selected_asset_code,
                   rpi.selected_asset_title,
                   rpi.replacement_policy AS item_replacement_policy,
                   a.asset_code AS binding_asset_code,
                   a.asset_type AS selected_asset_type,
                   a.status AS selected_asset_status,
                   a.maitu_material_id AS selected_asset_maitu_material_id,
                   a.source_material_type AS selected_asset_source_material_type,
                   a.maitu_binding_verification_source AS selected_asset_binding_verification_source,
                   a.maitu_binding_verified_at AS selected_asset_binding_verified_at,
                   a.maitu_binding_scope AS selected_asset_binding_scope
            FROM (SELECT 1) AS anchor
            LEFT JOIN maitu_replacement_plans rp
                ON rp.plan_code = %s AND rp.deleted_at IS NULL
            LEFT JOIN maitu_material_slots ms
                ON ms.slot_code = %s AND ms.deleted_at IS NULL
            LEFT JOIN maitu_replacement_plan_items rpi
                ON rpi.plan_code = %s AND rpi.slot_code = %s
            LEFT JOIN assets a
                ON a.asset_code = %s AND a.deleted_at IS NULL
            """,
            (
                task["plan_code"],
                task.get("slot_code"),
                task["plan_code"],
                task.get("slot_code"),
                task.get("asset_code"),
            ),
        )
        context = cursor.fetchone() or {}
        plan = {
            "maitu_project_code": context.get("maitu_project_code"),
            "target_live_room_id": context.get("target_live_room_id"),
            "scene_name": context.get("plan_scene_name"),
        }
        slot = {
            "scene_name": context.get("slot_scene_name"),
            "layer_name": context.get("layer_name"),
            "slot_name": context.get("slot_name"),
            "target_live_room_id": context.get("slot_target_live_room_id"),
            "target_clip_id": context.get("target_clip_id"),
            "target_layer_id": context.get("target_layer_id"),
            "expected_before_state": context.get("expected_before_state"),
            "accepted_asset_types": context.get("accepted_asset_types"),
            "replacement_policy": context.get("slot_replacement_policy"),
        }
        plan_item = {
            "slot_name": context.get("item_slot_name"),
            "selected_asset_code": context.get("item_selected_asset_code"),
            "binding_asset_code": context.get("binding_asset_code"),
            "selected_asset_type": context.get("selected_asset_type"),
            "selected_asset_status": context.get("selected_asset_status"),
            "selected_asset_title": context.get("selected_asset_title"),
            "selected_asset_maitu_material_id": context.get("selected_asset_maitu_material_id"),
            "selected_asset_source_material_type": context.get("selected_asset_source_material_type"),
            "selected_asset_binding_verification_source": context.get(
                "selected_asset_binding_verification_source"
            ),
            "selected_asset_binding_verified_at": context.get("selected_asset_binding_verified_at"),
            "selected_asset_binding_scope": context.get("selected_asset_binding_scope"),
            "replacement_policy": context.get("item_replacement_policy"),
        }
        return self._build_retry_operations(task, plan, slot, plan_item)

    @staticmethod
    def _operation_from_snapshot_row(
        snapshot: dict[str, Any],
        *,
        retry_task_code: str,
        operation_key: Any,
    ) -> dict[str, Any]:
        operation = snapshot.get("intent_payload")
        operator_token = settings.maitu_reconciliation_operator_token
        forbidden_values = (
            (operator_token.get_secret_value(),)
            if operator_token is not None and operator_token.get_secret_value()
            else ()
        )
        durable_payload = {
            key: value for key, value in operation.items() if key != "operation_fingerprint"
        } if isinstance(operation, dict) else operation
        if not isinstance(operation_key, str) or not isinstance(operation, dict) or not (
            operation.get("retry_task_code") == retry_task_code
            and operation.get("operation_key") == operation_key
            and operation.get("contract_version") == snapshot.get("contract_version")
            and operation.get("operation_type") == snapshot.get("operation_type")
            and operation.get("target_app") == snapshot.get("target_app")
            and operation.get("operation_fingerprint") == snapshot.get("intent_fingerprint")
            and operation.get("status") == snapshot.get("readiness_status")
            and operation.get("blocked_reasons") == snapshot.get("blocked_reasons")
            and is_canonical_retry_operation_intent(operation)
            and not contains_durable_secret(durable_payload, forbidden_values=forbidden_values)
        ):
            raise RetryCheckpointConflictError("stored retry operation intent is inconsistent")
        return operation

    def _find_authoritative_retry_operation(
        self,
        cursor: Any,
        task: dict[str, Any],
        operation_key: str,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT contract_version, operation_type, target_app, intent_fingerprint,
                   intent_payload, readiness_status, blocked_reasons
            FROM maitu_retry_operation_intents
            WHERE retry_task_code = %s AND operation_key = %s
            """,
            (task["retry_task_code"], operation_key),
        )
        snapshot = cursor.fetchone()
        if snapshot is not None:
            return self._operation_from_snapshot_row(
                snapshot,
                retry_task_code=task["retry_task_code"],
                operation_key=operation_key,
            )

        operation = next(
            (
                candidate
                for candidate in self._build_retry_operations_from_current_context(cursor, task)
                if candidate["operation_key"] == operation_key
            ),
            None,
        )
        if operation is None:
            raise RetryCheckpointConflictError("operation key is not present in the authoritative retry plan")
        operation = dict(operation)
        operation["status"] = "blocked"
        operation["blocked_reasons"] = [
            *operation.get("blocked_reasons", []),
            "missing_immutable_intent_snapshot",
        ]
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

    @classmethod
    def _completion_checkpoint_fingerprint(cls, checkpoint: dict[str, Any]) -> str | None:
        if not isinstance(checkpoint.get("completion_evidence"), dict):
            return None
        try:
            return cls._completion_payload_fingerprint(
                {
                    "attempt_id": checkpoint["attempt_id"],
                    "completion_id": checkpoint["completion_id"],
                    "operation_fingerprint": checkpoint["operation_fingerprint"],
                    "result_summary": checkpoint.get("completion_summary"),
                    "evidence": checkpoint["completion_evidence"],
                }
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _retry_execution_receipt_payload(payload: dict[str, Any]) -> dict[str, Any]:
        serializable = json.loads(
            json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)
        )
        claim_token = str(UUID(str(serializable.pop("claim_token"))))
        serializable["claim_token_fingerprint"] = hashlib.sha256(
            claim_token.encode("utf-8")
        ).hexdigest()
        return serializable

    @staticmethod
    def _retry_execution_receipt_payload_fingerprint(receipt_payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                receipt_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _retry_execution_receipt_fingerprint(cls, receipt: dict[str, Any]) -> str | None:
        result_payload = receipt.get("result_payload")
        if not isinstance(result_payload, dict):
            return None
        claim_token_fingerprint = result_payload.get("claim_token_fingerprint")
        if (
            not isinstance(claim_token_fingerprint, str)
            or len(claim_token_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in claim_token_fingerprint)
        ):
            return None
        try:
            if not (
                UUID(str(receipt["retry_execution_id"]))
                == UUID(str(result_payload["retry_execution_id"]))
                and receipt["claimed_by"] == result_payload["claimed_by"]
                and receipt["lease_version"] == result_payload["lease_version"]
                and receipt["retry_execution_status"]
                == result_payload["retry_execution_status"]
            ):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        return cls._retry_execution_receipt_payload_fingerprint(result_payload)

    @staticmethod
    def _assert_retry_execution_payload_token_free(payload: dict[str, Any]) -> None:
        operator_token = settings.maitu_reconciliation_operator_token
        forbidden_values = (
            (operator_token.get_secret_value(),)
            if operator_token is not None and operator_token.get_secret_value()
            else ()
        )
        durable_payload = {
            "claimed_by": payload.get("claimed_by"),
            **{
                key: payload.get(key)
                for key in (
                    "last_retry_execution_code",
                    "result_summary",
                    "error_message",
                    "screenshot_asset_code",
                    "retry_instruction",
                )
            },
        }
        if contains_durable_secret(durable_payload, forbidden_values=forbidden_values):
            raise RetryExecutionConflictError(
                "retry execution result durable fields must not contain credentials or the active claim token"
            )

    @staticmethod
    def _assert_verified_secret_free_evidence(
        evidence: Any,
        claim_token: Any,
        *,
        result_summary: Any = None,
    ) -> None:
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            raise RetryCheckpointConflictError("checkpoint evidence must be an authoritative verified readback")

        operator_token = settings.maitu_reconciliation_operator_token
        forbidden_values = (
            (operator_token.get_secret_value(),)
            if operator_token is not None and operator_token.get_secret_value()
            else ()
        )
        if contains_durable_secret(
            {
                "result_summary": result_summary,
                "evidence": evidence,
            },
            forbidden_values=forbidden_values,
        ):
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
        if converted.get("details") is None:
            converted["details"] = {}
        converted.setdefault("operations", [])
        return converted

    @staticmethod
    def _normalize_live_room_build_plan_operation(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        details = converted.get("details") if isinstance(converted.get("details"), dict) else {}
        script_layout_operation = details.get("script_layout_operation")
        if (
            details.get("contract_version") == "script_layout_operation_v1"
            and isinstance(script_layout_operation, dict)
        ):
            operation = dict(script_layout_operation)
            direct_db_fields = (
                "operation_type",
                "operation_name",
                "sort_order",
                "status",
                "scene_name",
                "required_category",
                "accepted_asset_types",
                "replacement_policy",
                "script_block_code",
                "instruction",
            )
            for key in direct_db_fields:
                value = converted.get(key)
                has_db_value = value is not None and value != []
                if has_db_value or key in operation:
                    operation[key] = value

            missing = object()

            def overlay_db_field(db_field: str, canonical_field: str, *alias_fields: str) -> None:
                db_value = converted.get(db_field)
                raw_value: Any = missing
                for field in (canonical_field, *alias_fields):
                    if field in operation:
                        if raw_value is missing:
                            raw_value = operation[field]
                        operation[field] = db_value
                if (raw_value is missing and db_value is not None) or (
                    raw_value is not missing and db_value != raw_value
                ):
                    operation[canonical_field] = db_value

            overlay_db_field("selected_asset_title", "selected_asset_title", "asset_title")
            overlay_db_field(
                "selected_asset_display_code",
                "selected_asset_display_code",
                "asset_display_code",
            )
            overlay_db_field(
                "selected_asset_local_file_code",
                "selected_asset_local_file_code",
                "asset_local_file_code",
            )
            overlay_db_field(
                "selected_asset_original_filename",
                "selected_asset_original_filename",
                "asset_original_filename",
            )
            overlay_db_field(
                "selected_asset_browser_use_hint",
                "selected_asset_browser_use_hint",
                "asset_browser_use_hint",
            )
            overlay_db_field("selection_source", "selection_source")
            db_layer_role = converted.get("layer_role")
            raw_layer_role = operation.get("layer_role", operation.get("layer_type"))
            if "layer_role" in operation:
                operation["layer_role"] = db_layer_role
            if "layer_type" in operation:
                operation["layer_type"] = db_layer_role
            if db_layer_role != raw_layer_role:
                operation["layer_role"] = db_layer_role
            db_layer_name = converted.get("layer_name")
            raw_layer_name = operation.get("layer_name", operation.get("layer_id"))
            if "layer_name" in operation:
                operation["layer_name"] = db_layer_name
            if "layer_id" in operation:
                operation["layer_id"] = db_layer_name
            if db_layer_name != raw_layer_name:
                operation["layer_name"] = db_layer_name
                operation["layer_id"] = db_layer_name
            db_asset_code = converted.get("selected_asset_code")
            raw_asset_code = operation.get("selected_asset_code", operation.get("asset_code"))
            if "selected_asset_code" in operation:
                operation["selected_asset_code"] = db_asset_code
            if "asset_code" in operation:
                operation["asset_code"] = db_asset_code
            if db_asset_code != raw_asset_code:
                operation["selected_asset_code"] = db_asset_code
                operation["asset_code"] = db_asset_code
            db_selected_asset_path = converted.get("selected_asset_local_relative_path")
            raw_selected_asset_path = operation.get(
                "selected_asset_path",
                operation.get(
                    "selected_asset_local_relative_path",
                    operation.get("asset_local_relative_path"),
                ),
            )
            if "selected_asset_path" in operation:
                operation["selected_asset_path"] = db_selected_asset_path
            if "selected_asset_local_relative_path" in operation:
                operation["selected_asset_local_relative_path"] = db_selected_asset_path
            if "asset_local_relative_path" in operation:
                operation["asset_local_relative_path"] = db_selected_asset_path
            if db_selected_asset_path != raw_selected_asset_path:
                operation["selected_asset_local_relative_path"] = db_selected_asset_path
            match_score = converted.get("match_score")
            if match_score is not None or "match_score" in operation:
                operation["match_score"] = float(match_score) if isinstance(match_score, Decimal) else match_score
            match_reasons = list(converted.get("match_reasons") or [])
            if match_reasons or "match_reasons" in operation:
                operation["match_reasons"] = match_reasons
            db_script_content = converted.get("script_block_content")
            raw_script_content = operation.get("script_block_content", operation.get("script_text"))
            if "script_block_content" in operation:
                operation["script_block_content"] = db_script_content
            if "script_text" in operation:
                operation["script_text"] = db_script_content
            if db_script_content != raw_script_content:
                operation["script_block_content"] = db_script_content
            return operation
        public_fields = {
            "operation_type",
            "operation_name",
            "sort_order",
            "status",
            "scene_name",
            "layer_name",
            "layer_role",
            "required_category",
            "accepted_asset_types",
            "replacement_policy",
            "selected_asset_code",
            "selected_asset_title",
            "selected_asset_display_code",
            "selected_asset_local_file_code",
            "selected_asset_original_filename",
            "selected_asset_local_relative_path",
            "selected_asset_browser_use_hint",
            "match_score",
            "match_reasons",
            "selection_source",
            "script_block_code",
            "script_block_content",
            "target_live_room_id",
            "scene_index",
            "layer_id",
            "layer_type",
            "need_type",
            "asset_code",
            "asset_display_code",
            "asset_local_file_code",
            "asset_original_filename",
            "asset_local_relative_path",
            "asset_browser_use_hint",
            "material_id",
            "maitu_material_id",
            "maitu_source_material_id",
            "source_material_type",
            "source_material_url",
            "source_cover_url",
            "speaker_id",
            "digital_human_image_id",
            "x",
            "y",
            "width",
            "height",
            "z_index",
            "script_text",
            "blocked_reason",
            "blocks_execution",
            "instruction",
            "details",
        }
        converted = {key: value for key, value in converted.items() if key in public_fields}
        converted["details"] = details
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
        details = converted.get("details") if isinstance(converted.get("details"), dict) else {}
        converted["details"] = details
        converted["ready_for_go_live"] = bool(details.get("ready_for_go_live", False))
        converted["manual_review_required"] = bool(details.get("manual_review_required", False))
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
        details = converted.get("details") if isinstance(converted.get("details"), dict) else {}
        converted = {**details, **converted}
        converted["details"] = details
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
