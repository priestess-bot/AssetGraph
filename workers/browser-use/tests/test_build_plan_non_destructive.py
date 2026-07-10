from __future__ import annotations

from dataclasses import dataclass

from browser_use_worker.build_plan_non_destructive import BuildPlanNonDestructiveRunner, build_non_destructive_execution_payload
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


def test_build_non_destructive_execution_payload_maps_actions_to_api_shape() -> None:
    preflight = BuildPlanPreflight(session=FakeNonDestructiveSession()).run(build_plan())
    result = BuildPlanNonDestructiveRunner(session=FakeNonDestructiveSession()).run(build_plan(), preflight)

    payload = build_non_destructive_execution_payload(result)

    assert payload["execution_status"] == "completed"
    assert payload["mode"] == "non_destructive"
    assert payload["result_summary"] == result.summary
    assert payload["operation_results"][1]["operation_index"] == 1
    assert payload["operation_results"][1]["operation_type"] == "select_scene"
    assert payload["operation_results"][1]["action_type"] == "select_scene"
    assert payload["operation_results"][1]["status"] == "executed"
    assert payload["operation_results"][2]["details"]["replacement_blocked"] is True


def test_build_non_destructive_execution_payload_includes_synthetic_blocked_preflight_result() -> None:
    warning_preflight = BuildPlanPreflight(session=None, probe_browser=False).run(build_plan())
    result = BuildPlanNonDestructiveRunner(session=FakeNonDestructiveSession()).run(build_plan(), warning_preflight)

    payload = build_non_destructive_execution_payload(result)

    assert payload["execution_status"] == "blocked"
    assert payload["failure_type"] == "preflight_not_green"
    assert payload["operation_results"] == [
        {
            "operation_index": 0,
            "operation_type": "preflight_build_plan",
            "operation_name": "BuildPlan preflight gate",
            "action_type": "preflight_gate",
            "status": "blocked",
            "failure_type": "preflight_not_green",
            "retryable": False,
            "error_message": result.summary,
            "details": {
                "ready_for_mutation": False,
                "allowed_action_count": 0,
                "blocked_mutation_count": 0,
                "failure_count": 1,
            },
        }
    ]


def scene_build_plan() -> dict:
    return {
        "build_plan_code": "MT-BUILD-20260710-000001",
        "reference_room_id": "39826",
        "operations": [
            {
                "operation_type": "preflight_scene_build_plan",
                "operation_name": "只读预检单场景搭建计划",
                "sort_order": 1,
                "status": "ready",
                "instruction": "预检单场景模板和禁开播规则；此计划为 dry-run，不直接操作麦兔。",
                "details": {"scene_template_code": "MT-TPL-SCENE-38336-001"},
            },
            {
                "operation_type": "create_scene_from_template",
                "operation_name": "按模板创建单场景 商品01-场景01",
                "sort_order": 10,
                "status": "planned",
                "scene_name": "商品01-场景01",
                "instruction": "按模板场景复刻结构；只生成计划，不点击正式开播。",
                "details": {"scene_template_code": "MT-TPL-SCENE-38336-001"},
            },
            {
                "operation_type": "insert_template_component",
                "operation_name": "插入模板组件 背景",
                "sort_order": 20,
                "status": "planned",
                "scene_name": "商品01-场景01",
                "layer_name": "微信图片_20260618221607_11_15",
                "layer_role": "background",
                "required_category": "background_image",
                "accepted_asset_types": ["IMG"],
                "replacement_policy": "keep_layout",
                "instruction": "插入/配置背景组件，保持模板坐标、尺寸和层级。",
                "details": {
                    "scene_template_code": "MT-TPL-SCENE-38336-001",
                    "component_template_code": "MT-TPL-LAYER-38336-001-01",
                    "geometry": {"left": 0, "top": 0, "width": 1080, "height": 1919, "scale": None},
                },
            },
            {
                "operation_type": "add_script_block",
                "operation_name": "写入单场景脚本",
                "sort_order": 30,
                "status": "planned",
                "scene_name": "商品01-场景01",
                "script_block_content": "今天我们用张裕夏日主题的结构讲龙谕龙8。",
                "instruction": "写入目标脚本，并回读确认文本一致。",
            },
            {
                "operation_type": "save_live_room",
                "operation_name": "保存单场景直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "scene_name": "商品01-场景01",
                "instruction": "只在组件和脚本回读验证通过后保存草稿；禁止点击正式开播。",
            },
        ],
    }


def test_scene_build_plan_non_destructive_opens_tabs_but_blocks_scene_creation_insert_and_save() -> None:
    state = FakeCurrentState(
        scenes=[FakeScene("商品01-场景01", active=True)],
        active_scene_name="商品01-场景01",
        layers=[FakeLayer("微信图片_20260618221607_11_15")],
        material_tabs=[FakeTab("背景")],
        workbench_tabs=[FakeTab("直播脚本")],
    )
    preflight_session = FakeNonDestructiveSession(state)
    preflight = BuildPlanPreflight(session=preflight_session).run(scene_build_plan())
    assert preflight.ready_to_execute is True
    action_session = FakeNonDestructiveSession(state)

    result = BuildPlanNonDestructiveRunner(session=action_session).run(scene_build_plan(), preflight)

    assert result.status == "completed"
    assert result.allowed_action_count == 2
    assert result.blocked_mutation_count == 4
    assert result.failure_count == 0
    assert ("open_material_tab", "背景") in action_session.calls
    assert ("open_workbench_tab", "直播脚本") in action_session.calls
    assert not any(call[0] in {"create_scene", "insert_template_component", "save_project"} for call in action_session.calls)
    assert result.actions[0].action_type == "preflight_already_passed"
    assert result.actions[1].action_type == "create_scene_from_template_blocked"
    assert result.actions[2].action_type == "open_material_tab"
    assert result.actions[3].action_type == "open_workbench_tab"
    assert result.actions[4].status == "blocked"
