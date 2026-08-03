from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode


MAITU_PLATFORMS: tuple[dict[str, Any], ...] = (
    {"external_platform_id": 1, "platform_code": "taobao", "platform_name": "淘宝"},
    {"external_platform_id": 2, "platform_code": "kuaishou", "platform_name": "快手"},
    {"external_platform_id": 3, "platform_code": "douyin", "platform_name": "抖音"},
    {"external_platform_id": 4, "platform_code": "jd", "platform_name": "京东"},
    {"external_platform_id": 5, "platform_code": "video", "platform_name": "视频号"},
    {"external_platform_id": 18, "platform_code": "wx", "platform_name": "微信小程序"},
    {"external_platform_id": 6, "platform_code": "pdd", "platform_name": "拼多多"},
    {"external_platform_id": 8, "platform_code": "weipinghui", "platform_name": "唯品会"},
    {"external_platform_id": 9, "platform_code": "meituan", "platform_name": "美团"},
)


class MaituInteractionSession(Protocol):
    def probe_current_page(self, *, open_if_needed: bool = False) -> Any: ...

    def read_maitu_account_identity(self) -> dict[str, Any]: ...

    def get_maitu_interaction_api_page(self, path: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MaituInteractionCatalog:
    external_account_id: int
    account_name: str | None
    platforms: tuple[dict[str, Any], ...]
    sessions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class MaituInteractionPage:
    source_total: int
    final_page: bool
    items: tuple[dict[str, Any], ...]


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _epoch_iso(value: Any) -> str | None:
    if not _positive_number(value):
        return None
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat().replace("+00:00", "Z")


def maitu_comment_boundary(value: Any) -> str:
    if not _positive_number(value):
        raise ValueError("Maitu session boundary must be a positive epoch timestamp")
    shifted = datetime.fromtimestamp(float(value), tz=UTC) + timedelta(hours=8)
    return shifted.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _positive_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and value > 0
    )


