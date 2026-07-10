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
