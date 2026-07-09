from __future__ import annotations

from dataclasses import dataclass

from browser_use_worker.build_plan_non_destructive import BuildPlanNonDestructiveRunner
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
    live_room_id: str = "39826"
    logged_in: bool = True
    login_required: bool = False
    scenes: list[FakeScene] | None = None
    active_scene_name: str = "场景01"
    layers: list[FakeLayer] | None = None
    material_tabs: list[FakeTab] | None = None
    workbench_tabs: list[FakeTab] | None = None

    def __post_init__(self) -> None:
        if self.scenes is None:
            self.scenes = [FakeScene("场景01", active=True)]
        if self.layers is None:
            self.layers = [FakeLayer("商品图")]
        if self.material_tabs is None:
            self.material_tabs = [FakeTab("装饰")]
        if self.workbench_tabs is None:
            self.workbench_tabs = [FakeTab("直播脚本")]


class FakeNonDestructiveSession:
    def __init__(self, state: FakeCurrentState | None = None) -> None:
        self.state = state or FakeCurrentState()
        self.calls: list[tuple[str, str | bool | None]] = []

    def read_current_state(self, *, open_if_needed: bool = True) -> FakeCurrentState:
        self.calls.append(("read_current_state", open_if_needed))
        return self.state

    def select_scene(self, scene_name: str) -> dict:
        self.calls.append(("select_scene", scene_name))
        self.state.active_scene_name = scene_name
        return {"clicked": True, "target": scene_name}

    def open_material_tab(self, tab_name: str) -> dict:
        self.calls.append(("open_material_tab", tab_name))
        return {"clicked": True, "target": tab_name}

    def open_workbench_tab(self, tab_name: str) -> dict:
        self.calls.append(("open_workbench_tab", tab_name))
        return {"clicked": True, "target": tab_name}


def build_plan() -> dict:
    return {
        "build_plan_code": "MT-BUILD-20260709-000001",
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
                "required_category": "floating_sticker",
                "accepted_asset_types": ["IMG"],
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


def test_non_destructive_runner_executes_only_allowed_low_risk_actions_after_green_preflight() -> None:
    preflight_session = FakeNonDestructiveSession()
    preflight = BuildPlanPreflight(session=preflight_session).run(build_plan())
    assert preflight.ready_to_execute is True
    action_session = FakeNonDestructiveSession()

    result = BuildPlanNonDestructiveRunner(session=action_session).run(build_plan(), preflight)

    assert result.status == "completed"
    assert result.ready_for_mutation is False
    assert result.build_plan_code == "MT-BUILD-20260709-000001"
    assert result.allowed_action_count == 3
    assert result.blocked_mutation_count == 3
    assert result.failure_count == 0
    assert ("select_scene", "场景01") in action_session.calls
    assert ("open_material_tab", "装饰") in action_session.calls
    assert ("open_workbench_tab", "直播脚本") in action_session.calls
    assert not any(call[0] in {"replace_layer_asset", "save_project"} for call in action_session.calls)
    assert result.actions[1].action_type == "select_scene"
    assert result.actions[2].action_type == "open_material_tab"
    assert result.actions[3].action_type == "open_workbench_tab"
    assert result.actions[4].status == "blocked"


def test_non_destructive_runner_blocks_when_preflight_is_not_green() -> None:
    warning_preflight = BuildPlanPreflight(session=None, probe_browser=False).run(build_plan())
    action_session = FakeNonDestructiveSession()

    result = BuildPlanNonDestructiveRunner(session=action_session).run(build_plan(), warning_preflight)

    assert result.status == "blocked"
    assert result.failure_count == 1
    assert result.allowed_action_count == 0
    assert action_session.calls == []
    assert "preflight" in result.summary
