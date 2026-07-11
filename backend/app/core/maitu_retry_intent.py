from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

RETRY_BEFORE_STATE_KEYS = frozenset(
    {"layer_id", "material_id", "left", "top", "width", "height", "z_index"}
)

RETRY_AUTHORITATIVE_INTENT_KEYS = frozenset(
    {
        "contract_version",
        "retry_task_code",
        "target_app",
        "maitu_project_code",
        "target_live_room_id",
        "slot_target_live_room_id",
        "target_clip_id",
        "target_layer_id",
        "plan_target_scene_name",
        "slot_target_scene_name",
        "expected_before_state",
        "desired_after_state",
        "target_scene_name",
        "slot_code",
        "layer_name",
        "asset_code",
        "selected_asset_code",
        "binding_asset_code",
        "selected_asset_type",
        "selected_asset_status",
        "accepted_asset_types",
        "maitu_material_id",
        "source_material_type",
        "binding_verification_source",
        "binding_verified_at",
        "binding_scope",
        "replacement_policy",
        "primary_operation_type",
        "retry_task_retryable",
        "operation_key",
        "operation_type",
        "instruction",
    }
)

RETRY_OPERATION_TOP_LEVEL_BINDINGS = {
    "contract_version": "contract_version",
    "retry_task_code": "retry_task_code",
    "target_app": "target_app",
    "operation_key": "operation_key",
    "operation_type": "operation_type",
    "target_live_room_id": "target_live_room_id",
    "target_clip_id": "target_clip_id",
    "target_scene_name": "target_scene_name",
    "scene_name": "target_scene_name",
    "target_layer_id": "target_layer_id",
    "expected_before_state": "expected_before_state",
    "desired_after_state": "desired_after_state",
    "slot_code": "slot_code",
    "layer_name": "layer_name",
    "asset_code": "asset_code",
    "selected_asset_type": "selected_asset_type",
    "selected_asset_status": "selected_asset_status",
    "accepted_asset_types": "accepted_asset_types",
    "maitu_material_id": "maitu_material_id",
    "source_material_type": "source_material_type",
    "binding_verification_source": "binding_verification_source",
    "binding_verified_at": "binding_verified_at",
    "binding_scope": "binding_scope",
    "replacement_policy": "replacement_policy",
    "instruction": "instruction",
}


def is_canonical_retry_before_state(candidate: Any, *, target_layer_id: Any) -> bool:
    if not isinstance(candidate, dict) or set(candidate) != RETRY_BEFORE_STATE_KEYS:
        return False
    if candidate.get("layer_id") != target_layer_id:
        return False
    material_id = candidate.get("material_id")
    if not _is_positive_int(material_id):
        return False
    for key in ("left", "top", "width", "height"):
        value = candidate.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            if not math.isfinite(value):
                return False
        except OverflowError:
            return False
    if candidate["width"] <= 0 or candidate["height"] <= 0:
        return False
    z_index = candidate.get("z_index")
    return isinstance(z_index, int) and not isinstance(z_index, bool)


