from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import browser_use_worker.__main__ as worker_main
from browser_use_worker.jd_metrics import JdLiveDashboardState
from browser_use_worker.maitu_material_resolver import (
    MaituMaterialResolutionIssue,
    MaituMaterialResolver as RealMaituMaterialResolver,
)
from browser_use_worker.client import AssetGraphClientError
from browser_use_worker.workbench_draft_lease import WorkbenchDraftLeaseError


class FakeAssetGraphClient:
    def __init__(self, _base_url: str) -> None:
        self.samples: list[tuple[str, dict[str, Any]]] = []
        self.session_updates: list[tuple[str, dict[str, Any]]] = []

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
        self.session_updates.append((capture_session_code, dict(payload)))
        return {"capture_session_code": capture_session_code, **payload}


class FakeBrowserUseCliSession:
    def set_execution_guard(self, guard: Any) -> None:
        self.execution_guard = guard

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


def executable_script_layout_gate() -> dict[str, Any]:
    return {
        "status": "ready",
        "can_execute": True,
        "manual_review_required": False,
        "blocked_reasons": [],
    }


def test_parse_args_uses_environment_asset_root(monkeypatch) -> None:
    monkeypatch.setenv("ASSETGRAPH_ASSETS_ROOT", "/srv/assetgraph-assets")

    args = worker_main.parse_args(["--check-config"])

    assert args.assets_root == "/srv/assetgraph-assets"


def test_check_config_rejects_conflicting_execution_mode_before_client_start(monkeypatch) -> None:
    client_started = False

    def forbidden_client(_base_url: str):
        nonlocal client_started
        client_started = True
        raise AssertionError("client must not start for an invalid mode combination")

    monkeypatch.setattr(worker_main, "AssetGraphClient", forbidden_client)

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main(["--check-config", "--probe-maitu"])

    assert "Conflicting CLI modes" in str(exc_info.value)
    assert client_started is False


def test_check_config_redacts_script_layout_worker_capability(monkeypatch, capsys) -> None:
    worker_token = "worker-capability-must-not-print"
    monkeypatch.setenv("ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN", worker_token)

    assert worker_main.main(["--check-config"]) == 0

    output = capsys.readouterr().out
    assert worker_token not in output
    parsed = json.loads(output)
    assert parsed["script_layout_worker_token"] == "[CONFIGURED]"


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
    assert fake_client.session_updates[-1][1]["status"] == "completed"
    assert sleeps == [15]
    output = capsys.readouterr().out
    assert "JD-METRIC-20260710-000001" in output
    assert '"online_viewers": 128' in output


def test_main_returns_nonzero_and_marks_metric_session_blocked_when_capture_is_blocked(monkeypatch, capsys) -> None:
    fake_client = FakeAssetGraphClient("http://assetgraph")
    monkeypatch.setattr(worker_main, "AssetGraphClient", lambda base_url: fake_client)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", lambda: FakeBrowserUseCliSession())
    monkeypatch.setattr(
        worker_main,
        "capture_jd_live_metric_sample",
        lambda *_args, **_kwargs: {
            "status": "blocked",
            "raw_metrics": {"ready_to_capture": False, "failure_type": "login_required"},
        },
    )

    exit_code = worker_main.main(
        [
            "--capture-jd-metrics",
            "--jd-metric-session-code",
            "JD-METRIC-BLOCKED",
        ]
    )

    assert exit_code == 2
    assert fake_client.session_updates[-1][1]["status"] == "blocked"
    assert '"status": "blocked"' in capsys.readouterr().out


