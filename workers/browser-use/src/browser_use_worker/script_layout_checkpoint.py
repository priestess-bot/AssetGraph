from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from .script_layout_draft_executor import (
    ScriptLayoutDraftActionResult,
    ScriptLayoutDraftResult,
    build_script_layout_draft_execution_payload,
    script_layout_action_to_operation_result,
)

T = TypeVar("T")

_DURABLE_URL_FIELDS = {
    "source_material_url",
    "source_cover_url",
    "url",
    "cover_url",
}


class ScriptLayoutCheckpointClient(Protocol):
    def start_script_layout_execution(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def renew_script_layout_execution(
        self,
        build_plan_code: str,
        execution_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def begin_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def dispatch_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def invalidate_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def complete_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def finalize_script_layout_execution(
        self,
        build_plan_code: str,
        execution_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


def _durable_execution_value(value: Any) -> Any:
    if isinstance(value, dict):
        durable: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"material_resolution_status", "material_resolution_reason"}:
                continue
            if key in _DURABLE_URL_FIELDS and isinstance(item, str):
                parsed = urlsplit(item)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    durable[key] = urlunsplit(
                        (parsed.scheme, parsed.netloc, parsed.path, "", "")
                    )
                    continue
            durable[key] = _durable_execution_value(item)
        return durable
    if isinstance(value, list):
        return [_durable_execution_value(item) for item in value]
    return value


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    durable_payload = _durable_execution_value(payload)
    encoded = json.dumps(durable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def script_layout_plan_fingerprint(operation_plan: dict[str, Any], *, target_live_room_id: str) -> str:
    durable_plan = {
        key: value
        for key, value in operation_plan.items()
        if key not in {"browser_use_operations_url", "created_at", "updated_at"}
    }
    durable_plan["target_live_room_id"] = target_live_room_id
    return _canonical_fingerprint(durable_plan)


def script_layout_operation_fingerprint(
    build_plan_code: str,
    operation_index: int,
    operation: dict[str, Any],
) -> str:
    return _canonical_fingerprint(
        {
            "build_plan_code": build_plan_code,
            "operation_index": operation_index,
            "operation": operation,
        }
    )


def _action_completion_verified(action: ScriptLayoutDraftActionResult) -> bool:
    if action.status == "skipped":
        return action.operation_type in {"placeholder_required", "save_draft"}
    if action.status != "completed":
        return False
    details = action.details if isinstance(action.details, dict) else {}
    result_field = {
        "preflight_content_build_plan": "preflight_result",
        "fill_default_scene": "rename_result",
        "create_scene": "create_result",
        "insert_asset_layer": "insert_result",
        "position_asset_layer": "position_result",
        "write_script": "write_result",
        "verify_scene": "verify_result",
        "verify_draft_persisted": "draft_result",
    }.get(action.operation_type or "")
    if result_field is None:
        return action.operation_type in {"placeholder_required", "save_draft"}
    result = details.get(result_field)
    return isinstance(result, dict) and result.get("verified") is True


def _retry_idempotent(call: Callable[[], T]) -> T:
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            return call()
        except Exception as exc:  # the request identity is stable across the bounded retry
            last_error = exc
    assert last_error is not None
    raise last_error


@dataclass(slots=True)
class AssetGraphScriptLayoutCheckpointStore:
    client: ScriptLayoutCheckpointClient
    build_plan_code: str
    execution_code: str
    target_live_room_id: str
    plan_fingerprint: str
    run_attempt_id: UUID
    lease_token: UUID
    lease_version: int
    operation_checkpoints: dict[int, dict[str, Any]]
    finalization_id: UUID = field(default_factory=uuid4)
    _completion_ids: dict[int, UUID] = field(default_factory=dict)

    @classmethod
    def start(
        cls,
        *,
        client: ScriptLayoutCheckpointClient,
        operation_plan: dict[str, Any],
        target_live_room_id: str,
    ) -> "AssetGraphScriptLayoutCheckpointStore":
        build_plan_code = str(operation_plan.get("build_plan_code") or "").strip()
        if not build_plan_code:
            raise ValueError("checkpointed script-layout execution requires build_plan_code")
        source_plan_fingerprint = str(operation_plan.get("checkpoint_source_fingerprint") or "").strip()
        if len(source_plan_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in source_plan_fingerprint
        ):
            raise ValueError("checkpointed script-layout execution requires backend source fingerprint")
        operations = operation_plan.get("operations")
        if not isinstance(operations, list) or not all(isinstance(item, dict) for item in operations):
            raise ValueError("checkpointed script-layout execution requires an operation manifest")
        if (
            not operations
            or operations[0].get("operation_type") != "preflight_content_build_plan"
            or operations[0].get("status") != "ready"
            or str(operations[0].get("target_live_room_id") or target_live_room_id) != target_live_room_id
        ):
            raise ValueError("checkpointed script-layout execution requires target-bound ready preflight first")
        start_request_id = uuid4()
        run_attempt_id = uuid4()
        start_payload = {
            "start_request_id": str(start_request_id),
            "run_attempt_id": str(run_attempt_id),
            "source_plan_fingerprint": source_plan_fingerprint,
            "target_live_room_id": target_live_room_id,
            "operations": [
                {"operation_index": index, "intent": _durable_execution_value(operation)}
                for index, operation in enumerate(operations)
            ],
            "mode": "script_layout_draft",
            "checkpoint_contract": "script_layout_checkpoint_v1",
        }
        execution = _retry_idempotent(
            lambda: client.start_script_layout_execution(build_plan_code, start_payload)
        )
        execution_code = str(execution.get("execution_code") or "").strip()
        if not execution_code:
            raise RuntimeError("checkpoint start response omitted execution_code")
        if execution.get("checkpoint_contract") != "script_layout_checkpoint_v1":
            raise RuntimeError("checkpoint start response contract mismatch")
        if execution.get("finalized_at") is not None:
            raise RuntimeError("checkpoint execution is already finalized")
        if str(execution.get("run_attempt_id")) != str(run_attempt_id):
            raise RuntimeError("checkpoint start response run attempt mismatch")
        try:
            lease_token = UUID(str(execution.get("lease_token")))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("checkpoint start response omitted lease token") from exc
        if lease_token in {start_request_id, run_attempt_id}:
            raise RuntimeError("checkpoint start response reused a request identity as lease token")
        lease_version = int(execution.get("lease_version") or 0)
        if lease_version < 1:
            raise RuntimeError("checkpoint start response omitted lease fence version")
        rows = execution.get("operation_results")
        if not isinstance(rows, list) or len(rows) != len(operations):
            raise RuntimeError("checkpoint start response manifest cardinality mismatch")
        operation_checkpoints: dict[int, dict[str, Any]] = {}
        for expected_index, row in enumerate(rows):
            if not isinstance(row, dict) or int(row.get("operation_index", -1)) != expected_index:
                raise RuntimeError("checkpoint start response manifest indexes mismatch")
            if not row.get("operation_fingerprint") or row.get("effect_class") not in {
                "mutating",
                "read_only",
                "manual_noop",
            }:
                raise RuntimeError("checkpoint start response omitted frozen operation identity")
            operation_checkpoints[expected_index] = row
        return cls(
            client=client,
            build_plan_code=build_plan_code,
            execution_code=execution_code,
            target_live_room_id=target_live_room_id,
            plan_fingerprint=str(execution.get("plan_fingerprint") or ""),
            run_attempt_id=run_attempt_id,
            lease_token=lease_token,
            lease_version=lease_version,
            operation_checkpoints=operation_checkpoints,
        )

    def ensure_lease_active(self) -> bool:
        response = _retry_idempotent(
            lambda: self.client.renew_script_layout_execution(
                self.build_plan_code,
                self.execution_code,
                {
                    "run_attempt_id": str(self.run_attempt_id),
                    "lease_token": str(self.lease_token),
                    "lease_version": self.lease_version,
                },
            )
        )
        if (
            str(response.get("run_attempt_id")) != str(self.run_attempt_id)
            or str(response.get("lease_token")) != str(self.lease_token)
            or int(response.get("lease_version") or 0) != self.lease_version
        ):
            raise RuntimeError("checkpoint lease renewal response changed the active fence")
        return True

    def _fenced_payload(self, operation_index: int) -> dict[str, Any]:
        checkpoint = self.operation_checkpoints[operation_index]
        return {
            "operation_fingerprint": checkpoint["operation_fingerprint"],
            "attempt_id": str(self.run_attempt_id),
            "lease_token": str(self.lease_token),
            "lease_version": self.lease_version,
        }

    def begin_operation(self, operation_index: int, operation: dict[str, Any]) -> dict[str, Any]:
        del operation
        self.ensure_lease_active()
        checkpoint = self.operation_checkpoints[operation_index]
        response = _retry_idempotent(
            lambda: self.client.begin_script_layout_execution_operation(
                self.build_plan_code,
                self.execution_code,
                operation_index,
                self._fenced_payload(operation_index),
            )
        )
        response = {**checkpoint, **response}
        self.operation_checkpoints[operation_index] = response
        return response

    def dispatch_operation(self, operation_index: int, operation: dict[str, Any]) -> dict[str, Any]:
        del operation
        self.ensure_lease_active()
        checkpoint = self.operation_checkpoints[operation_index]
        if checkpoint.get("effect_class") != "mutating":
            return checkpoint
        response = _retry_idempotent(
            lambda: self.client.dispatch_script_layout_execution_operation(
                self.build_plan_code,
                self.execution_code,
                operation_index,
                self._fenced_payload(operation_index),
            )
        )
        self.operation_checkpoints[operation_index] = response
        return response

    def invalidate_operation(
        self,
        operation_index: int,
        operation: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self.ensure_lease_active()
        checkpoint = self.operation_checkpoints[operation_index]
        payload = {
            **self._fenced_payload(operation_index),
            "evidence": _durable_execution_value({
                **evidence,
                "verified": True,
                "checkpoint_invalid": True,
                "operation_index": operation_index,
                "operation_type": operation.get("operation_type"),
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "target_live_room_id": self.target_live_room_id,
            }),
        }
        response = _retry_idempotent(
            lambda: self.client.invalidate_script_layout_execution_operation(
                self.build_plan_code,
                self.execution_code,
                operation_index,
                payload,
            )
        )
        self.operation_checkpoints[operation_index] = response
        return response

    def complete_operation(
        self,
        operation_index: int,
        operation: dict[str, Any],
        action: ScriptLayoutDraftActionResult,
    ) -> dict[str, Any]:
        self.ensure_lease_active()
        checkpoint = self.operation_checkpoints[operation_index]
        completion_id = self._completion_ids.setdefault(operation_index, uuid4())
        operation_result = script_layout_action_to_operation_result(action)
        # Completion evidence already carries the authoritative readback fields.
        # Persisting the provider's raw mutation response duplicates that data and
        # can retain unrelated provider metadata in the durable checkpoint.
        operation_result["details"] = {
            "summary": action.summary,
            "go_live_clicked": False,
        }
        effect_class = checkpoint["effect_class"]
        if effect_class == "mutating" and action.status != "completed":
            raise RuntimeError("mutating operation did not complete and must remain dispatched for reconciliation")
        operation_applied = effect_class == "mutating" and action.status == "completed"
        action_details = action.details if isinstance(action.details, dict) else {}
        nested_result: dict[str, Any] = {}
        for result_field in (
            "preflight_result",
            "rename_result",
            "create_result",
            "insert_result",
            "position_result",
            "write_result",
            "verify_result",
            "draft_result",
        ):
            candidate = action_details.get(result_field)
            if isinstance(candidate, dict):
                nested_result = candidate
                break
        source_material_type = nested_result.get("source_material_type")
        evidence = _durable_execution_value({
            "verified": _action_completion_verified(action),
            "operation_applied": operation_applied,
            "no_side_effect": not operation_applied,
            "operation_index": operation_index,
            "operation_type": action.operation_type or operation.get("operation_type"),
            "operation_fingerprint": checkpoint["operation_fingerprint"],
            "target_live_room_id": self.target_live_room_id,
            "expected_live_room_title": nested_result.get("expected_live_room_title"),
            "authoritative_live_room_title": nested_result.get("authoritative_live_room_title"),
            "scene_index": action.scene_index,
            "scene_name": action.scene_name,
            "clip_id": action.clip_id,
            "layer_id": action.layer_id,
            "layer_type": action.layer_type,
            "asset_code": action.asset_code,
            "material_id": nested_result.get("material_id"),
            "text_material_id": nested_result.get("text_material_id"),
            "verification_source": nested_result.get("verification_source"),
            "environment": nested_result.get("environment"),
            "not_live": nested_result.get("not_live"),
            "default_clip_id": nested_result.get("default_clip_id"),
            "source_material_id": (
                None if source_material_type == "digital_human" else nested_result.get("source_material_id")
            ),
            "source_material_type": source_material_type,
            "source_material_url": (
                None if source_material_type == "digital_human" else nested_result.get("source_material_url")
            ),
            "speaker_id": nested_result.get("speaker_id"),
            "digital_human_image_id": nested_result.get("digital_human_image_id"),
            "sound_enabled": nested_result.get("sound_enabled"),
            "expected_visual_count": nested_result.get("expected_visual_count"),
            "expected_text_count": nested_result.get("expected_text_count"),
            "expected_script_sha256": nested_result.get("expected_script_sha256"),
            "verified_layers": nested_result.get("verified_layers"),
            "verified_script_text": nested_result.get("verified_script_text"),
            "expected_scene_names": nested_result.get("expected_scene_names"),
            "actual_scene_names": nested_result.get("actual_scene_names"),
            "left": nested_result.get("left"),
            "top": nested_result.get("top"),
            "width": nested_result.get("width"),
            "height": nested_result.get("height"),
            "z_index": nested_result.get("z_index"),
            "script_sha256": (
                hashlib.sha256(str(operation.get("script_text") or "").encode("utf-8")).hexdigest()
                if action.operation_type == "write_script"
                else None
            ),
            "action_type": action.action_type,
            "status": action.status,
            "go_live_clicked": False,
        })
        if evidence["verified"] is not True:
            raise RuntimeError("operation completion lacks authoritative verification evidence")
        if effect_class == "mutating" and evidence["verification_source"] != "working_room_readback":
            raise RuntimeError("mutating operation completion lacks trusted working-room readback source")
        payload = {
            **self._fenced_payload(operation_index),
            "completion_id": str(completion_id),
            "result_summary": action.summary,
            "evidence": evidence,
            "operation_result": operation_result,
        }
        response = _retry_idempotent(
            lambda: self.client.complete_script_layout_execution_operation(
                self.build_plan_code,
                self.execution_code,
                operation_index,
                payload,
            )
        )
        self.operation_checkpoints[operation_index] = response
        return response

    def finalize(self, result: ScriptLayoutDraftResult) -> dict[str, Any]:
        self.ensure_lease_active()
        payload = build_script_layout_draft_execution_payload(result)
        payload.pop("operation_results", None)
        if result.status in {"failed", "blocked"}:
            error_code = (
                "SCRIPT_LAYOUT_DRAFT_BLOCKED"
                if result.status == "blocked"
                else "SCRIPT_LAYOUT_DRAFT_EXECUTION_FAILED"
            )
            payload = {
                "executor": "browser_use",
                "execution_status": result.status,
                "mode": "script_layout_draft",
                "failure_type": error_code.lower(),
                "retryable": False,
                "error_message": "草稿生成未完成，请确认测试房间现场状态后重试。",
                "result_summary": "草稿生成未完成，执行检查点已安全关闭。",
                "ready_for_go_live": False,
                "manual_review_required": True,
                "details": {
                    "error_code": error_code,
                    "failure_stage": "script_layout_draft_execution",
                    "go_live_clicked": False,
                },
            }
        payload.update(
            {
                "finalization_id": str(self.finalization_id),
                "run_attempt_id": str(self.run_attempt_id),
                "lease_token": str(self.lease_token),
                "lease_version": self.lease_version,
            }
        )
        payload = _durable_execution_value(payload)
        return _retry_idempotent(
            lambda: self.client.finalize_script_layout_execution(
                self.build_plan_code,
                self.execution_code,
                payload,
            )
        )
