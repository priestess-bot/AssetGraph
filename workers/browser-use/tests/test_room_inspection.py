from __future__ import annotations

import pytest

from browser_use_worker.functional_test_draft import room_inspection_fingerprint
from browser_use_worker.room_inspection import inspect_working_room


class Session:
    def __init__(self, room):
        self.room = room

    def read_live_room(self, live_room_id: str):
        assert live_room_id == "41172"
        return self.room


def room():
    return {
        "id": 41172,
        "name": "asser测试",
        "status": 0,
        "live_session_id": None,
        "latest_live_time": None,
        "_assetgraph_read_environment": "working",
        "topics": [
            {
                "clips": [
                    {"id": 2, "name": "第二场", "order_num": 1, "clip_materials": []},
                    {"id": 1, "name": "第一场", "order_num": 0, "clip_materials": [{"id": 9}]},
                ]
            }
        ],
    }


def test_inspection_returns_stable_ordered_offline_snapshot() -> None:
    result = inspect_working_room(
        Session(room()), target_live_room_id="41172", expected_title="asser测试"
    )
    assert result["is_live"] is False
    assert result["has_live_trace"] is False
    assert [item["scene_id"] for item in result["scenes"]] == ["1", "2"]
    assert result["scenes"][0]["material_count"] == 1
    assert len(room_inspection_fingerprint(result)) == 64


def test_inspection_rejects_a_live_room() -> None:
    payload = room()
    payload["status"] = 1
    result = inspect_working_room(
        Session(payload), target_live_room_id="41172", expected_title="asser测试"
    )
    assert result["is_live"] is True


def test_inspection_rejects_non_working_readback() -> None:
    payload = room()
    payload["_assetgraph_read_environment"] = "published"
    with pytest.raises(ValueError, match="working environment"):
        inspect_working_room(
            Session(payload), target_live_room_id="41172", expected_title="asser测试"
        )
