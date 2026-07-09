from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import maitu
from app.main import app


class FakeMaituMaterialSlotRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.executions: dict[str, dict[str, Any]] = {}
        self.retry_tasks: dict[str, dict[str, Any]] = {}
        self.assets: list[dict[str, Any]] = [
            {
                "asset_code": "AG-IMG-20260707-000001",
                "asset_type": "IMG",
                "title": "胶原蛋白商品主图-白底款",
                "original_filename": "collagen-main.png",
                "maitu_category": "product_image",
                "maitu_project_code": "MT-PROJ-20260707-000001",
                "maitu_scene_name": "京东空白直播间",
                "maitu_layer_name": "layer_8",
                "maitu_slot_name": "商品主图",
                "maitu_slot_code": "MT-SLOT-20260707-000001",
                "layer_width": 460,
                "layer_height": 460,
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-IMG-20260707-000002",
                "asset_type": "IMG",
                "title": "通用商品图",
                "original_filename": "product-generic.png",
                "maitu_category": "product_image",
                "maitu_project_code": None,
                "maitu_scene_name": None,
                "maitu_layer_name": None,
                "maitu_slot_name": None,
                "maitu_slot_code": None,
                "layer_width": None,
                "layer_height": None,
                "replacement_policy": "keep_layout",
            },
        ]

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = f"MT-SLOT-20260707-{len(self.rows) + 1:06d}"
        row = {
            "id": "81000000-0000-0000-0000-000000000001",
            "slot_code": code,
            "slot_name": payload["slot_name"],
            "maitu_project_code": payload.get("maitu_project_code"),
            "scene_name": payload.get("scene_name"),
            "scene_index": payload.get("scene_index"),
            "layer_name": payload.get("layer_name"),
            "layer_index": payload.get("layer_index"),
            "required_category": payload["required_category"],
            "accepted_asset_types": payload.get("accepted_asset_types", []),
            "aspect_ratio": payload.get("aspect_ratio"),
            "left_position": payload.get("left_position"),
            "top_position": payload.get("top_position"),
            "width": payload.get("width"),
            "height": payload.get("height"),
            "z_index": payload.get("z_index"),
            "replacement_policy": payload.get("replacement_policy", "keep_layout"),
            "description": payload.get("description"),
        }
        self.rows[code] = row
        return row

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
        rows = list(self.rows.values())
        if maitu_project_code is not None:
            rows = [row for row in rows if row.get("maitu_project_code") == maitu_project_code]
        if scene_name is not None:
            rows = [row for row in rows if row.get("scene_name") == scene_name]
        if required_category is not None:
            rows = [row for row in rows if row.get("required_category") == required_category]
        if slot_name is not None:
            rows = [row for row in rows if row.get("slot_name") == slot_name]
        if q:
            rows = [
                row
                for row in rows
                if q in row["slot_code"]
                or q in row["slot_name"]
                or q in (row.get("scene_name") or "")
                or q in (row.get("layer_name") or "")
                or q in (row.get("description") or "")
            ]
        return rows[offset : offset + limit]

    def get_by_code(self, slot_code: str) -> dict[str, Any] | None:
        return self.rows.get(slot_code)

    def update(self, slot_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.rows.get(slot_code)
        if row is None:
            return None
        row.update(payload)
        return row

    def soft_delete(self, slot_code: str) -> bool:
        return self.rows.pop(slot_code, None) is not None

    def list_candidate_assets(self, slot_code: str, *, limit: int = 20, offset: int = 0) -> dict[str, Any] | None:
        slot = self.rows.get(slot_code)
        if slot is None:
            return None
        assets = []
        for asset in self.assets:
            if asset["maitu_category"] != slot["required_category"]:
                continue
            if slot.get("accepted_asset_types") and asset["asset_type"] not in slot["accepted_asset_types"]:
                continue
            score = 0.5
            reasons = [f"maitu_category matches required_category: {slot['required_category']}"]
            if asset["asset_type"] in slot.get("accepted_asset_types", []):
                score += 0.2
                reasons.append(f"asset_type accepted: {asset['asset_type']}")
            if asset.get("maitu_project_code") == slot.get("maitu_project_code"):
                score += 0.1
                reasons.append(f"maitu_project_code matches: {slot['maitu_project_code']}")
            if asset.get("maitu_scene_name") == slot.get("scene_name"):
                score += 0.1
                reasons.append(f"scene_name matches: {slot['scene_name']}")
            if asset.get("maitu_slot_code") == slot_code:
                score += 0.1
                reasons.append(f"maitu_slot_code matches: {slot_code}")
            assets.append({**asset, "match_score": round(score, 4), "match_reasons": reasons})
        assets.sort(key=lambda row: row["match_score"], reverse=True)
        return {
            "slot_code": slot_code,
            "required_category": slot["required_category"],
            "accepted_asset_types": slot.get("accepted_asset_types", []),
            "assets": assets[offset : offset + limit],
        }

    def create_replacement_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = f"MT-PLAN-20260707-{len(self.plans) + 1:06d}"
        slot_codes = payload.get("slot_codes") or list(self.rows.keys())
        slots = [self.rows[slot_code] for slot_code in slot_codes if slot_code in self.rows]
        items = []
        for sort_order, slot in enumerate(slots):
            candidates = self.list_candidate_assets(slot["slot_code"], limit=1)
            candidate = candidates["assets"][0] if candidates and candidates["assets"] else None
            items.append(
                {
                    "slot_code": slot["slot_code"],
                    "slot_name": slot.get("slot_name"),
                    "required_category": slot.get("required_category"),
                    "selected_asset_code": candidate.get("asset_code") if candidate else None,
                    "selected_asset_title": candidate.get("title") if candidate else None,
                    "match_score": candidate.get("match_score") if candidate else None,
                    "match_reasons": candidate.get("match_reasons", []) if candidate else [],
                    "replacement_policy": candidate.get("replacement_policy") if candidate else slot.get("replacement_policy"),
                    "sort_order": sort_order,
                    "status": "selected" if candidate else "missing",
                }
            )
        plan = {
            "id": "82000000-0000-0000-0000-000000000001",
            "plan_code": code,
            "plan_name": payload["plan_name"],
            "maitu_project_code": payload.get("maitu_project_code"),
            "scene_name": payload.get("scene_name"),
            "status": "draft",
            "strategy": payload.get("strategy", "best_match"),
            "description": payload.get("description"),
            "items": items,
        }
        self.plans[code] = plan
        return plan

    def list_replacement_plans(
        self,
        *,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.plans.values())
        if maitu_project_code is not None:
            rows = [row for row in rows if row.get("maitu_project_code") == maitu_project_code]
        if scene_name is not None:
            rows = [row for row in rows if row.get("scene_name") == scene_name]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    def get_replacement_plan_by_code(self, plan_code: str) -> dict[str, Any] | None:
        return self.plans.get(plan_code)

    def get_browser_use_operation_plan(self, plan_code: str) -> dict[str, Any] | None:
        plan = self.plans.get(plan_code)
        if plan is None:
            return None
        operations = []
        for item in plan.get("items", []):
            slot = self.rows.get(item["slot_code"], {})
            if item.get("selected_asset_code"):
                instruction = (
                    f"进入麦兔项目 {plan.get('maitu_project_code')} 的“{slot.get('scene_name')}”场景，"
                    f"找到{slot.get('layer_name')}图层/槽位，将素材替换为 "
                    f"{item['selected_asset_code']}（{item.get('selected_asset_title')}），"
                    f"替换策略为 {item.get('replacement_policy')}；保持原图层位置和尺寸不变，替换后保存项目。"
                )
                operations.append(
                    {
                        "operation_type": "replace_layer_asset",
                        "slot_code": item["slot_code"],
                        "slot_name": item.get("slot_name"),
                        "scene_name": slot.get("scene_name"),
                        "layer_name": slot.get("layer_name"),
                        "asset_code": item.get("selected_asset_code"),
                        "asset_title": item.get("selected_asset_title"),
                        "replacement_policy": item.get("replacement_policy"),
                        "status": "ready",
                        "instruction": instruction,
                    }
                )
        return {
            "plan_code": plan_code,
            "executor": "browser_use",
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": plan.get("scene_name"),
            "operations": operations,
        }

    def create_execution_result(self, plan_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.plans.get(plan_code)
        if plan is None:
            return None
        execution_code = f"MT-EXEC-20260707-{len(self.executions) + 1:06d}"
        operation_results = []
        for sort_order, operation in enumerate(payload.get("operation_results", [])):
            operation_results.append(
                {
                    "id": f"83000000-0000-0000-0000-{sort_order + 1:012d}",
                    "slot_code": operation["slot_code"],
                    "operation_type": operation.get("operation_type", "replace_layer_asset"),
                    "asset_code": operation.get("asset_code"),
                    "status": operation["status"],
                    "failure_type": operation.get("failure_type"),
                    "retryable": operation.get("retryable", False),
                    "retry_instruction": operation.get("retry_instruction"),
                    "error_message": operation.get("error_message"),
                    "screenshot_asset_code": operation.get("screenshot_asset_code"),
                    "details": operation.get("details", {}),
                    "sort_order": sort_order,
                }
            )
        execution = {
            "id": "84000000-0000-0000-0000-000000000001",
            "execution_code": execution_code,
            "plan_code": plan_code,
            "executor": payload.get("executor", "browser_use"),
            "execution_status": payload["execution_status"],
            "failure_type": payload.get("failure_type"),
            "retryable": payload.get("retryable", False),
            "retry_instruction": payload.get("retry_instruction"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "error_message": payload.get("error_message"),
            "screenshot_asset_code": payload.get("screenshot_asset_code"),
            "result_summary": payload.get("result_summary"),
            "operation_results": operation_results,
            "created_at": None,
        }
        plan["status"] = "executed" if payload["execution_status"] == "succeeded" else "execution_failed"
        self.executions[execution_code] = execution
        self._create_retry_tasks_for_execution(execution)
        return execution

    def list_execution_results(
        self,
        plan_code: str,
        *,
        executor: str | None = None,
        execution_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if plan_code not in self.plans:
            return None
        rows = [row for row in self.executions.values() if row["plan_code"] == plan_code]
        if executor is not None:
            rows = [row for row in rows if row["executor"] == executor]
        if execution_status is not None:
            rows = [row for row in rows if row["execution_status"] == execution_status]
        return rows[offset : offset + limit]

    def get_execution_result_by_code(self, plan_code: str, execution_code: str) -> dict[str, Any] | None:
        execution = self.executions.get(execution_code)
        if execution is None or execution["plan_code"] != plan_code:
            return None
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
        rows = list(self.retry_tasks.values())
        if plan_code is not None:
            rows = [row for row in rows if row["plan_code"] == plan_code]
        if execution_code is not None:
            rows = [row for row in rows if row["execution_code"] == execution_code]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if failure_type is not None:
            rows = [row for row in rows if row["failure_type"] == failure_type]
        return rows[offset : offset + limit]

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
        rows = []
        for task in self.retry_tasks.values():
            if not task.get("retryable") or task.get("retry_attempt_count", 0) >= max_attempts:
                continue
            if status is not None and task.get("status") != status:
                continue
            if failure_type is not None and task.get("failure_type") != failure_type:
                continue
            plan = self.plans.get(task["plan_code"], {})
            slot = self.rows.get(task.get("slot_code"), {}) if task.get("slot_code") else {}
            project_code = slot.get("maitu_project_code") or plan.get("maitu_project_code")
            task_scene_name = slot.get("scene_name") or plan.get("scene_name")
            if maitu_project_code is not None and project_code != maitu_project_code:
                continue
            if scene_name is not None and task_scene_name != scene_name:
                continue
            rows.append(
                {
                    **task,
                    "maitu_project_code": project_code,
                    "scene_name": task_scene_name,
                    "slot_name": slot.get("slot_name"),
                    "layer_name": slot.get("layer_name"),
                    "next_operation_type": {
                        "missing_layer": "retry_replace_layer_asset",
                        "selector_changed": "retry_replace_layer_asset",
                        "asset_upload_failed": "retry_asset_upload_and_replace",
                        "save_failed": "retry_save_project",
                        "login_expired": "recover_login_then_retry",
                    }.get(task.get("failure_type"), "retry_browser_use_operation"),
                    "browser_use_operations_url": f"/api/maitu/retry-tasks/{task['retry_task_code']}/browser-use-operations",
                }
            )
        rows.sort(key=lambda row: (row["retry_attempt_count"], row["retry_task_code"]))
        return rows[offset : offset + limit]

    def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        rows = self.list_retry_queue(
            failure_type=payload.get("failure_type"),
            maitu_project_code=payload.get("maitu_project_code"),
            scene_name=payload.get("scene_name"),
            max_attempts=payload.get("max_attempts", 3),
            limit=1,
        )
        if not rows:
            return None
        task = self.retry_tasks[rows[0]["retry_task_code"]]
        task["status"] = "in_progress"
        task["claimed_by"] = payload["claimed_by"]
        task["claimed_at"] = "2026-07-07T09:00:00Z"
        task["claim_expires_at"] = "2026-07-07T09:15:00Z"
        return {**rows[0], **task}

    def reclaim_expired_retry_tasks(self) -> dict[str, Any]:
        reclaimed_codes = []
        for task in self.retry_tasks.values():
            if task.get("status") == "in_progress" and task.get("claim_expires_at") is not None:
                task["status"] = "pending"
                task["claimed_by"] = None
                task["claimed_at"] = None
                task["claim_expires_at"] = None
                reclaimed_codes.append(task["retry_task_code"])
        return {"reclaimed_count": len(reclaimed_codes), "retry_task_codes": reclaimed_codes}

    def get_retry_worker_next(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        reclaim_result = self.reclaim_expired_retry_tasks()
        retry_task = self.claim_next_retry_task(payload)
        if retry_task is None:
            return None
        operation_plan = self.get_retry_task_browser_use_operation_plan(retry_task["retry_task_code"])
        return {
            "reclaimed_count": reclaim_result["reclaimed_count"],
            "reclaimed_retry_task_codes": reclaim_result["retry_task_codes"],
            "retry_task": retry_task,
            "operation_plan": operation_plan,
        }

    def release_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        task["status"] = payload.get("status", "pending")
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["claim_expires_at"] = None
        if payload.get("result_summary") is not None:
            task["result_summary"] = payload["result_summary"]
        return task

    def get_retry_task_by_code(self, retry_task_code: str) -> dict[str, Any] | None:
        return self.retry_tasks.get(retry_task_code)

    def update_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        task.update(payload)
        return task

    def get_retry_task_browser_use_operation_plan(self, retry_task_code: str) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        plan = self.plans.get(task["plan_code"], {})
        slot = self.rows.get(task.get("slot_code"), {}) if task.get("slot_code") else {}
        plan_item = next(
            (item for item in plan.get("items", []) if item.get("slot_code") == task.get("slot_code")),
            {},
        )
        operation_type = {
            "missing_layer": "retry_replace_layer_asset",
            "selector_changed": "retry_replace_layer_asset",
            "asset_upload_failed": "retry_asset_upload_and_replace",
            "save_failed": "retry_save_project",
            "login_expired": "recover_login_then_retry",
        }.get(task.get("failure_type"), "retry_browser_use_operation")
        scene_name = slot.get("scene_name") or plan.get("scene_name")
        layer_name = slot.get("layer_name")
        asset_title = plan_item.get("selected_asset_title")
        policy = plan_item.get("replacement_policy") or slot.get("replacement_policy") or "keep_layout"
        instruction = (
            f"执行重试任务 {retry_task_code}：{task.get('retry_instruction') or '按失败原因重试'}；"
            f"进入麦兔项目 {plan.get('maitu_project_code') or '当前项目'} 的“{scene_name or '当前场景'}”场景，"
            f"只重试槽位 {task.get('slot_code') or '整体执行'}，找到 {layer_name or '目标图层/槽位'}，"
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
                    "slot_name": slot.get("slot_name"),
                    "scene_name": scene_name,
                    "layer_name": layer_name,
                    "asset_code": task.get("asset_code"),
                    "asset_title": asset_title,
                    "replacement_policy": policy,
                    "failure_type": task.get("failure_type"),
                    "status": "ready" if task.get("retryable") and task.get("status") in {"pending", "in_progress"} else "blocked",
                    "instruction": instruction,
                }
            ],
        }

    def create_retry_task_execution_result(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        status_map = {
            "succeeded": "succeeded",
            "failed": "failed",
            "manual_required": "manual_required",
        }
        task["status"] = status_map.get(payload["retry_execution_status"], payload["retry_execution_status"])
        task["retry_attempt_count"] += 1
        if payload.get("last_retry_execution_code") is not None:
            task["last_retry_execution_code"] = payload["last_retry_execution_code"]
        if payload.get("result_summary") is not None:
            task["result_summary"] = payload["result_summary"]
        if payload.get("error_message") is not None:
            task["error_message"] = payload["error_message"]
        if payload.get("screenshot_asset_code") is not None:
            task["screenshot_asset_code"] = payload["screenshot_asset_code"]
        if payload.get("retry_instruction") is not None:
            task["retry_instruction"] = payload["retry_instruction"]
        return task

    def _create_retry_tasks_for_execution(self, execution: dict[str, Any]) -> None:
        retryable_operations = [operation for operation in execution["operation_results"] if operation.get("retryable")]
        if retryable_operations:
            for operation in retryable_operations:
                self._create_retry_task(execution, operation)
            return
        if execution.get("retryable"):
            self._create_retry_task(execution, None)

    def _create_retry_task(self, execution: dict[str, Any], operation: dict[str, Any] | None) -> None:
        code = f"MT-RETRY-20260707-{len(self.retry_tasks) + 1:06d}"
        source = operation or execution
        task = {
            "id": f"85000000-0000-0000-0000-{len(self.retry_tasks) + 1:012d}",
            "retry_task_code": code,
            "plan_code": execution["plan_code"],
            "execution_code": execution["execution_code"],
            "slot_code": operation.get("slot_code") if operation else None,
            "asset_code": operation.get("asset_code") if operation else None,
            "executor": execution["executor"],
            "failure_type": source.get("failure_type"),
            "retryable": True,
            "retry_instruction": source.get("retry_instruction"),
            "status": "pending",
            "error_message": source.get("error_message"),
            "screenshot_asset_code": source.get("screenshot_asset_code"),
            "retry_attempt_count": 0,
            "last_retry_execution_code": None,
            "result_summary": None,
            "claimed_by": None,
            "claimed_at": None,
            "claim_expires_at": None,
            "created_at": None,
            "updated_at": None,
        }
        self.retry_tasks[code] = task


@pytest.fixture
def client() -> TestClient:
    repository = FakeMaituMaterialSlotRepository()
    app.dependency_overrides[maitu.get_maitu_slot_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_list_get_update_and_delete_maitu_slot(client: TestClient) -> None:
    create_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "scene_index": 0,
            "layer_name": "layer_8",
            "layer_index": 8,
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
            "aspect_ratio": "1:1",
            "left_position": 840,
            "top_position": 180,
            "width": 460,
            "height": 460,
            "z_index": 8,
            "replacement_policy": "keep_layout",
            "description": "麦兔直播间中的商品主图槽位，只替换素材，不改布局。",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["slot_code"] == "MT-SLOT-20260707-000001"
    assert created["required_category"] == "product_image"
    assert created["accepted_asset_types"] == ["IMG"]
    assert created["replacement_policy"] == "keep_layout"

    list_response = client.get(
        "/api/maitu/slots",
        params={
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "required_category": "product_image",
            "slot_name": "商品主图",
            "q": "商品主图",
        },
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["slot_code"] == created["slot_code"]

    get_response = client.get(f"/api/maitu/slots/{created['slot_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["layer_name"] == "layer_8"

    update_response = client.patch(
        f"/api/maitu/slots/{created['slot_code']}",
        json={"replacement_policy": "fit_contain", "description": "商品主图允许等比适配。"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["replacement_policy"] == "fit_contain"

    candidates_response = client.get(f"/api/maitu/slots/{created['slot_code']}/candidate-assets")
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert candidates["slot_code"] == created["slot_code"]
    assert candidates["required_category"] == "product_image"
    assert candidates["accepted_asset_types"] == ["IMG"]
    assert candidates["assets"][0]["asset_code"] == "AG-IMG-20260707-000001"
    assert candidates["assets"][0]["match_score"] == 1.0
    assert "maitu_slot_code matches" in candidates["assets"][0]["match_reasons"][-1]

    delete_response = client.delete(f"/api/maitu/slots/{created['slot_code']}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/api/maitu/slots/{created['slot_code']}")
    assert missing_response.status_code == 404


def test_get_missing_maitu_slot_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/slots/MT-SLOT-20260707-999999")

    assert response.status_code == 404


def test_create_list_and_get_replacement_plan(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]

    create_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "京东空白直播间商品素材替换方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
            "strategy": "best_match",
            "description": "自动为麦兔模板选择商品主图素材。",
        },
    )

    assert create_response.status_code == 201
    plan = create_response.json()
    assert plan["plan_code"] == "MT-PLAN-20260707-000001"
    assert plan["items"][0]["slot_code"] == slot_code
    assert plan["items"][0]["selected_asset_code"] == "AG-IMG-20260707-000001"
    assert plan["items"][0]["status"] == "selected"

    list_response = client.get(
        "/api/maitu/replacement-plans",
        params={"maitu_project_code": "MT-PROJ-20260707-000001", "status": "draft"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["plan_code"] == plan["plan_code"]

    get_response = client.get(f"/api/maitu/replacement-plans/{plan['plan_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["items"][0]["match_score"] == 1.0

    operations_response = client.get(f"/api/maitu/replacement-plans/{plan['plan_code']}/browser-use-operations")
    assert operations_response.status_code == 200
    operations = operations_response.json()
    assert operations["executor"] == "browser_use"
    assert operations["target_app"] == "maitu"
    assert operations["operations"][0]["operation_type"] == "replace_layer_asset"
    assert operations["operations"][0]["asset_code"] == "AG-IMG-20260707-000001"
    assert "Browser" not in operations["operations"][0]["instruction"]
    assert "保持原图层位置和尺寸不变" in operations["operations"][0]["instruction"]


def test_create_list_and_get_browser_use_execution_result(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]

    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "京东空白直播间商品素材替换方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    plan_code = plan_response.json()["plan_code"]

    create_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "succeeded",
            "started_at": "2026-07-07T09:00:00Z",
            "finished_at": "2026-07-07T09:02:00Z",
            "screenshot_asset_code": "AG-IMG-20260707-000099",
            "result_summary": "Browser use 已在麦兔中完成商品主图替换并保存项目。",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "succeeded",
                    "screenshot_asset_code": "AG-IMG-20260707-000099",
                    "details": {"layer_name": "layer_8", "saved": True},
                }
            ],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["execution_code"] == "MT-EXEC-20260707-000001"
    assert created["executor"] == "browser_use"
    assert created["execution_status"] == "succeeded"
    assert created["operation_results"][0]["slot_code"] == slot_code
    assert created["operation_results"][0]["status"] == "succeeded"
    assert created["operation_results"][0]["details"]["saved"] is True

    list_response = client.get(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        params={"executor": "browser_use", "execution_status": "succeeded"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["execution_code"] == created["execution_code"]

    get_response = client.get(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results/{created['execution_code']}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["result_summary"].startswith("Browser use 已在麦兔中完成")

    refreshed_plan_response = client.get(f"/api/maitu/replacement-plans/{plan_code}")
    assert refreshed_plan_response.status_code == 200
    assert refreshed_plan_response.json()["status"] == "executed"


def test_failed_browser_use_execution_classifies_failure_and_creates_retry_task(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={"plan_name": "失败可重试方案", "slot_codes": [slot_code]},
    )
    plan_code = plan_response.json()["plan_code"]

    create_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "failure_type": "missing_layer",
            "retryable": True,
            "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后只重试该槽位。",
            "result_summary": "商品主图图层未定位成功，其他步骤跳过。",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                    "details": {"layer_name": "layer_8", "selector": None},
                }
            ],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["execution_status"] == "partial_failed"
    assert created["failure_type"] == "missing_layer"
    assert created["retryable"] is True
    assert "重新扫描麦兔场景图层树" in created["retry_instruction"]
    assert created["operation_results"][0]["failure_type"] == "missing_layer"
    assert created["operation_results"][0]["retryable"] is True

    retry_list_response = client.get(
        "/api/maitu/retry-tasks",
        params={"plan_code": plan_code, "status": "pending", "failure_type": "missing_layer"},
    )
    assert retry_list_response.status_code == 200
    retry_task = retry_list_response.json()[0]
    assert retry_task["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert retry_task["plan_code"] == plan_code
    assert retry_task["execution_code"] == created["execution_code"]
    assert retry_task["slot_code"] == slot_code
    assert retry_task["failure_type"] == "missing_layer"
    assert retry_task["retryable"] is True
    assert retry_task["status"] == "pending"
    assert "定位 layer_8" in retry_task["retry_instruction"]

    get_retry_response = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}")
    assert get_retry_response.status_code == 200
    assert get_retry_response.json()["error_message"] == "Browser use 未找到 layer_8。"

    update_retry_response = client.patch(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}",
        json={
            "status": "in_progress",
            "retry_attempt_count": 1,
            "last_retry_execution_code": created["execution_code"],
            "result_summary": "已交给 Browser use 重新定位 layer_8。",
        },
    )
    assert update_retry_response.status_code == 200
    assert update_retry_response.json()["status"] == "in_progress"
    assert update_retry_response.json()["retry_attempt_count"] == 1


def test_retry_task_browser_use_operations_plan_contains_minimal_retry_steps(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "商品主图重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    plan_code = plan_response.json()["plan_code"]
    execution_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    retry_task = client.get(
        "/api/maitu/retry-tasks",
        params={"execution_code": execution_response.json()["execution_code"]},
    ).json()[0]

    response = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations")

    assert response.status_code == 200
    operation_plan = response.json()
    assert operation_plan["retry_task_code"] == retry_task["retry_task_code"]
    assert operation_plan["plan_code"] == plan_code
    assert operation_plan["execution_code"] == execution_response.json()["execution_code"]
    assert operation_plan["executor"] == "browser_use"
    assert operation_plan["target_app"] == "maitu"
    operation = operation_plan["operations"][0]
    assert operation["operation_type"] == "retry_replace_layer_asset"
    assert operation["slot_code"] == slot_code
    assert operation["layer_name"] == "layer_8"
    assert operation["asset_code"] == "AG-IMG-20260707-000001"
    assert operation["asset_title"] == "胶原蛋白商品主图-白底款"
    assert operation["failure_type"] == "missing_layer"
    assert operation["status"] == "ready"
    assert "重试任务" in operation["instruction"]
    assert "只重试槽位" in operation["instruction"]
    assert "保持原图层位置和尺寸不变" in operation["instruction"]


def test_retry_task_execution_result_updates_task_status_and_attempt_count(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={"plan_name": "商品主图重试结果方案", "slot_codes": [slot_code]},
    )
    plan_code = plan_response.json()["plan_code"]
    execution_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    retry_task = client.get(
        "/api/maitu/retry-tasks",
        params={"execution_code": execution_response.json()["execution_code"]},
    ).json()[0]

    callback_response = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results",
        json={
            "retry_execution_status": "succeeded",
            "last_retry_execution_code": "MT-EXEC-20260707-000002",
            "result_summary": "Browser use 重新定位 layer_8 后已完成商品主图替换并保存项目。",
            "screenshot_asset_code": "AG-IMG-20260707-000199",
        },
    )

    assert callback_response.status_code == 200
    updated = callback_response.json()
    assert updated["retry_task_code"] == retry_task["retry_task_code"]
    assert updated["status"] == "succeeded"
    assert updated["retry_attempt_count"] == 1
    assert updated["last_retry_execution_code"] == "MT-EXEC-20260707-000002"
    assert updated["result_summary"].startswith("Browser use 重新定位")
    assert updated["screenshot_asset_code"] == "AG-IMG-20260707-000199"

    get_response = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "succeeded"


def test_retry_queue_lists_only_pending_retryable_tasks_with_context(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "待重试队列方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    execution_response = client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    execution_code = execution_response.json()["execution_code"]

    queue_response = client.get(
        "/api/maitu/retry-queue",
        params={
            "failure_type": "missing_layer",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "max_attempts": 3,
        },
    )

    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert len(queue) == 1
    item = queue[0]
    assert item["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert item["execution_code"] == execution_code
    assert item["status"] == "pending"
    assert item["retryable"] is True
    assert item["failure_type"] == "missing_layer"
    assert item["maitu_project_code"] == "MT-PROJ-20260707-000001"
    assert item["scene_name"] == "京东空白直播间"
    assert item["slot_name"] == "商品主图"
    assert item["layer_name"] == "layer_8"
    assert item["next_operation_type"] == "retry_replace_layer_asset"
    assert item["browser_use_operations_url"].endswith("/browser-use-operations")

    client.patch(item["browser_use_operations_url"].removesuffix("/browser-use-operations"), json={"retry_attempt_count": 3})
    empty_queue_response = client.get("/api/maitu/retry-queue", params={"max_attempts": 3})
    assert empty_queue_response.status_code == 200
    assert empty_queue_response.json() == []


def test_retry_queue_claim_next_locks_task_and_release_unlocks_it(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "待领取重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )

    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={
            "claimed_by": "browser-use-worker-1",
            "lock_ttl_seconds": 900,
            "failure_type": "missing_layer",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "max_attempts": 3,
        },
    )

    assert claim_response.status_code == 200
    claimed = claim_response.json()
    assert claimed["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert claimed["status"] == "in_progress"
    assert claimed["claimed_by"] == "browser-use-worker-1"
    assert claimed["claimed_at"] is not None
    assert claimed["claim_expires_at"] is not None
    assert claimed["next_operation_type"] == "retry_replace_layer_asset"

    queue_after_claim = client.get("/api/maitu/retry-queue")
    assert queue_after_claim.status_code == 200
    assert queue_after_claim.json() == []

    release_response = client.post(
        f"/api/maitu/retry-tasks/{claimed['retry_task_code']}/release",
        json={"status": "pending", "result_summary": "worker heartbeat lost; release back to queue"},
    )
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["status"] == "pending"
    assert released["claimed_by"] is None
    assert released["claimed_at"] is None
    assert released["claim_expires_at"] is None
    assert released["result_summary"] == "worker heartbeat lost; release back to queue"


def test_retry_queue_reclaim_expired_unlocks_in_progress_tasks(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "过期领取重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={"claimed_by": "browser-use-worker-1", "lock_ttl_seconds": 900, "max_attempts": 3},
    )
    retry_task_code = claim_response.json()["retry_task_code"]

    reclaim_response = client.post("/api/maitu/retry-queue/reclaim-expired")

    assert reclaim_response.status_code == 200
    payload = reclaim_response.json()
    assert payload["reclaimed_count"] == 1
    assert payload["retry_task_codes"] == [retry_task_code]

    task_response = client.get(f"/api/maitu/retry-tasks/{retry_task_code}")
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["status"] == "pending"
    assert task["claimed_by"] is None
    assert task["claimed_at"] is None
    assert task["claim_expires_at"] is None


def test_retry_worker_next_reclaims_claims_and_returns_operation_plan(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "worker next 重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )

    response = client.post(
        "/api/maitu/retry-worker/next",
        json={
            "claimed_by": "browser-use-worker-1",
            "lock_ttl_seconds": 900,
            "failure_type": "missing_layer",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "max_attempts": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reclaimed_count"] == 0
    assert payload["reclaimed_retry_task_codes"] == []
    assert payload["retry_task"]["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert payload["retry_task"]["status"] == "in_progress"
    assert payload["retry_task"]["claimed_by"] == "browser-use-worker-1"
    assert payload["operation_plan"]["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert payload["operation_plan"]["operations"][0]["operation_type"] == "retry_replace_layer_asset"
    assert "只重试槽位" in payload["operation_plan"]["operations"][0]["instruction"]


@pytest.mark.parametrize("path", ["/api/maitu/retry-worker/next"])
def test_retry_worker_next_returns_404_when_no_task_available(client: TestClient, path: str) -> None:
    response = client.post(path, json={"claimed_by": "browser-use-worker-1"})

    assert response.status_code == 404


def test_release_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.post("/api/maitu/retry-tasks/MT-RETRY-20260707-999999/release", json={"status": "pending"})

    assert response.status_code == 404


def test_create_execution_result_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/replacement-plans/MT-PLAN-20260707-999999/execution-results",
        json={"execution_status": "failed", "error_message": "plan not found"},
    )

    assert response.status_code == 404


def test_get_missing_execution_result_returns_404(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={"slot_name": "商品主图", "required_category": "product_image", "accepted_asset_types": ["IMG"]},
    )
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={"plan_name": "测试方案", "slot_codes": [slot_response.json()["slot_code"]]},
    )
    plan_code = plan_response.json()["plan_code"]

    response = client.get(f"/api/maitu/replacement-plans/{plan_code}/execution-results/MT-EXEC-20260707-999999")

    assert response.status_code == 404


def test_list_execution_results_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/replacement-plans/MT-PLAN-20260707-999999/execution-results")

    assert response.status_code == 404


def test_get_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/retry-tasks/MT-RETRY-20260707-999999")

    assert response.status_code == 404


def test_update_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.patch("/api/maitu/retry-tasks/MT-RETRY-20260707-999999", json={"status": "cancelled"})

    assert response.status_code == 404


def test_get_browser_use_operations_for_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/retry-tasks/MT-RETRY-20260707-999999/browser-use-operations")

    assert response.status_code == 404


def test_create_execution_result_for_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/retry-tasks/MT-RETRY-20260707-999999/execution-results",
        json={"retry_execution_status": "failed", "error_message": "retry task not found"},
    )

    assert response.status_code == 404


def test_get_missing_replacement_plan_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/replacement-plans/MT-PLAN-20260707-999999")

    assert response.status_code == 404


def test_get_browser_use_operations_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/replacement-plans/MT-PLAN-20260707-999999/browser-use-operations")

    assert response.status_code == 404


def test_candidate_assets_for_missing_slot_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/slots/MT-SLOT-20260707-999999/candidate-assets")

    assert response.status_code == 404


class FakeSlotCandidateQwen3Client:
    embedding_model = "qwen3-embedding-4b-local"
    rerank_model = "qwen3-reranker-4b-local"

    def embed_texts(self, texts: list[str], *, is_query: bool = False, instruction: str | None = None, dimensions: int | None = None) -> list[list[float]]:
        assert is_query is True
        assert "商品讲解视频" in texts[0]
        assert "product_video" in texts[0]
        return [[1.0, 0.0, 0.0]]

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
        instruction: str | None = None,
        max_length: int | None = None,
        return_documents: bool = True,
    ) -> list[dict[str, Any]]:
        return []


def test_semantic_candidate_assets_for_slot_use_slot_context_and_retrieval_index(client: TestClient) -> None:
    from app.services.asset_candidates import AssetRetrievalIndex

    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品讲解视频",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "视频图层",
            "required_category": "product_video",
            "accepted_asset_types": ["VID"],
            "replacement_policy": "keep_layout",
            "description": "用于品酒大师商品讲解片段。",
        },
    )
    slot_code = slot_response.json()["slot_code"]
    index = AssetRetrievalIndex(
        entries=[
            {
                "document_id": "asset:AG-VID-20260709-000052:retrieval",
                "asset_code": "AG-VID-20260709-000052",
                "display_code": "MT-VID-0024",
                "local_file_code": "MT-VID-0024",
                "title": "视频 - 商品讲解视频 - 品酒大师PRO",
                "content": "品酒大师 商品讲解 视频 PRO",
                "content_hash": "hash-video",
                "metadata": {
                    "asset_type": "VID",
                    "maitu_category": "product_video",
                    "usage": "商品讲解视频",
                    "subject": "品酒大师PRO",
                    "local_relative_path": "视频/MT-VID-0024.mp4",
                },
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "document_id": "asset:AG-IMG-20260709-000001:retrieval",
                "asset_code": "AG-IMG-20260709-000001",
                "display_code": "MT-IMG-0001",
                "local_file_code": "MT-IMG-0001",
                "title": "图片 - 商品主图 - 品酒大师PRO",
                "content": "品酒大师 商品主图 图片",
                "content_hash": "hash-image",
                "metadata": {
                    "asset_type": "IMG",
                    "maitu_category": "product_image",
                    "usage": "商品主图",
                    "subject": "品酒大师PRO",
                    "local_relative_path": "图片/MT-IMG-0001.png",
                },
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [0.0, 1.0, 0.0],
            },
        ]
    )
    app.dependency_overrides[maitu.get_slot_asset_retrieval_index_factory] = lambda: lambda: index
    app.dependency_overrides[maitu.get_slot_candidate_qwen3_client_factory] = lambda: lambda: FakeSlotCandidateQwen3Client()
    try:
        response = client.get(
            f"/api/maitu/slots/{slot_code}/candidate-assets",
            params={"semantic": True, "limit": 1},
        )
    finally:
        app.dependency_overrides.pop(maitu.get_slot_asset_retrieval_index_factory, None)
        app.dependency_overrides.pop(maitu.get_slot_candidate_qwen3_client_factory, None)

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "semantic_retrieval"
    assert body["semantic_query"]
    assert body["embedding_model"] == "qwen3-embedding-4b-local"
    assert body["assets"][0]["asset_code"] == "AG-VID-20260709-000052"
    assert body["assets"][0]["display_code"] == "MT-VID-0024"
    assert body["assets"][0]["original_filename"] == "MT-VID-0024.mp4"
    assert body["assets"][0]["retrieval_score"] == 1.0
    assert "maitu_category matches required_category: product_video" in body["assets"][0]["match_reasons"]
