from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol


class RoomInspectionSession(Protocol):
    def read_live_room(self, live_room_id: str) -> dict[str, Any]: ...


def inspect_working_room(
    session: RoomInspectionSession,
    *,
    target_live_room_id: str,
    expected_title: str | None,
) -> dict[str, Any]:
    room = session.read_live_room(target_live_room_id)
    if not isinstance(room, dict) or str(room.get("id")) != target_live_room_id:
        raise ValueError("authoritative room id does not match target_live_room_id")
    if room.get("_assetgraph_read_environment") != "working":
        raise ValueError("room inspection was not read from the working environment")
    title = room.get("name")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("authoritative room has no title")
    topics = room.get("topics")
    if not isinstance(topics, list):
        raise ValueError("authoritative room has no topic list")
    scenes: list[dict[str, Any]] = []
    for topic in topics:
        clips = topic.get("clips") if isinstance(topic, dict) else None
        if not isinstance(clips, list):
            raise ValueError("authoritative topic has no clip list")
        for clip in clips:
            if not isinstance(clip, dict):
                raise ValueError("authoritative clip must be an object")
            scene_id = _positive_int(clip.get("id"), "scene id")
            materials = clip.get("clip_materials")
            if not isinstance(materials, list):
                raise ValueError("authoritative clip has no material list")
            scenes.append(
                {
                    "scene_id": str(scene_id),
                    "name": str(clip.get("name") or ""),
                    "order_num": _number(clip.get("order_num"), "scene order_num"),
                    "material_count": len(materials),
                }
            )
    scenes.sort(key=lambda item: (item["order_num"], int(item["scene_id"])))
    is_live = _room_is_active_live(room)
    has_live_trace = _room_has_live_trace(room)
    confirmed_offline = _room_is_confirmed_not_live(room)
    if not is_live and not confirmed_offline:
        raise ValueError("room has no explicit authoritative offline state")
    return {
        "schema_version": "maitu-working-room-inspection.v1",
        "target_live_room_id": target_live_room_id,
        "actual_title": title,
        "expected_title": expected_title,
        "title_matches": expected_title is None or title == expected_title,
        "is_live": is_live,
        "has_live_trace": has_live_trace,
        "read_environment": "working",
        "scene_count": len(scenes),
        "scenes": scenes,
        "captured_at": datetime.now(UTC).isoformat(),
        "ready_for_go_live": False,
        "go_live_clicked": False,
    }


def _room_is_active_live(room: dict[str, Any]) -> bool:
    active_values = {
        "1", "true", "yes", "live", "living", "on_air", "started", "running", "broadcasting"
    }
    return any(
        value is True or (value is not None and str(value).strip().lower() in active_values)
        for key in ("is_live", "living", "is_living", "status", "live_status", "room_status")
        if (value := room.get(key)) is not None
    )


def _room_is_confirmed_not_live(room: dict[str, Any]) -> bool:
    inactive_values = {
        "0", "false", "no", "off", "offline", "stopped", "draft", "working", "idle", "pending", "not_live"
    }
    return any(
        value is False or (value is not None and str(value).strip().lower() in inactive_values)
        for key in ("is_live", "living", "is_living", "status", "live_status", "room_status")
        if (value := room.get(key)) is not None
    )


def _room_has_live_trace(room: dict[str, Any]) -> bool:
    return any(
        value is not None and str(value).strip() not in {"", "0"}
        for key in ("live_session_id", "latest_live_time", "live_started_at", "live_start_time")
        if (value := room.get(key)) is not None
    )


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
