from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.services.code_generator import (
    BusinessObjectType,
    format_maitu_execution_code,
    format_maitu_plan_code,
    format_maitu_retry_task_code,
    format_maitu_slot_code,
)


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
                instruction = (
                    f"进入麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
                    f"找到{layer_name or slot_name or item['slot_code']}图层/槽位，"
                    f"将素材替换为 {item['selected_asset_code']}（{item.get('selected_asset_title') or '未命名素材'}），"
                    f"替换策略为 {policy}；保持原图层位置和尺寸不变，替换后保存项目。"
                )
                operations.append(
                    {
                        "operation_type": "replace_layer_asset",
                        "slot_code": item["slot_code"],
                        "slot_name": slot_name,
                        "scene_name": scene_name,
                        "layer_name": layer_name,
                        "asset_code": item.get("selected_asset_code"),
                        "asset_title": item.get("selected_asset_title"),
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
                    SELECT rt.retry_task_code
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
                    claim_expires_at = now() + (%s * interval '1 second'), updated_at = now()
                FROM candidate
                WHERE rt.retry_task_code = candidate.retry_task_code
                RETURNING rt.retry_task_code
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            return None
        return self._get_retry_queue_item_by_code(row["retry_task_code"])

    def reclaim_expired_retry_tasks(self) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_execution_retry_tasks
                SET status = 'pending', claimed_by = NULL, claimed_at = NULL,
                    claim_expires_at = NULL, updated_at = now()
                WHERE deleted_at IS NULL
                    AND status = 'in_progress'
                    AND claim_expires_at IS NOT NULL
                    AND claim_expires_at < now()
                RETURNING retry_task_code
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

    def release_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        assignments = ["status = %s", "claimed_by = NULL", "claimed_at = NULL", "claim_expires_at = NULL"]
        values: list[Any] = [payload.get("status", "pending")]
        if "result_summary" in payload:
            assignments.append("result_summary = %s")
            values.append(payload["result_summary"])
        values.append(retry_task_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE maitu_execution_retry_tasks
                SET {', '.join(assignments)}, updated_at = now()
                WHERE retry_task_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_retry_task(row) if row else None

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
        writable_fields = (
            "status",
            "retry_attempt_count",
            "last_retry_execution_code",
            "result_summary",
            "retry_instruction",
        )
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
                WHERE retry_task_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_retry_task(row) if row else None

    def get_retry_task_browser_use_operation_plan(self, retry_task_code: str) -> dict[str, Any] | None:
        task = self.get_retry_task_by_code(retry_task_code)
        if task is None:
            return None

        plan = self.get_replacement_plan_by_code(task["plan_code"]) or {}
        slot = self.get_by_code(task["slot_code"]) if task.get("slot_code") else None
        plan_items = plan.get("items", [])
        plan_item = next((item for item in plan_items if item.get("slot_code") == task.get("slot_code")), {})
        scene_name = (slot or {}).get("scene_name") or plan.get("scene_name")
        layer_name = (slot or {}).get("layer_name")
        slot_name = plan_item.get("slot_name") or (slot or {}).get("slot_name")
        asset_title = plan_item.get("selected_asset_title")
        policy = plan_item.get("replacement_policy") or (slot or {}).get("replacement_policy") or "keep_layout"
        status = "ready" if task.get("retryable") and task.get("status") in {"pending", "in_progress"} else "blocked"
        operation_type = self._retry_operation_type_for_failure(task.get("failure_type"))
        instruction = (
            f"执行重试任务 {retry_task_code}：{task.get('retry_instruction') or '按失败原因重试'}；"
            f"进入麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
            f"只重试槽位 {task.get('slot_code') or '整体执行'}，找到 {layer_name or slot_name or '目标图层/槽位'}，"
            f"将素材替换为 {task.get('asset_code') or '原计划素材'}（{asset_title or '未命名素材'}），"
            f"替换策略为 {policy}；保持原图层位置和尺寸不变，替换后保存项目。"
        )
        return {
            "retry_task_code": retry_task_code,
            "plan_code": task["plan_code"],
            "execution_code": task["execution_code"],
            "executor": task.get("executor", "browser_use"),
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": scene_name,
            "operations": [
                {
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
                    "instruction": instruction,
                }
            ],
        }

    def create_retry_task_execution_result(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.get_retry_task_by_code(retry_task_code) is None:
            return None
        data = {
            "status": self._retry_task_status_from_execution(payload["retry_execution_status"]),
            "retry_attempt_count_increment": 1,
        }
        optional_fields = (
            "last_retry_execution_code",
            "result_summary",
            "error_message",
            "screenshot_asset_code",
            "retry_instruction",
        )
        for field in optional_fields:
            if field in payload:
                data[field] = payload[field]

        assignments = ["status = %s", "retry_attempt_count = retry_attempt_count + %s"]
        values: list[Any] = [data["status"], data["retry_attempt_count_increment"]]
        for field in optional_fields:
            if field in data:
                assignments.append(f"{field} = %s")
                values.append(data[field])
        values.append(retry_task_code)

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE maitu_execution_retry_tasks
                SET {', '.join(assignments)}, updated_at = now()
                WHERE retry_task_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._normalize_retry_task(row) if row else None

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
        }
        return mapping.get(retry_execution_status, retry_execution_status)

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
    def _normalize_operation_result(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
        if converted.get("details") is None:
            converted["details"] = {}
        return converted

    @staticmethod
    def _normalize_retry_task(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted and converted["id"] is not None:
            converted["id"] = str(converted["id"])
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
