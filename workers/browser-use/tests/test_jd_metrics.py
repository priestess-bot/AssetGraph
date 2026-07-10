from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from browser_use_worker.jd_metrics import (
    JdLiveDashboardParser,
    JdLiveDashboardState,
    build_jd_live_metric_sample_payload,
    capture_jd_live_metric_sample,
)


class FakeAssetGraphClient:
    def __init__(self, metric_session: dict[str, Any]) -> None:
        self.metric_session = metric_session
        self.written_samples: list[tuple[str, dict[str, Any]]] = []

    def get_jd_live_metric_session(self, capture_session_code: str) -> dict[str, Any]:
        assert capture_session_code == self.metric_session["capture_session_code"]
        return self.metric_session

    def write_jd_live_metric_sample(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.written_samples.append((capture_session_code, payload))
        return {"capture_session_code": capture_session_code, "sample_index": len(self.written_samples) - 1, **payload}


class FakeBrowserSession:
    def __init__(self, state: JdLiveDashboardState) -> None:
        self.state = state
        self.opened_urls: list[str | None] = []

    def read_jd_live_dashboard_state(self, *, open_url: str | None = None) -> JdLiveDashboardState:
        self.opened_urls.append(open_url)
        return self.state


def test_jd_live_dashboard_parser_extracts_core_metrics() -> None:
    text = """
    京东商家后台
    直播数据
    在线人数 128
    平均停留 42.5秒
    商品点击率 18%
    商品成交率 3.1%
    GMV 9,865.50元
    UV价值 12.34
    商品曝光 1200
    商品点击 216
    成交订单 11
    成交金额 9865.5元
    流量来源 推荐 80 店铺 48
    评论 14
    点赞 266
    """

    state = JdLiveDashboardParser().parse_state(title="京麦", url="https://jm.jd.com/live-data", text=text)

    assert state.logged_in is True
    assert state.login_required is False
    assert state.metrics["online_viewers"] == 128
    assert state.metrics["average_stay_seconds"] == 42.5
    assert state.metrics["product_click_rate"] == 0.18
    assert state.metrics["product_conversion_rate"] == 0.031
    assert state.metrics["gmv"] == 9865.5
    assert state.metrics["uv_value"] == 12.34
    assert state.metrics["product_exposures"] == 1200
    assert state.metrics["product_clicks"] == 216
    assert state.metrics["transaction_count"] == 11
    assert state.metrics["transaction_amount"] == 9865.5
    assert state.metrics["traffic_sources"]["推荐"] == 80
    assert state.metrics["traffic_sources"]["店铺"] == 48
    assert state.metrics["interaction_data"]["comments"] == 14
    assert state.metrics["interaction_data"]["likes"] == 266


def test_jd_live_dashboard_parser_extracts_core_metrics_from_jlive_session_analysis() -> None:
    text = """
    场次分析
    直播中
    直播间ID：47030662
    趋势与渠道分布
    观看人数
    713
    成交父单量
    19
    成交金额
    5965.36
    观看引商率
    52.88%
    观看成交率
    2.66%
    用户互动分析
    点赞次数
    182
    观看时长
    24秒
    商品分析
    商卡曝光人数 商卡点击人数 曝光点击率 加购人数 成交人数 曝光转化率 成交金额 成交父单量
    合计 1,292 388 30.0% 14 19 1.5% ￥5,965.36 19
    """

    state = JdLiveDashboardParser().parse_state(title="场次分析 - 京东直播", url="https://jlive.jd.com/dataCenter/sessionAnalysis", text=text)

    assert state.logged_in is True
    assert state.metrics["online_viewers"] == 713
    assert state.metrics["average_stay_seconds"] == 24
    assert state.metrics["product_click_rate"] == 0.3
    assert state.metrics["product_conversion_rate"] == 0.015
    assert state.metrics["gmv"] == 5965.36
    assert state.metrics["product_exposures"] == 1292
    assert state.metrics["product_clicks"] == 388
    assert state.metrics["transaction_count"] == 19
    assert state.metrics["transaction_amount"] == 5965.36
    assert state.metrics["interaction_data"]["likes"] == 182


def test_build_jd_live_metric_sample_payload_aligns_sample_to_scene_schedule() -> None:
    state = JdLiveDashboardState(
        title="京麦",
        url="https://jm.jd.com/live-data",
        text="直播数据",
        logged_in=True,
        login_required=False,
        metrics={"online_viewers": 128, "gmv": 9865.5},
        raw_metrics={"parser": "test"},
    )
    session = {
        "started_at": "2026-07-10T00:00:00+00:00",
        "current_scene_name": "兜底场景",
        "current_scene_index": 99,
        "scene_schedule": [
            {"scene_index": 0, "scene_name": "商品01-场景01", "start_offset_seconds": 0, "end_offset_seconds": 60},
            {"scene_index": 1, "scene_name": "商品01-场景02", "start_offset_seconds": 60, "end_offset_seconds": 120},
        ],
    }

    payload = build_jd_live_metric_sample_payload(
        session,
        state,
        sampled_at=datetime(2026, 7, 10, 0, 0, 30, tzinfo=UTC),
    )

    assert payload["scene_name"] == "商品01-场景01"
    assert payload["scene_index"] == 0
    assert payload["live_elapsed_seconds"] == 30
    assert payload["online_viewers"] == 128
    assert payload["gmv"] == 9865.5
    assert payload["status"] == "captured"
    assert payload["raw_metrics"]["parser"] == "test"


def test_capture_jd_live_metric_sample_reads_dashboard_and_writes_sample() -> None:
    sampled_at = datetime(2026, 7, 10, 0, 0, 30, tzinfo=UTC)
    metric_session = {
        "capture_session_code": "JD-METRIC-20260710-000001",
        "dashboard_url": "https://jm.jd.com/live-data",
        "started_at": "2026-07-10T00:00:00+00:00",
        "scene_schedule": [
            {"scene_index": 0, "scene_name": "商品01-场景01", "start_offset_seconds": 0, "end_offset_seconds": 60}
        ],
    }
    client = FakeAssetGraphClient(metric_session)
    browser_session = FakeBrowserSession(
        JdLiveDashboardState(
            title="京麦",
            url="https://jm.jd.com/live-data",
            text="直播数据 在线人数 128",
            logged_in=True,
            login_required=False,
            metrics={"online_viewers": 128},
            raw_metrics={"parser": "test"},
        )
    )

    result = capture_jd_live_metric_sample(
        client,
        "JD-METRIC-20260710-000001",
        browser_session=browser_session,
        sampled_at=sampled_at,
    )

    assert browser_session.opened_urls == ["https://jm.jd.com/live-data"]
    assert result["sample_index"] == 0
    assert client.written_samples[0][0] == "JD-METRIC-20260710-000001"
    assert client.written_samples[0][1]["online_viewers"] == 128
    assert client.written_samples[0][1]["scene_name"] == "商品01-场景01"


@pytest.mark.parametrize(
    "dashboard_url",
    [
        "http://jm.jd.com/live-data",
        "https://jm.jd.com:444/live-data",
        "https://user@jm.jd.com/live-data",
        "https://jm.jd.com.evil.test/live-data",
        "https://evil.test/?next=jlive.jd.com",
        "file:///C:/Users/59521/.ssh/id_rsa",
    ],
)
def test_capture_jd_live_metric_sample_rejects_untrusted_dashboard_url_before_browser_navigation(
    dashboard_url: str,
) -> None:
    metric_session = {
        "capture_session_code": "JD-METRIC-20260710-000001",
        "dashboard_url": dashboard_url,
    }
    client = FakeAssetGraphClient(metric_session)
    browser_session = FakeBrowserSession(
        JdLiveDashboardState(
            title="unused",
            url=dashboard_url,
            text="unused",
            logged_in=False,
            login_required=False,
            metrics={},
            raw_metrics={},
        )
    )

    with pytest.raises(ValueError, match="trusted JD dashboard"):
        capture_jd_live_metric_sample(
            client,
            "JD-METRIC-20260710-000001",
            browser_session=browser_session,
        )

    assert browser_session.opened_urls == []
    assert client.written_samples == []


def test_capture_jd_live_metric_sample_writes_blocked_sample_when_dashboard_has_no_core_metrics() -> None:
    metric_session = {"capture_session_code": "JD-METRIC-20260710-000001", "dashboard_url": "https://jm.jd.com/live-data"}
    client = FakeAssetGraphClient(metric_session)
    browser_session = FakeBrowserSession(
        JdLiveDashboardState(
            title="京麦工作台",
            url="https://jm.jd.com/index/index.html",
            text="京麦首页 服务市场 精品应用",
            logged_in=True,
            login_required=False,
            metrics={"traffic_sources": {}, "interaction_data": {}},
            raw_metrics={"parser": "test"},
        )
    )

    result = capture_jd_live_metric_sample(
        client,
        "JD-METRIC-20260710-000001",
        browser_session=browser_session,
        sampled_at=datetime(2026, 7, 10, 0, 0, 30, tzinfo=UTC),
    )

    assert result["status"] == "blocked"
    assert client.written_samples[0][1]["raw_metrics"]["failure_type"] == "live_dashboard_not_detected"


def test_capture_jd_live_metric_sample_writes_blocked_sample_when_login_required() -> None:
    metric_session = {"capture_session_code": "JD-METRIC-20260710-000001", "dashboard_url": "https://jm.jd.com/live-data"}
    client = FakeAssetGraphClient(metric_session)
    browser_session = FakeBrowserSession(
        JdLiveDashboardState(
            title="京麦登录",
            url="https://jm.jd.com/login",
            text="账号 密码 登录",
            logged_in=False,
            login_required=True,
            metrics={},
            raw_metrics={"parser": "test"},
        )
    )

    result = capture_jd_live_metric_sample(
        client,
        "JD-METRIC-20260710-000001",
        browser_session=browser_session,
        sampled_at=datetime(2026, 7, 10, 0, 0, 30, tzinfo=UTC),
    )

    assert result["status"] == "blocked"
    assert client.written_samples[0][1]["raw_metrics"]["failure_type"] == "login_required"