def _page_items(payload: dict[str, Any], *, endpoint: str) -> tuple[list[dict[str, Any]], int]:
    items = payload.get("items")
    total = payload.get("total")
    if not isinstance(items, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError(f"Unexpected Maitu pagination schema for {endpoint}")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError(f"Unexpected Maitu item schema for {endpoint}")
    return items, total


class MaituInteractionCollector:
    def __init__(self, session: MaituInteractionSession):
        self.session = session

    def collect_catalog(self) -> MaituInteractionCatalog:
        probe = self.session.probe_current_page(open_if_needed=True)
        if not getattr(probe, "logged_in", False) or getattr(probe, "login_required", True):
            raise RuntimeError("Maitu login is required in the visible browser")
        identity = self.session.read_maitu_account_identity()
        sessions_by_id: dict[int, dict[str, Any]] = {}
        for platform in MAITU_PLATFORMS:
            platform_id = int(platform["external_platform_id"])
            offset = 0
            limit = 100
            for _page in range(10000):
                query = urlencode(
                    {
                        "offset": offset,
                        "limit": limit,
                        "status": 2,
                        "live_room_platform": platform_id,
                    }
                )
                endpoint = f"live_session/?{query}"
                raw_page = self.session.get_maitu_interaction_api_page(endpoint)
                items, total = _page_items(raw_page, endpoint=endpoint)
                for raw in items:
                    normalized = self._normalize_session(raw, expected_platform_id=platform_id)
                    sessions_by_id[normalized["external_session_id"]] = normalized
                offset += len(items)
                if not items or offset >= total:
                    break
            else:
                raise RuntimeError(f"Maitu session pagination exceeded safety limit for platform {platform_id}")
        return MaituInteractionCatalog(
            external_account_id=int(identity["external_account_id"]),
            account_name=identity.get("account_name"),
            platforms=tuple(dict(item) for item in MAITU_PLATFORMS),
            sessions=tuple(
                sorted(
                    sessions_by_id.values(),
                    key=lambda item: (item["started_at"], item["external_session_id"]),
                )
            ),
        )

    def iter_interaction_pages(self, live_session: dict[str, Any]) -> Iterator[MaituInteractionPage]:
        source_payload = live_session.get("source_payload")
        if not isinstance(source_payload, dict):
            raise ValueError("Live session has no source payload for exact Maitu boundaries")
        session_id = int(live_session["external_session_id"])
        live_room_id = int(live_session["external_live_room_id"])
        created_after = maitu_comment_boundary(source_payload.get("start_at"))
        created_before = maitu_comment_boundary(source_payload.get("end_at"))
        offset = 0
        limit = 100
        for _page in range(10000):
            query = urlencode(
                {
                    "offset": offset,
                    "limit": limit,
                    "live_room_id": live_room_id,
                    "created_at_after": created_after,
                    "created_at_before": created_before,
                    "live_session_id": session_id,
                }
            )
            endpoint = f"live_room_comment/{live_room_id}/get_comments_es?{query}"
            raw_page = self.session.get_maitu_interaction_api_page(endpoint)
            items, total = _page_items(raw_page, endpoint=endpoint)
            normalized = tuple(
                self._normalize_interaction(
                    item,
                    expected_live_room_id=live_room_id,
                )
                for item in items
            )
            offset += len(items)
            final_page = not items or offset >= total
            yield MaituInteractionPage(
                source_total=total,
                final_page=final_page,
                items=normalized,
            )
            if final_page:
                return
        raise RuntimeError(f"Maitu interaction pagination exceeded safety limit for session {session_id}")

    @staticmethod
    def _normalize_session(raw: dict[str, Any], *, expected_platform_id: int) -> dict[str, Any]:
        session_id = raw.get("id")
        live_room_id = raw.get("live_room_id")
        platform_id = raw.get("live_room_platform")
        start_at = raw.get("start_at")
        end_at = raw.get("end_at")
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in (session_id, live_room_id)
        ) or not all(_positive_number(value) for value in (start_at, end_at)):
            raise ValueError("Maitu live session is missing a stable identity or time boundary")
        if platform_id != expected_platform_id:
            raise ValueError("Maitu live session platform does not match the requested platform")
        if end_at < start_at:
            raise ValueError("Maitu live session has an inverted time boundary")
        title = str(raw.get("live_room_name") or f"直播场次 {session_id}").strip()
        return {
            "external_session_id": session_id,
            "external_live_room_id": live_room_id,
            "external_platform_id": platform_id,
            "platform_live_id": str(raw.get("live_room_platform_id") or "").strip() or None,
            "title": title[:512],
            "live_room_type": str(raw.get("live_room_type") or "").strip()[:64] or None,
            "source_status": int(raw.get("status") or 0),
            "started_at": _epoch_iso(start_at),
            "ended_at": _epoch_iso(end_at),
            "duration_seconds": int(max(0, end_at - start_at)),
            "source_created_at": _epoch_iso(raw.get("created_at")),
            "source_updated_at": _epoch_iso(raw.get("updated_at")),
            "source_payload": raw,
            "source_fingerprint": _canonical_fingerprint(raw),
        }

    @staticmethod
    def _normalize_interaction(
        raw: dict[str, Any],
        *,
        expected_live_room_id: int,
    ) -> dict[str, Any]:
        interaction_id = raw.get("id")
        live_room_id = raw.get("live_room_id")
        if interaction_id is None or isinstance(interaction_id, (dict, list, bool)):
            raise ValueError("Maitu interaction is missing a stable identity")
        if live_room_id != expected_live_room_id:
            raise ValueError("Maitu interaction belongs to an unexpected live room")
        topic = raw.get("topic") if isinstance(raw.get("topic"), dict) else {}
        return {
            "external_interaction_id": str(interaction_id),
            "live_room_id": live_room_id,
            "platform": raw.get("platform") if isinstance(raw.get("platform"), int) else None,
            "platform_live_id": str(raw.get("platform_live_id") or "").strip()[:255] or None,
            "request_id": str(raw.get("request_id") or "").strip()[:255] or None,
            "interaction_type": int(raw.get("interaction_type") or 0),
            "content": str(raw.get("content") or ""),
            "publisher_name": str(raw.get("publisher_name") or "").strip()[:512] or None,
            "publisher_role": str(raw.get("publisher_role") or "").strip()[:64] or None,
            "item_id": str(topic.get("item_id") or "").strip()[:255] or None,
            "published_at": _epoch_iso(raw.get("published_at")),
            "digital_reply_type": raw.get("comment_type") if isinstance(raw.get("comment_type"), int) else None,
            "digital_reply_status": raw.get("comment_status") if isinstance(raw.get("comment_status"), int) else None,
            "digital_reply_content": str(raw.get("interact_content") or "") or None,
            "digital_replied_at": _epoch_iso(raw.get("interacted_at")),
            "bullet_reply_type": raw.get("comment_type_1") if isinstance(raw.get("comment_type_1"), int) else None,
            "bullet_reply_status": raw.get("comment_status_1") if isinstance(raw.get("comment_status_1"), int) else None,
            "bullet_reply_content": str(raw.get("interact_content_1") or "") or None,
            "bullet_replied_at": _epoch_iso(raw.get("interacted_at_1")),
            "reply_decision_code": raw.get("reply_decision_code") if isinstance(raw.get("reply_decision_code"), int) else None,
            "bullet_reply_decision_code": raw.get("reply_decision_code_1") if isinstance(raw.get("reply_decision_code_1"), int) else None,
            "source_created_at": _epoch_iso(raw.get("created_at")),
            "source_updated_at": _epoch_iso(raw.get("updated_at")),
            "source_payload": raw,
        }
