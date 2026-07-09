from __future__ import annotations

from dataclasses import dataclass

from browser_use_worker.build_plan_preflight import BuildPlanPreflight


@dataclass(slots=True)
class FakeScene:
    name: str
    active: bool = False


@dataclass(slots=True)
class FakeLayer:
    name: str
    active: bool = False


@dataclass(slots=True)
class FakeTab:
    name: str
    active: bool = False


@dataclass(slots=True)
class FakeCurrentState:
    title: str = "MyTwins麦兔直播"
    url: str = "https://live2.maituai.com/LiveRoom?liveRoomId=39826"
    text: str = "场景01\n商品图\n直播脚本"
    live_room_id: str | None = "39826"
    live_room_name: str | None = "京东空白直播间-0707-1352"
    platform: str | None = "京东版"
    logged_in: bool = True
    login_required: bool = False
    scenes: list[FakeScene] | None = None
    active_scene_name: str | None = "场景01"
    layers: list[FakeLayer] | None = None
    workbench_tabs: list[FakeTab] | None = None
    active_workbench_tab: str | None = None


class FakeCurrentStateSession:
    def __init__(self, state: FakeCurrentState) -> None:
        self.state = state
        self.calls = 0

    def read_current_state(self, *, open_if_needed: bool = True) -> FakeCurrentState:
        assert open_if_needed is True
        self.calls += 1
        return self.state


def build_plan() -> dict:
    return {
        "build_plan_code": "MT-BUILD-20260709-000001",
        "blueprint_code": "MT-BP-20260709-39826",
        "reference_room_id": "39826",
        "operations": [
            {
                "operation_type": "preflight_build_plan",
                "operation_name": "只读预检",
                "sort_order": 1,
                "status": "ready",
                "instruction": "只读确认当前麦兔页面，默认不点击正式开播。",
            },
            {
                "operation_type": "select_scene",
                "operation_name": "选择场景01",
                "sort_order": 10,
                "status": "ready",
                "scene_name": "场景01",
                "instruction": "只做定位不保存。",
            },
            {
                "operation_type": "replace_layer_asset",
                "operation_name": "规划商品图",
                "sort_order": 20,
                "status": "planned",
                "scene_name": "场景01",
                "layer_name": "商品图",
                "replacement_policy": "keep_layout",
                "instruction": "定位商品图图层并保持原布局。",
            },
            {
                "operation_type": "add_script_block",
                "operation_name": "写脚本块",
                "sort_order": 30,
                "status": "planned",
                "scene_name": "场景01",
                "script_block_code": "SCRIPT-1",
                "script_block_content": "大家好，今天介绍品酒大师PRO。",
                "instruction": "写入脚本块，写入后重新 Observe。",
            },
            {
                "operation_type": "save_live_room",
                "operation_name": "保存直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "instruction": "仅保存草稿；默认不点击正式开播。",
            },
        ],
    }


def ready_state() -> FakeCurrentState:
    return FakeCurrentState(
        scenes=[FakeScene("场景01", active=True)],
        layers=[FakeLayer("商品图", active=False)],
        workbench_tabs=[FakeTab("直播脚本", active=True), FakeTab("直播互动")],
    )


def test_build_plan_preflight_passes_for_matching_current_state() -> None:
    session = FakeCurrentStateSession(ready_state())

    result = BuildPlanPreflight(session=session).run(build_plan())

    assert result.status == "passed"
    assert result.ready_to_execute is True
    assert result.failure_count == 0
    assert result.warning_count == 0
    assert result.build_plan_code == "MT-BUILD-20260709-000001"
    assert session.calls == 1
    assert any(check.name == "maitu_live_room_id" and check.status == "pass" for check in result.checks)
    assert any(check.name == "operation[2].active_scene_layer_visibility" and check.status == "pass" for check in result.checks)


def test_build_plan_preflight_rejects_unsafe_save_and_go_live_instruction() -> None:
    plan = build_plan()
    plan["operations"][-1]["status"] = "ready"
    plan["operations"][-1]["instruction"] = "保存后点击正式开播。"

    result = BuildPlanPreflight(session=FakeCurrentStateSession(ready_state())).run(plan)

    assert result.status == "failed"
    assert result.ready_to_execute is False
    assert any(check.name == "operation[4].save_live_room_manual_review" and check.status == "fail" for check in result.checks)
    assert any(check.name == "operation[4].go_live_safety" and check.status == "fail" for check in result.checks)


def test_build_plan_preflight_fails_when_active_scene_layer_is_missing() -> None:
    state = ready_state()
    state.layers = [FakeLayer("其它图层")]

    result = BuildPlanPreflight(session=FakeCurrentStateSession(state)).run(build_plan())

    assert result.status == "failed"
    check = next(check for check in result.checks if check.name == "operation[2].active_scene_layer_visibility")
    assert check.status == "fail"
    assert check.details["layer_name"] == "商品图"


def test_build_plan_preflight_warns_for_non_active_scene_layer() -> None:
    plan = build_plan()
    plan["operations"][2]["scene_name"] = "场景02"
    state = FakeCurrentState(
        scenes=[FakeScene("场景01", active=True), FakeScene("场景02")],
        active_scene_name="场景01",
        layers=[FakeLayer("商品图")],
        workbench_tabs=[FakeTab("直播脚本")],
    )

    result = BuildPlanPreflight(session=FakeCurrentStateSession(state)).run(plan)

    assert result.status == "warning"
    assert result.ready_to_execute is False
    assert result.failure_count == 0
    assert any(check.name == "operation[2].inactive_scene_layer_visibility" and check.status == "warning" for check in result.checks)


def test_build_plan_preflight_can_skip_browser_probe_but_is_not_ready() -> None:
    result = BuildPlanPreflight(session=None, probe_browser=False).run(build_plan())

    assert result.status == "warning"
    assert result.ready_to_execute is False
    assert result.failure_count == 0
    assert result.skipped_count == 1
    assert any(check.name == "maitu_current_state_probe" and check.status == "skipped" for check in result.checks)
