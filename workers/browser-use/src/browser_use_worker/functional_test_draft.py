from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from .room_inspection import inspect_working_room


def enable_test_pending_rights_plan(
    operation_plan: dict[str, Any],
    *,
    job_payload: dict[str, Any],
) -> dict[str, Any]:
    if (
        job_payload.get("execution_mode") != "replace_test_draft"
        or job_payload.get("test_use_acknowledged") is not True
        or job_payload.get("non_releasable") is not True
    ):
        return operation_plan
    blockers = [str(item) for item in operation_plan.get("blocked_reasons") or []]
    if blockers and not all(_pending_rights_blocker(item) for item in blockers):
        raise ValueError("test-only execution cannot waive a non-rights BuildPlan blocker")
    normalized = json.loads(json.dumps(operation_plan, ensure_ascii=False))
    normalized["status"] = "ready"
    normalized["can_execute"] = True
    normalized["manual_review_required"] = False
    normalized["blocked_reasons"] = []
    normalized["test_pending_rights_exception"] = True
    normalized["non_releasable"] = True
    return normalized


def reset_allowlisted_test_room(
    session: Any,
    *,
    job_payload: dict[str, Any],
    progress: Callable[[str, int, str], None],
) -> dict[str, Any]:
    target_live_room_id = str(job_payload.get("build_plan", {}).get("target_live_room_id") or "")
    expected_title = str(job_payload.get("build_plan", {}).get("expected_title") or "")
    if target_live_room_id != "41172" or expected_title != "asser测试":
        raise ValueError("replace mode is limited to allowlisted room 41172 / asser测试")
    expected_fingerprint = str(job_payload.get("expected_room_fingerprint") or "")
    confirmed_scene_ids = [str(item) for item in job_payload.get("confirmed_scene_ids") or []]
    inspection = inspect_working_room(
        session,
        target_live_room_id=target_live_room_id,
        expected_title=expected_title,
    )
    if inspection["actual_title"] != expected_title:
        raise ValueError("working-room title changed after user confirmation")
    if inspection["is_live"] or inspection["has_live_trace"]:
        raise ValueError("working room is live or has a live-session trace")
    observed_fingerprint = room_inspection_fingerprint(inspection)
    observed_scene_ids = [str(item["scene_id"]) for item in inspection["scenes"]]
    if observed_fingerprint != expected_fingerprint:
        raise ValueError("working-room state changed after user confirmation")
    if sorted(observed_scene_ids) != sorted(confirmed_scene_ids):
        raise ValueError("working-room scene list changed after user confirmation")
    if not observed_scene_ids:
        raise ValueError("working room has no keeper scene")
    keeper_scene_id = observed_scene_ids[0]
    progress("clearing_draft", 1, "正在清空已确认的测试草稿")
    deleted_scene_ids: list[str] = []
    for scene_id in observed_scene_ids[1:]:
        session.delete_clip(
            live_room_id=target_live_room_id,
            clip_id=int(scene_id),
            expected_live_room_title=expected_title,
        )
        deleted_scene_ids.append(scene_id)
    clear_result = session.clear_clip_materials(
        live_room_id=target_live_room_id,
        clip_id=int(keeper_scene_id),
        expected_live_room_title=expected_title,
    )
    empty = inspect_working_room(
        session,
        target_live_room_id=target_live_room_id,
        expected_title=expected_title,
    )
    if (
        empty["scene_count"] != 1
        or str(empty["scenes"][0]["scene_id"]) != keeper_scene_id
        or int(empty["scenes"][0]["material_count"]) != 0
    ):
        raise ValueError("test-room reset did not converge to one empty keeper scene")
    return {
        "keeper_scene_id": keeper_scene_id,
        "deleted_scene_ids": deleted_scene_ids,
        "clear_result": _clear_result_evidence(clear_result),
        "empty_room_readback": empty,
        "go_live_clicked": False,
    }


def room_inspection_fingerprint(inspection: dict[str, Any]) -> str:
    identity = {
        "target_live_room_id": str(inspection.get("target_live_room_id") or ""),
        "actual_title": inspection.get("actual_title"),
        "is_live": inspection.get("is_live"),
        "has_live_trace": inspection.get("has_live_trace"),
        "read_environment": inspection.get("read_environment"),
        "scenes": inspection.get("scenes"),
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clear_result_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """Keep reset outcomes without persisting provider DELETE responses."""

    evidence: dict[str, Any] = {}
    for field_name in (
        "status",
        "live_room_id",
        "clip_id",
        "remaining_material_count",
        "verified",
        "verification_source",
        "not_live",
        "go_live_clicked",
    ):
        value = result.get(field_name)
        if isinstance(value, (str, int, bool)) and not isinstance(value, float):
            evidence[field_name] = value
    deleted_material_ids = result.get("deleted_material_ids")
    if isinstance(deleted_material_ids, list):
        evidence["deleted_material_ids"] = [
            value
            for value in deleted_material_ids
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        ]
    return evidence


def _pending_rights_blocker(value: str) -> bool:
    lowered = value.lower()
    return (
        value.startswith("asset_rights_not_approved:") and value.endswith(":pending")
    ) or ("rights" in lowered and ("pending" in lowered or "not_approved" in lowered))
