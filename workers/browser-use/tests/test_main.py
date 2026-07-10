from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import browser_use_worker.__main__ as worker_main
from browser_use_worker.jd_metrics import JdLiveDashboardState
from browser_use_worker.maitu_material_resolver import (
    MaituMaterialResolutionIssue,
    MaituMaterialResolver as RealMaituMaterialResolver,
)


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


def test_main_resolves_maitu_materials_and_writes_resolved_plan(monkeypatch, capsys, tmp_path: Path) -> None:
    asset_code = "AG-IMG-20260710-000099"
    plan_path = tmp_path / "plan.json"
    resolved_path = tmp_path / "resolved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
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
            self.asset.update(payload)
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


@pytest.mark.parametrize("extra_args", [[], ["--probe-maitu"], ["--observe-maitu"]])
def test_main_rejects_real_draft_execution_without_full_material_resolution(
    monkeypatch,
    extra_args: list[str],
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

    assert "requires --resolve-maitu-materials" in str(exc_info.value)
    assert started == []


def test_main_still_allows_in_memory_draft_dry_run_without_material_resolver(capsys, tmp_path: Path) -> None:
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

    assert exit_code == 0
    assert '"ready_for_go_live": false' in capsys.readouterr().out


def test_main_fail_closes_before_draft_execution_when_material_resolution_is_manual(monkeypatch, capsys, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"operations": [{"operation_type": "insert_asset_layer", "asset_code": "AG-MISSING"}]}), encoding="utf-8")
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
            "--script-layout-draft-execute",
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
    plan_path.write_text(json.dumps({"operations": [resolved_operation]}), encoding="utf-8")
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
            "--script-layout-draft-execute",
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
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": "AG-IMG-1", "layer_type": "product_image"}
        ]
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
            "--script-layout-draft-execute",
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
    source_plan = {"operations": [{"operation_type": "insert_asset_layer", "asset_code": "AG-IMG-1"}]}
    resolved_plan = {
        "operations": [
            {
                "operation_type": "insert_asset_layer",
                "asset_code": "AG-IMG-1",
                "layer_type": "product_image",
                "maitu_material_id": 41000,
                "material_id": 41000,
                "source_material_type": "image",
                "source_material_url": "https://static.example/gift.png",
                "material_resolution_status": "matched_existing_maitu_material",
            }
        ]
    }
    plan_path.write_text(json.dumps(source_plan), encoding="utf-8")
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

    class CapturingRunner:
        def __init__(self, *, session: Any) -> None:
            captured["session"] = session

        def run(self, operation_plan: dict[str, Any], *, target_live_room_id: str | None = None) -> GreenRunResult:
            captured["operation_plan"] = operation_plan
            captured["target_live_room_id"] = target_live_room_id
            return GreenRunResult()

    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession)
    monkeypatch.setattr(worker_main, "MaituMaterialResolver", GreenResolver)
    monkeypatch.setattr(worker_main, "ScriptLayoutDraftRunner", CapturingRunner)

    exit_code = worker_main.main(
        [
            "--resolve-maitu-materials",
            "--script-layout-draft-execute",
            "--script-layout-build-plan-file",
            str(plan_path),
            "--target-live-room-id",
            "50002",
        ]
    )

    assert exit_code == 0
    assert captured["operation_plan"] is resolved_plan
    assert captured["operation_plan"]["operations"][0]["material_id"] == 41000
    assert captured["target_live_room_id"] == "50002"
    assert '"status": "completed"' in capsys.readouterr().out