def test_main_fails_closed_when_metric_capture_returns_failed_status(monkeypatch, capsys) -> None:
    fake_client = FakeAssetGraphClient("http://assetgraph")
    monkeypatch.setattr(worker_main, "AssetGraphClient", lambda base_url: fake_client)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", lambda: FakeBrowserUseCliSession())
    monkeypatch.setattr(
        worker_main,
        "capture_jd_live_metric_sample",
        lambda *_args, **_kwargs: {
            "status": "failed",
            "raw_metrics": {"ready_to_capture": True, "failure_type": "upstream_rejected"},
        },
    )

    exit_code = worker_main.main(
        [
            "--capture-jd-metrics",
            "--jd-metric-session-code",
            "JD-METRIC-FAILED",
        ]
    )

    assert exit_code == 2
    assert fake_client.session_updates[-1][1]["status"] == "failed"
    assert '"status": "failed"' in capsys.readouterr().out


def test_main_marks_metric_session_failed_when_capture_raises(monkeypatch, capsys) -> None:
    fake_client = FakeAssetGraphClient("http://assetgraph")
    monkeypatch.setattr(worker_main, "AssetGraphClient", lambda base_url: fake_client)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", lambda: FakeBrowserUseCliSession())

    def fail_capture(*_args, **_kwargs):
        raise RuntimeError("dashboard read failed")

    monkeypatch.setattr(worker_main, "capture_jd_live_metric_sample", fail_capture)

    exit_code = worker_main.main(
        [
            "--capture-jd-metrics",
            "--jd-metric-session-code",
            "JD-METRIC-FAILED",
        ]
    )

    assert exit_code == 2
    assert fake_client.session_updates[-1][1]["status"] == "failed"
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert "dashboard read failed" in output["result_summary"]


