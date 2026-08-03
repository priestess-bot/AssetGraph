from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pytest

from browser_use_worker.maitu_interaction_sync import (
    MAITU_PLATFORMS,
    MaituInteractionCollector,
    maitu_comment_boundary,
)


@dataclass
class _Probe:
    logged_in: bool = True
    login_required: bool = False


class _Session:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def probe_current_page(self, *, open_if_needed: bool = False):
        assert open_if_needed is True
        return _Probe()

    def read_maitu_account_identity(self):
        return {"external_account_id": 42, "account_name": "operator"}

    def get_maitu_interaction_api_page(self, path: str):
        self.paths.append(path)
        parsed = urlparse(path)
        query = parse_qs(parsed.query)
        if path.startswith("live_session/"):
            platform = int(query["live_room_platform"][0])
            if platform != 4:
                return {"items": [], "total": 0, "offset": 0, "limit": 100}
            return {
                "items": [
                    {
                        "id": 156953,
                        "live_room_id": 37706,
                        "live_room_platform": 4,
                        "live_room_platform_id": "jd-live-id",
                        "live_room_name": "测试直播",
                        "live_room_type": "ts_real_driver",
                        "status": 2,
                        "start_at": 1_750_000_000.0,
                        "end_at": 1_750_003_600.0,
                        "created_at": 1_750_000_000.0,
                        "updated_at": 1_750_003_600.0,
                    }
                ],
                "total": 1,
                "offset": 0,
                "limit": 100,
            }
        assert query["live_session_id"] == ["156953"]
        assert query["live_room_id"] == ["37706"]
        return {
            "items": [
                {
                    "id": 9001,
                    "live_room_id": 37706,
                    "platform": 4,
                    "interaction_type": 0,
                    "content": "多少钱？",
                    "publisher_name": "user",
                    "publisher_role": "SELF",
                    "published_at": 1_750_000_100,
                    "comment_type": 1,
                    "comment_status": 1,
                    "interact_content": "请看三号链接",
                    "interacted_at": 1_750_000_105,
                    "comment_type_1": 2,
                    "comment_status_1": 1,
                    "interact_content_1": "三号链接",
                    "interacted_at_1": 1_750_000_106,
                    "reply_decision_code": 10,
                    "reply_decision_code_1": 11,
                    "topic": {"item_id": "SKU-3"},
                    "created_at": 1_750_000_100,
                    "updated_at": 1_750_000_106,
                }
            ],
            "total": 1,
            "offset": 0,
            "limit": 100,
        }


def test_catalog_traverses_every_supported_platform_and_normalizes_session() -> None:
    session = _Session()
    catalog = MaituInteractionCollector(session).collect_catalog()

    assert catalog.external_account_id == 42
    assert len(catalog.platforms) == len(MAITU_PLATFORMS) == 9
    assert len([path for path in session.paths if path.startswith("live_session/")]) == 9
    assert len(catalog.sessions) == 1
    assert catalog.sessions[0]["external_session_id"] == 156953
    assert catalog.sessions[0]["external_platform_id"] == 4
    assert catalog.sessions[0]["duration_seconds"] == 3600


def test_interaction_query_uses_shifted_exact_boundaries_and_preserves_both_replies() -> None:
    session = _Session()
    collector = MaituInteractionCollector(session)
    live_session = collector.collect_catalog().sessions[0]

    pages = list(collector.iter_interaction_pages(live_session))

    assert len(pages) == 1
    assert pages[0].source_total == 1
    assert pages[0].final_page is True
    item = pages[0].items[0]
    assert item["digital_reply_content"] == "请看三号链接"
    assert item["bullet_reply_content"] == "三号链接"
    assert item["item_id"] == "SKU-3"
    comment_path = next(path for path in session.paths if path.startswith("live_room_comment/"))
    query = parse_qs(urlparse(comment_path).query)
    assert query["created_at_after"] == [maitu_comment_boundary(1_750_000_000)]
    assert query["created_at_before"] == [maitu_comment_boundary(1_750_003_600)]


def test_interaction_room_mismatch_is_rejected() -> None:
    collector = MaituInteractionCollector(_Session())
    with pytest.raises(ValueError, match="unexpected live room"):
        collector._normalize_interaction(
            {"id": 1, "live_room_id": 2},
            expected_live_room_id=3,
        )
