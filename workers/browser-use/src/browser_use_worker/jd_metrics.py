from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

CORE_METRIC_NAMES = [
    "online_viewers",
    "average_stay_seconds",
    "product_click_rate",
    "product_conversion_rate",
    "gmv",
    "uv_value",
    "product_exposures",
    "product_clicks",
    "transaction_count",
    "transaction_amount",
    "traffic_sources",
    "interaction_data",
]

_NUMBER = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"

METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "online_viewers": ("在线人数", "实时在线", "在线观众", "观看人数"),
    "average_stay_seconds": ("停留时长", "平均停留", "人均停留", "观看时长"),
    "product_click_rate": ("商品点击率", "点击率", "曝光点击率", "观看引商率"),
    "product_conversion_rate": ("商品成交率", "成交率", "转化率", "曝光转化率", "观看成交率"),
    "gmv": ("GMV", "成交金额", "成交额"),
    "uv_value": ("UV价值", "UV 价值", "访客价值"),
    "product_exposures": ("商品曝光", "商卡曝光人数", "曝光人数", "曝光次数"),
    "product_clicks": ("商品点击", "商卡点击人数", "点击人数", "点击次数"),
    "transaction_count": ("成交父单量", "成交数据", "成交订单", "成交件数", "成交人数"),
    "transaction_amount": ("成交金额", "成交额"),
}


@dataclass(slots=True)
class JdLiveDashboardState:
    title: str
    url: str
    text: str
    logged_in: bool
    login_required: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    raw_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JdLiveMetricSamplePayload:
    scene_name: str | None
    scene_index: int | None
    live_elapsed_seconds: int | None
    online_viewers: int | None = None
    average_stay_seconds: float | None = None
    product_click_rate: float | None = None
    product_conversion_rate: float | None = None
    gmv: float | None = None
    uv_value: float | None = None
    product_exposures: int | None = None
    product_clicks: int | None = None
    transaction_count: int | None = None
    transaction_amount: float | None = None
    traffic_sources: dict[str, Any] = field(default_factory=dict)
    interaction_data: dict[str, Any] = field(default_factory=dict)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "captured"


