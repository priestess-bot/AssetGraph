from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from browser_use_worker.preflight import ReplacementPlanPreflight


class FakeAssetClient:
    def __init__(self, assets: dict[str, dict[str, Any]]) -> None:
        self.assets = assets
        self.requested_codes: list[str] = []

    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        self.requested_codes.append(asset_code)
        return self.assets.get(asset_code)


@dataclass(slots=True)
class FakeProbe:
    title: str = "MyTwins麦兔直播"
    url: str = "https://live2.maituai.com/Home"
    text: str = "首页\n本地向量检索验证场景\n素材管理"
    logged_in: bool = True
    login_required: bool = False
    opened_home: bool = False


class FakeProbeSession:
    def __init__(self, probe: FakeProbe) -> None:
        self.probe = probe
        self.calls = 0

    def probe_current_page(self, *, open_if_needed: bool = True) -> FakeProbe:
        assert open_if_needed is True
        self.calls += 1
        return self.probe


def write_asset_file(root: Path, relative_path: str, content: bytes = b"video-bytes") -> Path:
    path = root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def asset(relative_path: str = "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4") -> dict[str, Any]:
    return {
        "asset_code": "AG-VID-20260709-000052",
        "display_code": "MT-VID-0024",
        "local_file_code": "MT-VID-0024",
        "title": "视频 - 商品讲解视频 - 品酒大师PRO",
        "local_relative_path": relative_path,
        "file_size": len(b"video-bytes"),
    }


def operation_plan() -> dict[str, Any]:
    return {
        "plan_code": "MT-PLAN-20260709-000001",
        "maitu_project_code": "MT-PROJ-LOCAL-SMOKE",
        "scene_name": "本地向量检索验证场景",
        "operations": [
            {
                "operation_type": "replace_layer_asset",
                "slot_code": "MT-SLOT-20260709-000001",
                "slot_name": "商品讲解视频槽位",
                "asset_code": "AG-VID-20260709-000052",
                "asset_display_code": "MT-VID-0024",
                "asset_local_file_code": "MT-VID-0024",
                "asset_original_filename": "MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
                "asset_local_relative_path": "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
                "asset_browser_use_hint": "用于麦兔视频素材选择：品酒大师PRO，用途：商品讲解视频",
                "instruction": "将素材替换为 MT-VID-0024",
            }
        ],
    }


def test_preflight_passes_for_browser_ready_plan_and_existing_asset_file(tmp_path: Path) -> None:
    relative_path = "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4"
    write_asset_file(tmp_path, relative_path)
    session = FakeProbeSession(FakeProbe())
    preflight = ReplacementPlanPreflight(
        asset_client=FakeAssetClient({"AG-VID-20260709-000052": asset(relative_path)}),
        assets_root=tmp_path,
        session=session,
    )

    result = preflight.run(operation_plan())

    assert result.status == "passed"
    assert result.ready_to_execute is True
    assert result.failure_count == 0
    assert result.warning_count == 0
    assert session.calls == 1
    assert any(check.name == "maitu_browser_probe" and check.status == "pass" for check in result.checks)
    assert any(check.name == "maitu_scene_visibility" and check.status == "pass" for check in result.checks)


def test_preflight_fails_when_browser_use_asset_fields_are_missing(tmp_path: Path) -> None:
    plan = operation_plan()
    plan["operations"][0].pop("asset_browser_use_hint")
    write_asset_file(tmp_path, "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4")
    preflight = ReplacementPlanPreflight(
        asset_client=FakeAssetClient({"AG-VID-20260709-000052": asset()}),
        assets_root=tmp_path,
        session=FakeProbeSession(FakeProbe()),
    )

    result = preflight.run(plan)

    assert result.status == "failed"
    assert result.ready_to_execute is False
    assert any(check.name == "operation[0].browser_use_asset_fields" and check.status == "fail" for check in result.checks)


def test_preflight_fails_when_local_asset_file_is_missing(tmp_path: Path) -> None:
    preflight = ReplacementPlanPreflight(
        asset_client=FakeAssetClient({"AG-VID-20260709-000052": asset()}),
        assets_root=tmp_path,
        session=FakeProbeSession(FakeProbe()),
    )

    result = preflight.run(operation_plan())

    assert result.status == "failed"
    missing_file_check = next(check for check in result.checks if check.name == "operation[0].local_asset_file")
    assert missing_file_check.status == "fail"
    assert "missing" in missing_file_check.summary.lower()


def test_preflight_rejects_unsafe_asset_relative_path(tmp_path: Path) -> None:
    plan = operation_plan()
    plan["operations"][0]["asset_local_relative_path"] = "../secrets.mp4"
    preflight = ReplacementPlanPreflight(
        asset_client=FakeAssetClient({"AG-VID-20260709-000052": asset("../secrets.mp4")}),
        assets_root=tmp_path,
        session=FakeProbeSession(FakeProbe()),
    )

    result = preflight.run(plan)

    assert result.status == "failed"
    unsafe_check = next(check for check in result.checks if check.name == "operation[0].local_asset_file")
    assert unsafe_check.status == "fail"
    assert "unsafe" in unsafe_check.summary.lower()


def test_preflight_fails_when_login_page_is_visible(tmp_path: Path) -> None:
    relative_path = "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4"
    write_asset_file(tmp_path, relative_path)
    preflight = ReplacementPlanPreflight(
        asset_client=FakeAssetClient({"AG-VID-20260709-000052": asset(relative_path)}),
        assets_root=tmp_path,
        session=FakeProbeSession(FakeProbe(url="https://live2.maituai.com/Login", text="手机号\n密码\n登录", logged_in=False, login_required=True)),
    )

    result = preflight.run(operation_plan())

    assert result.status == "failed"
    assert any(check.name == "maitu_browser_probe" and check.status == "fail" for check in result.checks)


def test_preflight_can_skip_browser_probe_but_is_not_ready_to_execute(tmp_path: Path) -> None:
    relative_path = "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4"
    write_asset_file(tmp_path, relative_path)
    preflight = ReplacementPlanPreflight(
        asset_client=FakeAssetClient({"AG-VID-20260709-000052": asset(relative_path)}),
        assets_root=tmp_path,
        session=None,
        probe_browser=False,
    )

    result = preflight.run(operation_plan())

    assert result.status == "warning"
    assert result.ready_to_execute is False
    assert result.failure_count == 0
    assert result.skipped_count == 1
    assert any(check.name == "maitu_browser_probe" and check.status == "skipped" for check in result.checks)