def test_main_runs_live_scene_fill_and_writes_execution_result(monkeypatch, capsys) -> None:
    operation_plan = {
        "build_plan_code": "MT-BUILD-20260710-000001",
        "reference_room_id": "38336",
        "target_live_room_id": "40173",
        "operations": [
            {
                "operation_type": "preflight_scene_build_plan",
                "operation_name": "预检",
                "status": "ready",
                "details": {"safety_gate": True, "target_live_room_id": "40173"},
            },
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
            return {
                "id": live_room_id,
                "is_live": False,
                "_assetgraph_read_environment": "working",
                "topics": [{"clips": [{"id": 416425, "name": "未命名", "order_num": 0}]}],
            }

        def rename_clip(self, *, live_room_id: str, clip_id: int, name: str) -> dict[str, Any]:
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

    assert exit_code == 2
    assert fake_client.execution_payloads[0][0] == "MT-BUILD-20260710-000001"
    assert fake_client.execution_payloads[0][1]["mode"] == "live_scene_fill"
    assert fake_client.execution_payloads[0][1]["operation_results"][1]["details"]["target_clip_id"] == 416425
    output = capsys.readouterr().out
    assert "MT-EXEC-20260710-000100" in output


def test_main_rejects_live_scene_fill_target_mismatch_before_browser_start(monkeypatch) -> None:
    class TargetMismatchClient(FakeAssetGraphClient):
        def get_live_room_build_plan_operation_plan(self, _build_plan_code: str) -> dict[str, Any]:
            return {"target_live_room_id": "50002", "operations": []}

    browser_started = False

    def forbidden_browser():
        nonlocal browser_started
        browser_started = True
        raise AssertionError("browser must not start before the live-scene target gate")

    monkeypatch.setattr(worker_main, "AssetGraphClient", TargetMismatchClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", forbidden_browser)

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main(
            [
                "--build-plan-code",
                "MT-BUILD-TARGET-MISMATCH",
                "--live-scene-fill",
                "--target-live-room-id",
                "40173",
            ]
        )

    assert "does not match" in str(exc_info.value)
    assert browser_started is False


def test_main_resolves_maitu_materials_and_writes_resolved_plan(monkeypatch, capsys, tmp_path: Path) -> None:
    asset_code = "AG-IMG-20260710-000099"
    plan_path = tmp_path / "plan.json"
    resolved_path = tmp_path / "resolved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                **executable_script_layout_gate(),
                "build_plan_code": "MT-LAYOUT-BUILD-20260710-000001",
                "operations": [
                    {
                        "operation_type": "insert_asset_layer",
                        "asset_code": asset_code,
                        "layer_type": "product_image",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class ResolverClient(FakeAssetGraphClient):
        def __init__(self, base_url: str) -> None:
            super().__init__(base_url)
            self.asset = {
                "asset_code": asset_code,
                "subject": "礼盒",
                "original_filename": "礼盒.png",
                "local_relative_path": "商品图/礼盒.png",
            }
            self.binding_updates: list[dict[str, Any]] = []

        def get_asset(self, requested_asset_code: str) -> dict[str, Any] | None:
            return dict(self.asset) if requested_asset_code == asset_code else None

        def update_asset_maitu_material_binding(self, requested_asset_code: str, payload: dict[str, Any]) -> dict[str, Any]:
            assert requested_asset_code == asset_code
            self.binding_updates.append(dict(payload))
            self.asset.update(
                {
                    **payload,
                    "maitu_binding_verification_source": "backend_maitu_inventory_readback",
                    "maitu_binding_scope": "assetgraph_script_layout_material_binding_v2",
                    "maitu_binding_verified_at": "2026-07-12T14:00:00Z",
                }
            )
            return dict(self.asset)

    class ResolverSession(FakeBrowserUseCliSession):
        def list_maitu_materials(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": 41000,
                    "name": "礼盒",
                    "type": "image",
                    "url": "https://static.example/gift-box.png",
                }
            ]

        def upload_maitu_material(self, **_kwargs) -> dict[str, Any]:
            raise AssertionError("existing Maitu material should be reused")

    fake_client = ResolverClient("http://assetgraph")
    monkeypatch.setattr(worker_main, "AssetGraphClient", lambda base_url: fake_client)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", lambda: ResolverSession())

    exit_code = worker_main.main(
        [
            "--resolve-maitu-materials",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--resolved-plan-file",
            str(resolved_path),
            "--assets-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert fake_client.binding_updates[0]["maitu_material_id"] == 41000
    resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
    assert resolved["operations"][0]["material_id"] == 41000
    assert resolved["operations"][0]["source_material_url"].endswith("gift-box.png")
    output = capsys.readouterr().out
    assert '"status": "resolved"' in output


@pytest.mark.parametrize(
    "argv",
    [
        [
            "--live-scene-fill",
            "--dry-run",
            "--build-plan-code",
            "MT-BUILD-DRY-RUN-BLOCKED",
            "--target-live-room-id",
            "40173",
        ],
        [
            "--script-layout-draft-execute",
            "--dry-run",
            "--write-result",
            "--script-layout-build-plan-file",
            "must-not-be-read.json",
            "--target-live-room-id",
            "DRY-RUN-ROOM",
        ],
        ["--once", "--dry-run"],
        ["--capture-jd-metrics", "--jd-metric-session-code", "JD-METRIC-MUST-NOT-RUN", "--dry-run"],
        ["--non-destructive-build", "--build-plan-code", "MT-BUILD-MUST-NOT-RUN", "--dry-run"],
        ["--dry-run"],
    ],
)
def test_main_rejects_dry_run_combinations_that_would_create_real_side_effects_before_clients_start(
    monkeypatch,
    argv: list[str],
) -> None:
    started: list[str] = []

    def forbidden_constructor(name: str):
        def construct(*_args, **_kwargs):
            started.append(name)
            raise AssertionError(f"{name} must not start for rejected dry-run combinations")

        return construct

    monkeypatch.setattr(worker_main, "AssetGraphClient", forbidden_constructor("AssetGraphClient"))
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", forbidden_constructor("BrowserUseCliSession"))
    monkeypatch.setattr(worker_main, "LiveSceneFillRunner", forbidden_constructor("LiveSceneFillRunner"))
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", forbidden_constructor("ScriptLayoutDraftRunner"))

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main(argv)

    assert "dry-run" in str(exc_info.value).lower()
    assert started == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--probe-maitu", "--observe-maitu"],
        [
            "--capture-jd-metrics",
            "--jd-metric-session-code",
            "JD-METRIC-CONFLICT",
            "--live-scene-fill",
            "--build-plan-code",
            "MT-BUILD-CONFLICT",
            "--target-live-room-id",
            "40173",
        ],
    ],
)
def test_main_rejects_conflicting_cli_modes_before_clients_or_browser_start(
    monkeypatch,
    argv: list[str],
) -> None:
    started: list[str] = []

    def forbidden_constructor(name: str):
        def construct(*_args, **_kwargs):
            started.append(name)
            raise AssertionError(f"{name} must not start for conflicting CLI modes")

        return construct

    monkeypatch.setattr(worker_main, "AssetGraphClient", forbidden_constructor("AssetGraphClient"))
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", forbidden_constructor("BrowserUseCliSession"))

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main(argv)

    assert "conflicting" in str(exc_info.value).lower()
    assert started == []


@pytest.mark.parametrize(
    ("extra_args", "expected_message"),
    [
        (["--probe-maitu"], "Conflicting CLI modes"),
        (["--observe-maitu"], "Conflicting CLI modes"),
    ],
)
def test_main_rejects_real_draft_execution_without_full_material_resolution(
    monkeypatch,
    extra_args: list[str],
    expected_message: str,
) -> None:
    started: list[str] = []

    def forbidden_constructor(name: str):
        def construct(*_args, **_kwargs):
            started.append(name)
            raise AssertionError(f"{name} must not start before the real draft resolver gate")

        return construct

    monkeypatch.setattr(worker_main, "AssetGraphClient", forbidden_constructor("AssetGraphClient"))
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", forbidden_constructor("BrowserUseCliSession"))
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", forbidden_constructor("ScriptLayoutDraftRunner"))

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main(
            [
                "--script-layout-draft-execute",
                "--script-layout-build-plan-file",
                "untrusted-plan.json",
                "--target-live-room-id",
                "50001",
                *extra_args,
            ]
        )

    assert expected_message in str(exc_info.value)
    assert started == []


@pytest.mark.parametrize("plan_target", [None, "50002"])
def test_main_rejects_unbound_or_mismatched_real_draft_target_before_resolver_side_effects(
    monkeypatch,
    tmp_path: Path,
    plan_target: str | None,
) -> None:
    started: list[str] = []
    plan_path = tmp_path / "target-gate-plan.json"
    payload: dict[str, Any] = {**executable_script_layout_gate(), "operations": []}
    if plan_target is not None:
        payload["target_live_room_id"] = plan_target
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    def forbidden_constructor(name: str):
        def construct(*_args, **_kwargs):
            started.append(name)
            raise AssertionError(f"{name} must not start before the bound target-room gate")

        return construct

    monkeypatch.setattr(worker_main, "AssetGraphClient", forbidden_constructor("AssetGraphClient"))
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", forbidden_constructor("BrowserUseCliSession"))
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", forbidden_constructor("MaituMaterialResolver"))
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", forbidden_constructor("ScriptLayoutDraftRunner"))

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main(
            [
                "--resolve-maitu-materials",
                "--script-layout-draft-execute",
                "--script-layout-build-plan-file",
                str(plan_path),
                "--target-live-room-id",
                "50001",
            ]
        )

    assert "separate phases" in str(exc_info.value).lower()
    assert started == []


def test_main_still_allows_in_memory_draft_dry_run_without_material_resolver(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    started: list[str] = []

    def forbidden_constructor(name: str):
        def construct(*_args, **_kwargs):
            started.append(name)
            raise AssertionError(f"{name} must not start during in-memory dry-run")

        return construct

    monkeypatch.setattr(worker_main, "AssetGraphClient", forbidden_constructor("AssetGraphClient"))
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", forbidden_constructor("BrowserUseCliSession"))
    plan_path = tmp_path / "dry-run-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "operations": [
                    {"operation_type": "preflight_content_build_plan", "status": "ready"},
                    {"operation_type": "save_draft", "status": "manual_review"},
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = worker_main.main(
        [
            "--dry-run",
            "--script-layout-draft-execute",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--target-live-room-id",
            "DRY-RUN-ROOM",
        ]
    )

    assert exit_code == 2
    assert started == []
    assert '"ready_for_go_live": false' in capsys.readouterr().out


def test_main_fail_closes_before_draft_execution_when_material_resolution_is_manual(monkeypatch, capsys, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                **executable_script_layout_gate(),
                "target_live_room_id": "50001",
                "operations": [{"operation_type": "insert_asset_layer", "asset_code": "AG-MISSING"}],
            }
        ),
        encoding="utf-8",
    )
    runner_started = False

    class ManualResolver:
        def __init__(self, **_kwargs) -> None:
            pass

        def resolve_plan(self, operation_plan: dict[str, Any]):
            return worker_main.MaituMaterialResolutionResult(
                status="completed_with_manual_review",
                reused_binding_count=0,
                remote_match_count=0,
                uploaded_count=0,
                manual_required_count=1,
                operation_plan=operation_plan,
                issues=[],
            )

    class MustNotRun:
        def __init__(self, **_kwargs) -> None:
            nonlocal runner_started
            runner_started = True
            raise AssertionError("draft runner must not start with unresolved Maitu materials")

    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", ManualResolver)
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", MustNotRun)

    exit_code = worker_main.main(
        [
            "--resolve-maitu-materials",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--target-live-room-id",
            "50001",
        ]
    )

    assert exit_code == 2
    assert runner_started is False
    assert '"manual_required_count": 1' in capsys.readouterr().out


def test_main_fail_closes_on_nonempty_resolver_issues_even_when_count_is_zero(monkeypatch, capsys, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    resolved_operation = {
        "operation_type": "insert_asset_layer",
        "asset_code": "AG-IMG-1",
        "layer_type": "product_image",
        "maitu_material_id": 41000,
        "source_material_type": "image",
        "source_material_url": "https://static.example/gift.png",
        "material_resolution_status": "matched_existing_maitu_material",
    }
    plan_path.write_text(
        json.dumps(
            {
                **executable_script_layout_gate(),
                "target_live_room_id": "50001",
                "operations": [resolved_operation],
            }
        ),
        encoding="utf-8",
    )
    runner_started = False

    class IssueResolver:
        def __init__(self, **_kwargs) -> None:
            pass

        operation_has_executable_binding = staticmethod(RealMaituMaterialResolver.operation_has_executable_binding)

        def resolve_plan(self, _operation_plan: dict[str, Any]):
            return worker_main.MaituMaterialResolutionResult(
                status="resolved",
                reused_binding_count=0,
                remote_match_count=1,
                uploaded_count=0,
                manual_required_count=0,
                operation_plan={"operations": [resolved_operation]},
                issues=[
                    MaituMaterialResolutionIssue(
                        asset_code="AG-IMG-1",
                        reason="simulated_issue",
                        summary="must fail closed",
                        candidate_material_ids=[],
                    )
                ],
            )

    class MustNotRun:
        def __init__(self, **_kwargs) -> None:
            nonlocal runner_started
            runner_started = True

    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", IssueResolver)
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", MustNotRun)

    exit_code = worker_main.main(
        [
            "--resolve-maitu-materials",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--target-live-room-id",
            "50001",
        ]
    )

    assert exit_code == 2
    assert runner_started is False
    assert '"reason": "simulated_issue"' in capsys.readouterr().out


def test_main_fail_closes_when_resolver_claims_resolved_but_binding_is_incomplete(monkeypatch, capsys, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    source_plan = {
        **executable_script_layout_gate(),
        "target_live_room_id": "50001",
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": "AG-IMG-1", "layer_type": "product_image"}
        ],
    }
    plan_path.write_text(json.dumps(source_plan), encoding="utf-8")
    runner_started = False

    class IncompleteResolver:
        def __init__(self, **_kwargs) -> None:
            pass

        operation_has_executable_binding = staticmethod(RealMaituMaterialResolver.operation_has_executable_binding)

        def resolve_plan(self, _operation_plan: dict[str, Any]):
            incomplete = {
                "operations": [
                    {
                        **source_plan["operations"][0],
                        "maitu_material_id": 41000,
                        "source_material_type": "image",
                        "material_resolution_status": "matched_existing_maitu_material",
                    }
                ]
            }
            return worker_main.MaituMaterialResolutionResult(
                status="resolved",
                reused_binding_count=0,
                remote_match_count=1,
                uploaded_count=0,
                manual_required_count=0,
                operation_plan=incomplete,
                issues=[],
            )

    class MustNotRun:
        def __init__(self, **_kwargs) -> None:
            nonlocal runner_started
            runner_started = True

    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", IncompleteResolver)
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", MustNotRun)

    exit_code = worker_main.main(
        [
            "--resolve-maitu-materials",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--target-live-room-id",
            "50001",
        ]
    )

    assert exit_code == 2
    assert runner_started is False
    assert '"status": "blocked_invalid_material_resolution"' in capsys.readouterr().out


def test_main_passes_resolved_plan_into_draft_execution(monkeypatch, capsys, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    resolved_plan = {
        "build_plan_code": "MT-BUILD-20260712-000001",
        "checkpoint_source_fingerprint": "c" * 64,
        "target_live_room_id": "50002",
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "status": "ready",
                "target_live_room_id": "50002",
            },
            {
                "operation_type": "insert_asset_layer",
                "asset_code": "AG-IMG-1",
                "layer_type": "product_image",
                "maitu_material_id": 41000,
                "material_id": 41000,
                "source_material_type": "image",
                "source_material_url": "https://static.example/gift.png",
                "material_resolution_status": "matched_existing_maitu_material",
            },
        ],
    }
    plan_path.write_text(json.dumps(resolved_plan), encoding="utf-8")
    captured: dict[str, Any] = {}

    class GreenResolver:
        def __init__(self, **_kwargs) -> None:
            pass

        operation_has_executable_binding = staticmethod(RealMaituMaterialResolver.operation_has_executable_binding)

        def resolve_plan(self, _operation_plan: dict[str, Any]):
            return worker_main.MaituMaterialResolutionResult(
                status="resolved",
                reused_binding_count=0,
                remote_match_count=1,
                uploaded_count=0,
                manual_required_count=0,
                operation_plan=resolved_plan,
                issues=[],
            )

    @dataclass
    class GreenRunResult:
        status: str = "completed"
        failure_count: int = 0
        manual_review_required: bool = False
        actions: list[Any] = field(default_factory=list)

    class CapturingRunner:
        def __init__(self, *, session: Any, checkpoint_store: Any = None) -> None:
            captured["session"] = session
            captured["runner_checkpoint_store"] = checkpoint_store

        def run(self, operation_plan: dict[str, Any], *, target_live_room_id: str | None = None) -> GreenRunResult:
            captured["operation_plan"] = operation_plan
            captured["target_live_room_id"] = target_live_room_id
            return GreenRunResult()

    class CapturingCheckpointStore:
        @classmethod
        def start(
            cls,
            *,
            client: Any,
            operation_plan: dict[str, Any],
            target_live_room_id: str,
        ):
            instance = cls()
            captured["checkpoint_plan"] = operation_plan
            captured["checkpoint_target"] = target_live_room_id
            return instance

        def ensure_lease_active(self) -> bool:
            captured["lease_guard_installed"] = True
            return True

        def finalize(self, result: GreenRunResult) -> dict[str, Any]:
            return {"execution_code": "MT-EXEC-20260712-000001", "execution_status": result.status}

    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession)
    monkeypatch.setattr(worker_main, "is_trusted_browser_use_cli_session", lambda _session: True)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", GreenResolver)
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", CapturingRunner)
    monkeypatch.setattr(worker_main, "AssetGraphScriptLayoutCheckpointStore", CapturingCheckpointStore)

    exit_code = worker_main.main(
        [
            "--script-layout-draft-execute",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--target-live-room-id",
            "50002",
        ]
    )

    assert exit_code == 0
    assert captured["operation_plan"] == resolved_plan
    assert captured["operation_plan"]["operations"][0]["operation_type"] == "preflight_content_build_plan"
    assert captured["operation_plan"]["operations"][1]["material_id"] == 41000
    assert captured["target_live_room_id"] == "50002"
    assert captured["checkpoint_plan"] == resolved_plan
    assert captured["runner_checkpoint_store"] is not None
    assert '"status": "completed"' in capsys.readouterr().out


def test_workbench_draft_job_heartbeats_through_resolution_and_execution(monkeypatch, capsys) -> None:
    heartbeat_seen = threading.Event()
    captured: dict[str, Any] = {"heartbeats": [], "completed": [], "failed": []}
    lease_token = "11111111-1111-4111-8111-111111111111"
    plan = {
        **executable_script_layout_gate(),
        "build_plan_code": "MT-BUILD-20260720-000001",
        "checkpoint_source_fingerprint": "a" * 64,
        "target_live_room_id": "50003",
        "operations": [{"operation_type": "preflight_content_build_plan", "status": "ready"}],
    }

    class DraftClient:
        timeout_seconds = 0.1

        def __init__(self, _base_url: str) -> None:
            self.script_layout_worker_token = None
            self.worker_id = None

        @staticmethod
        def claim_next_workbench_draft_execution(payload: dict[str, Any]) -> dict[str, Any]:
            assert payload == {"lease_seconds": 3600}
            return {
                "execution_job_code": "MT-WB-EXEC-20260720-000001",
                "lease_token": lease_token,
                "payload": {"build_plan": {"build_plan_code": plan["build_plan_code"]}},
            }

        def heartbeat_workbench_draft_execution(
            self,
            job_code: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            captured["heartbeats"].append((job_code, payload, threading.current_thread().name))
            if threading.current_thread().name.startswith("workbench-draft-heartbeat-"):
                heartbeat_seen.set()
            return {"status": "running"}

        @staticmethod
        def get_live_room_build_plan_operation_plan(_build_plan_code: str) -> dict[str, Any]:
            return plan

        @staticmethod
        def complete_workbench_draft_execution(job_code: str, payload: dict[str, Any]) -> dict[str, Any]:
            captured["completed"].append((job_code, payload))
            return {"execution_job_code": job_code, "status": "succeeded"}

        @staticmethod
        def fail_workbench_draft_execution(job_code: str, payload: dict[str, Any]) -> dict[str, Any]:
            captured["failed"].append((job_code, payload))
            return {"execution_job_code": job_code, "status": "failed"}

    class Session(FakeBrowserUseCliSession):
        pass

    class Resolver:
        def __init__(self, *, session: Session, **_kwargs: Any) -> None:
            self.session = session

        def resolve_plan(self, source_plan: dict[str, Any]) -> Any:
            assert heartbeat_seen.wait(timeout=0.2), "periodic heartbeat did not cover material resolution"
            assert self.session.execution_guard() is True
            return worker_main.MaituMaterialResolutionResult(
                status="resolved",
                reused_binding_count=1,
                remote_match_count=0,
                uploaded_count=0,
                manual_required_count=0,
                operation_plan=source_plan,
                issues=[],
            )

    class Checkpoint:
        @classmethod
        def start(cls, **_kwargs: Any) -> "Checkpoint":
            return cls()

        @staticmethod
        def ensure_lease_active() -> bool:
            return True

        @staticmethod
        def finalize(result: Any) -> dict[str, Any]:
            return {"status": result.status}

    @dataclass
    class Result:
        status: str = "completed_with_manual_review"
        summary: str = "draft built and held for manual review"
        failure_count: int = 0
        manual_review_required: bool = True
        actions: list[Any] = field(default_factory=list)

    class Runner:
        def __init__(self, *, session: Session, **_kwargs: Any) -> None:
            self.session = session

        def run(self, _plan: dict[str, Any], *, target_live_room_id: str) -> Result:
            assert target_live_room_id == "50003"
            assert self.session.execution_guard() is True
            return Result()

    monkeypatch.setenv("ASSETGRAPH_WORKBENCH_DRAFT_HEARTBEAT_INTERVAL_SECONDS", "0.001")
    monkeypatch.setattr(worker_main, "AssetGraphClient", DraftClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", Session)
    monkeypatch.setattr(worker_main, "is_trusted_browser_use_cli_session", lambda _session: True)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", Resolver)
    monkeypatch.setattr(worker_main, "AssetGraphScriptLayoutCheckpointStore", Checkpoint)
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", Runner)

    assert worker_main.main(["--run-workbench-draft-job"]) == 0

    assert len(captured["heartbeats"]) >= 3  # initial, periodic, final validation
    assert captured["completed"]
    assert captured["completed"][0][1]["result"]["status"] == "completed_with_manual_review"
    assert captured["failed"] == []
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"


def test_workbench_draft_heartbeat_failure_fences_complete_and_fail_409_preserves_error(monkeypatch) -> None:
    heartbeat_failed = threading.Event()
    captured: dict[str, Any] = {"completed": 0, "failed": 0}
    lease_token = "22222222-2222-4222-8222-222222222222"
    plan = {
        **executable_script_layout_gate(),
        "build_plan_code": "MT-BUILD-20260720-000002",
        "target_live_room_id": "50004",
        "operations": [{"operation_type": "preflight_content_build_plan", "status": "ready"}],
    }

    class DraftClient:
        timeout_seconds = 0.1

        def __init__(self, _base_url: str) -> None:
            self.script_layout_worker_token = None
            self.worker_id = None

        @staticmethod
        def claim_next_workbench_draft_execution(_payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "execution_job_code": "MT-WB-EXEC-20260720-000002",
                "lease_token": lease_token,
                "payload": {"build_plan": {"build_plan_code": plan["build_plan_code"]}},
            }

        @staticmethod
        def get_live_room_build_plan_operation_plan(_build_plan_code: str) -> dict[str, Any]:
            return plan

        @staticmethod
        def heartbeat_workbench_draft_execution(_job_code: str, _payload: dict[str, Any]) -> dict[str, Any]:
            if threading.current_thread().name.startswith("workbench-draft-heartbeat-"):
                heartbeat_failed.set()
                raise AssetGraphClientError("HTTP 409 heartbeat: lease lost")
            return {"status": "running"}

        @staticmethod
        def complete_workbench_draft_execution(_job_code: str, _payload: dict[str, Any]) -> dict[str, Any]:
            captured["completed"] += 1
            return {}

        @staticmethod
        def fail_workbench_draft_execution(_job_code: str, _payload: dict[str, Any]) -> dict[str, Any]:
            captured["failed"] += 1
            raise AssetGraphClientError("HTTP 409 fail: lease no longer active")

    class Resolver:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        @staticmethod
        def resolve_plan(source_plan: dict[str, Any]) -> Any:
            assert heartbeat_failed.wait(timeout=0.2)
            time.sleep(0.01)
            return worker_main.MaituMaterialResolutionResult(
                status="resolved",
                reused_binding_count=1,
                remote_match_count=0,
                uploaded_count=0,
                manual_required_count=0,
                operation_plan=source_plan,
                issues=[],
            )

    monkeypatch.setenv("ASSETGRAPH_WORKBENCH_DRAFT_HEARTBEAT_INTERVAL_SECONDS", "0.001")
    monkeypatch.setattr(worker_main, "AssetGraphClient", DraftClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession)
    monkeypatch.setattr(worker_main, "is_trusted_browser_use_cli_session", lambda _session: True)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", Resolver)

    with pytest.raises(WorkbenchDraftLeaseError, match="heartbeat failed") as error:
        worker_main.main(["--run-workbench-draft-job"])

    assert "fail: lease no longer active" not in str(error.value)
    assert captured == {"completed": 0, "failed": 1}