class JdLiveDashboardParser:
    """Heuristic read-only parser for JD live dashboard text snapshots.

    JD dashboard DOM/labels may vary by backend version.  The parser keeps the
    worker useful before selector hardening by extracting known Chinese metric
    labels from page text and preserving the raw text/metrics for later review.
    """

    def parse_state(self, *, title: str, url: str, text: str) -> JdLiveDashboardState:
        login_required = self._looks_like_login(url, text)
        logged_in = self._looks_like_logged_in(url, text) and not login_required
        metrics = self.parse_metrics(text)
        return JdLiveDashboardState(
            title=title,
            url=url,
            text=text,
            logged_in=logged_in,
            login_required=login_required,
            metrics=metrics,
            raw_metrics={"text_excerpt": text[:2000], "parser": "label_near_number_v1"},
        )

    def parse_metrics(self, text: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for metric_name, labels in METRIC_LABELS.items():
            value = self._first_label_value(text, labels)
            if value is None:
                continue
            if metric_name in {"online_viewers", "product_exposures", "product_clicks", "transaction_count"}:
                metrics[metric_name] = int(round(value))
            elif metric_name in {"product_click_rate", "product_conversion_rate"}:
                metrics[metric_name] = self._normalize_rate(text, labels, value)
            else:
                metrics[metric_name] = value
        metrics["traffic_sources"] = self._parse_group(text, ("流量来源", "来源分布"))
        metrics["interaction_data"] = self._parse_interactions(text)
        metrics.update(self._parse_product_table_totals(text))
        return metrics

    def _first_label_value(self, text: str, labels: tuple[str, ...]) -> float | None:
        for label in labels:
            patterns = [
                re.compile(rf"{re.escape(label)}[^0-9%\n]{{0,20}}{_NUMBER}\s*(%|秒|分钟|元)?", re.IGNORECASE),
                # Some dashboard cards render the value on the next line.
                re.compile(rf"{re.escape(label)}\s*\n\s*{_NUMBER}\s*(%|秒|分钟|元)?", re.IGNORECASE),
            ]
            for pattern in patterns:
                for match in pattern.finditer(text):
                    suffix = text[match.start() + len(label) : match.start() + len(label) + 1]
                    if suffix == "率" and not label.endswith("率"):
                        continue
                    value = float(match.group(1).replace(",", ""))
                    unit = match.group(2) or ""
                    if unit == "分钟":
                        value *= 60
                    return value
        return None

    def _normalize_rate(self, text: str, labels: tuple[str, ...], value: float) -> float:
        label_pattern = "|".join(re.escape(label) for label in labels)
        near_percent = re.search(rf"(?:{label_pattern})[^\n]{{0,30}}%", text, re.IGNORECASE) is not None
        if near_percent or value > 1:
            return round(value / 100, 6)
        return round(value, 6)

    def _parse_group(self, text: str, labels: tuple[str, ...]) -> dict[str, float]:
        result: dict[str, float] = {}
        for label in labels:
            start = text.find(label)
            if start < 0:
                continue
            window = text[start : start + 300]
            for name, value in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9_\-]{2,12})\s*[:：]?\s*" + _NUMBER, window):
                if name in label:
                    continue
                result[name] = float(value.replace(",", ""))
            if result:
                break
        return result

    def _parse_interactions(self, text: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for key, labels in {
            "comments": ("评论", "评论数", "评论次数"),
            "likes": ("点赞", "点赞数", "点赞次数"),
            "follows": ("关注", "新增关注"),
        }.items():
            value = self._first_label_value(text, labels)
            if value is not None:
                result[key] = int(round(value))
        return result

    def _parse_product_table_totals(self, text: str) -> dict[str, Any]:
        if not all(label in text for label in ("商卡曝光人数", "商卡点击人数", "曝光点击率")):
            return {}
        total_match = re.search(r"合计\s+(.+)", text)
        if not total_match:
            return {}
        values = [float(value.replace(",", "")) for value in re.findall(_NUMBER, total_match.group(1))]
        if len(values) < 8:
            return {}
        return {
            "product_exposures": int(round(values[0])),
            "product_clicks": int(round(values[1])),
            "product_click_rate": round(values[2] / 100, 6),
            "product_conversion_rate": round(values[5] / 100, 6),
            "transaction_amount": values[6],
            "transaction_count": int(round(values[7])),
        }

    @staticmethod
    def _looks_like_login(url: str, text: str) -> bool:
        compact = text.replace(" ", "")
        return "login" in url.lower() or ("登录" in compact and ("密码" in compact or "验证码" in compact))

    @staticmethod
    def _looks_like_logged_in(url: str, text: str) -> bool:
        combined = f"{url}\n{text}"
        return any(marker in combined for marker in ("直播数据", "实时数据", "数据中心", "京麦", "商家后台", "京东直播", "场次分析"))


def scene_context_for_sample(session: dict[str, Any], *, sampled_at: datetime | None = None) -> tuple[str | None, int | None, int | None]:
    sampled_at = sampled_at or datetime.now(UTC)
    current_scene_name = session.get("current_scene_name")
    current_scene_index = session.get("current_scene_index")
    started_at = session.get("started_at")
    elapsed_seconds: int | None = None
    if isinstance(started_at, str):
        try:
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            started_at = None
    if isinstance(started_at, datetime):
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        elapsed_seconds = max(0, int((sampled_at - started_at).total_seconds()))
    for scene in session.get("scene_schedule") or []:
        if elapsed_seconds is None or not isinstance(scene, dict):
            continue
        start = scene.get("start_offset_seconds")
        end = scene.get("end_offset_seconds")
        if start is None:
            continue
        if elapsed_seconds >= int(start) and (end is None or elapsed_seconds < int(end)):
            return scene.get("scene_name"), scene.get("scene_index"), elapsed_seconds
    return current_scene_name, current_scene_index, elapsed_seconds


def build_jd_live_metric_sample_payload(
    session: dict[str, Any],
    state: JdLiveDashboardState,
    *,
    sampled_at: datetime | None = None,
) -> dict[str, Any]:
    sampled_at = sampled_at or datetime.now(UTC)
    scene_name, scene_index, live_elapsed_seconds = scene_context_for_sample(session, sampled_at=sampled_at)
    payload = JdLiveMetricSamplePayload(
        scene_name=scene_name,
        scene_index=scene_index,
        live_elapsed_seconds=live_elapsed_seconds,
        raw_metrics={**state.raw_metrics, "url": state.url, "title": state.title, "metrics": state.metrics},
    )
    for metric_name in CORE_METRIC_NAMES:
        if metric_name in state.metrics:
            setattr(payload, metric_name, state.metrics[metric_name])
    result = {key: value for key, value in asdict(payload).items() if value is not None}
    result["sampled_at"] = sampled_at.isoformat()
    return result


def _dashboard_url_from_session(session: dict[str, Any]) -> str | None:
    raw_url = session.get("dashboard_url")
    if not raw_url:
        config = session.get("config")
        if isinstance(config, dict):
            raw_url = config.get("dashboard_url")
    if not raw_url:
        return None
    url = str(raw_url)
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("dashboard_url must be a trusted JD dashboard HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"jm.jd.com", "jlive.jd.com"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("dashboard_url must be a trusted JD dashboard HTTPS URL")
    return url


def _has_core_numeric_metrics(metrics: dict[str, Any]) -> bool:
    return any(
        metric_name in metrics and metrics[metric_name] is not None
        for metric_name in CORE_METRIC_NAMES
        if metric_name not in {"traffic_sources", "interaction_data"}
    )


def capture_jd_live_metric_sample(
    client: Any,
    capture_session_code: str,
    *,
    browser_session: Any,
    sampled_at: datetime | None = None,
) -> dict[str, Any]:
    """Read the current JD live dashboard and write one synchronized sample.

    The capture is deliberately fail-closed: if the JD dashboard is on a login
    page or cannot be recognized as logged in, the worker still writes a
    `blocked` sample with raw evidence instead of inventing metrics.
    """

    sampled_at = sampled_at or datetime.now(UTC)
    session = client.get_jd_live_metric_session(capture_session_code)
    state: JdLiveDashboardState = browser_session.read_jd_live_dashboard_state(
        open_url=_dashboard_url_from_session(session),
    )
    payload = build_jd_live_metric_sample_payload(session, state, sampled_at=sampled_at)
    if state.login_required or not state.logged_in:
        payload["status"] = "blocked"
        payload.setdefault("raw_metrics", {})["failure_type"] = "login_required" if state.login_required else "dashboard_not_detected"
        payload["raw_metrics"]["ready_to_capture"] = False
    elif not _has_core_numeric_metrics(state.metrics):
        payload["status"] = "blocked"
        payload.setdefault("raw_metrics", {})["failure_type"] = "live_dashboard_not_detected"
        payload["raw_metrics"]["ready_to_capture"] = False
    else:
        payload.setdefault("raw_metrics", {})["ready_to_capture"] = True
    return client.write_jd_live_metric_sample(capture_session_code, payload)
