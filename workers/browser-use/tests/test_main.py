from __future__ import annotations

from typing import Any

import browser_use_worker.__main__ as worker_main
from browser_use_worker.jd_metrics import JdLiveDashboardState


class FakeAssetGraphClient:
    def __init__(self, _base_url: str) -> None:
        self.samples: list[tuple[str, dict[str, Any]]] = []

    def get_jd_live_metric_session(self, capture_session_code: str) -> dict[str, Any]:
        return {
            "capture_session_code": capture_session_code,
            "dashboard_url": "https://jm.jd.com/live-data",
            "started_at": "2026-07-10T00:00:00+00:00",
        }

    def write_jd_live_metric_sample(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.samples.append((capture_session_code, payload))
        return {"capture_session_code": capture_session_code, "sample_index": len(self.samples) - 1, **payload}

    def update_jd_live_metric_session(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"capture_session_code": capture_session_code, **payload}


class FakeBrowserUseCliSession:
    def read_jd_live_dashboard_state(self, *, open_url: str | None = None) -> JdLiveDashboardState:
        assert open_url == "https://jm.jd.com/live-data"
        return JdLiveDashboardState(
            title="京麦",
            url="https://jm.jd.com/live-data",
            text="直播数据 在线人数 128",
            logged_in=True,
            login_required=False,
            metrics={"online_viewers": 128},
            raw_metrics={"parser": "test"},
        )


def test_main_captures_jd_metric_samples_with_interval(monkeypatch, capsys) -> None:
    fake_client = FakeAssetGraphClient("http://assetgraph")
    sleeps: list[float] = []

    monkeypatch.setattr(worker_main, "AssetGraphClient", lambda base_url: fake_client)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", lambda: FakeBrowserUseCliSession())
    monkeypatch.setattr(worker_main.time, "sleep", lambda seconds: sleeps.append(seconds))

    exit_code = worker_main.main(
        [
            "--capture-jd-metrics",
            "--jd-metric-session-code",
            "JD-METRIC-20260710-000001",
            "--max-samples",
            "2",
            "--capture-interval-seconds",
            "15",
        ]
    )

    assert exit_code == 0
    assert len(fake_client.samples) == 2
    assert sleeps == [15]
    output = capsys.readouterr().out
    assert "JD-METRIC-20260710-000001" in output
    assert '"online_viewers": 128' in output


def test_main_runs_live_scene_fill_and_writes_execution_result(monkeypatch, capsys) -> None:
    operation_plan = {
        "build_plan_code": "MT-BUILD-20260710-000001",
        "reference_room_id": "38336",
        "operations": [
            {"operation_type": "preflight_scene_build_plan", "operation_name": "预检"},
            {
                "operation_type": "create_scene_from_template",
                "operation_name": "创建场景",
                "scene_name": "商品01-场景01",
                "details": {"reference_clip_id": "390051"},
            },
            {"operation_type": "insert_template_component", "operation_name": "插入背景", "layer_name": "背景"},
            {"operation_type": "add_script_block", "operation_name": "写脚本", "script_block_content": "脚本"},
            {"operation_type": "save_live_room", "operation_name": "人工保存", "status": "manual_review"},
        ],
    }

    class FakeClient(FakeAssetGraphClient):
        def __init__(self, base_url: str) -> None:
            super().__init__({"capture_session_code": "JD-METRIC-20260710-000001"})
            self.execution_payloads: list[tuple[str, dict[str, Any]]] = []

        def get_live_room_build_plan_operation_plan(self, build_plan_code: str) -> dict[str, Any]:
            assert build_plan_code == "MT-BUILD-20260710-000001"
            return operation_plan

        def write_live_room_build_plan_execution_result(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.execution_payloads.append((build_plan_code, payload))
            return {"execution_code": "MT-EXEC-20260710-000100", **payload}

    class FakeMaituSession(FakeBrowserUseCliSession):
        def read_live_room(self, live_room_id: str) -> dict[str, Any]:
            return {"topics": [{"clips": [{"id": 416425, "name": "未命名", "order_num": 0}]}]}

        def rename_clip(self, clip_id: int, name: str) -> dict[str, Any]:
            return {"clip_id": clip_id, "name": name}

        def fill_clip_from_template(self, **kwargs) -> dict[str, Any]:
            return {"target_clip_id": kwargs["target_clip_id"], "visual_count": len(kwargs["component_operations"]), "text_count": 1}

    fake_client = FakeClient("http://assetgraph")
    monkeypatch.setattr(worker_main, "AssetGraphClient", lambda base_url: fake_client)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", lambda: FakeMaituSession())

    exit_code = worker_main.main(
        [
            "--build-plan-code",
            "MT-BUILD-20260710-000001",
            "--live-scene-fill",
            "--target-live-room-id",
            "40173",
        ]
    )

    assert exit_code == 0
    assert fake_client.execution_payloads[0][0] == "MT-BUILD-20260710-000001"
    assert fake_client.execution_payloads[0][1]["mode"] == "live_scene_fill"
    assert fake_client.execution_payloads[0][1]["operation_results"][1]["details"]["target_clip_id"] == 416425
    output = capsys.readouterr().out
    assert "MT-EXEC-20260710-000100" in output