def retry_operation_intent_fingerprint(authoritative_intent: Any) -> str | None:
    if not isinstance(authoritative_intent, dict) or set(authoritative_intent) != RETRY_AUTHORITATIVE_INTENT_KEYS:
        return None
    return hashlib.sha256(
        json.dumps(
            authoritative_intent,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def is_canonical_retry_operation_intent(operation: Any) -> bool:
    if not isinstance(operation, dict):
        return False
    required = {
        "authoritative_intent",
        "blocked_reasons",
        "instruction",
        "operation_fingerprint",
        "retry_task_code",
        "status",
        *RETRY_OPERATION_TOP_LEVEL_BINDINGS,
    }
    if not required.issubset(operation):
        return False

    authoritative_intent = operation.get("authoritative_intent")
    expected_fingerprint = retry_operation_intent_fingerprint(authoritative_intent)
    if expected_fingerprint is None or operation.get("operation_fingerprint") != expected_fingerprint:
        return False
    if any(
        operation.get(operation_key) != authoritative_intent.get(intent_key)
        for operation_key, intent_key in RETRY_OPERATION_TOP_LEVEL_BINDINGS.items()
    ):
        return False
    if operation.get("contract_version") != "maitu-retry-mutation-v1" or operation.get("target_app") != "maitu":
        return False
    if not isinstance(operation.get("retry_task_code"), str) or not operation["retry_task_code"]:
        return False
    if not isinstance(operation.get("instruction"), str) or not operation["instruction"]:
        return False

    operation_key = operation.get("operation_key")
    operation_type = operation.get("operation_type")
    if operation_key == "save_project":
        if operation_type != "retry_save_project":
            return False
    elif operation_key == "primary":
        if operation_type == "retry_save_project":
            return False
    else:
        return False

    status = operation.get("status")
    blocked_reasons = operation.get("blocked_reasons")
    if not isinstance(blocked_reasons, list) or any(
        not isinstance(reason, str) or not reason for reason in blocked_reasons
    ):
        return False
    if status == "ready":
        return not blocked_reasons and _is_ready_retry_replace_intent(authoritative_intent)
    if status == "blocked":
        return bool(blocked_reasons)
    return False


def _is_ready_retry_replace_intent(intent: dict[str, Any]) -> bool:
    if intent.get("operation_key") != "primary" or intent.get("operation_type") != "retry_replace_layer_asset":
        return False
    if intent.get("primary_operation_type") != "retry_replace_layer_asset":
        return False
    if intent.get("retry_task_retryable") is not True:
        return False

    project_code = intent.get("maitu_project_code")
    if not isinstance(project_code, str) or not project_code:
        return False
    target_room = intent.get("target_live_room_id")
    if not isinstance(target_room, str) or not target_room or intent.get("slot_target_live_room_id") != target_room:
        return False
    if not _is_positive_int(intent.get("target_clip_id")) or not _is_positive_int(intent.get("target_layer_id")):
        return False

    target_scene = intent.get("target_scene_name")
    plan_scene = intent.get("plan_target_scene_name")
    slot_scene = intent.get("slot_target_scene_name")
    if not isinstance(target_scene, str) or not target_scene:
        return False
    if plan_scene is not None and (not isinstance(plan_scene, str) or not plan_scene):
        return False
    if slot_scene is not None and (not isinstance(slot_scene, str) or not slot_scene):
        return False
    if plan_scene is not None and slot_scene is not None and plan_scene != slot_scene:
        return False
    if target_scene != (slot_scene or plan_scene):
        return False

    before = intent.get("expected_before_state")
    if not is_canonical_retry_before_state(before, target_layer_id=intent.get("target_layer_id")):
        return False
    after = intent.get("desired_after_state")
    if not isinstance(after, dict) or set(after) != {
        "maitu_material_id",
        "source_material_type",
        "replacement_policy",
        "geometry",
    }:
        return False
    expected_geometry = {key: before[key] for key in ("left", "top", "width", "height", "z_index")}
    if after.get("geometry") != expected_geometry:
        return False
    if any(
        after.get(key) != intent.get(key)
        for key in ("maitu_material_id", "source_material_type", "replacement_policy")
    ):
        return False

    asset_code = intent.get("asset_code")
    if not isinstance(asset_code, str) or not asset_code:
        return False
    if not asset_code == intent.get("selected_asset_code") == intent.get("binding_asset_code"):
        return False
    selected_asset_type = intent.get("selected_asset_type")
    source_material_type = intent.get("source_material_type")
    if {"IMG": "image", "VID": "video"}.get(selected_asset_type) != source_material_type:
        return False
    accepted_asset_types = intent.get("accepted_asset_types")
    if not isinstance(accepted_asset_types, list) or selected_asset_type not in accepted_asset_types:
        return False
    if intent.get("selected_asset_status") != "stored" or intent.get("replacement_policy") != "keep_layout":
        return False

    if not _is_positive_int(intent.get("maitu_material_id")):
        return False
    if intent.get("binding_verification_source") != "maitu_readback":
        return False
    if intent.get("binding_scope") != f"live_room:{target_room}":
        return False
    return _is_timezone_aware_iso_datetime(intent.get("binding_verified_at"))


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_timezone_aware_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.utcoffset() is not None
