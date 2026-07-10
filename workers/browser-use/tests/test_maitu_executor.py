from __future__ import annotations

from typing import Any

from browser_use_worker.maitu_executor import MaituBrowserExecutionError, MaituBrowserUseExecutor


class FakeAssetClient:
    def __init__(self, assets: dict[str, dict[str, Any]] | None = None) -> None:
        self.assets = assets or {}
        self.requested_codes: list[str] = []

    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        self.requested_codes.append(asset_code)
        return self.assets.get(asset_code)


class FakeMaituSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail_on_replace: MaituBrowserExecutionError | None = None

    def ensure_ready(self, *, maitu_project_code: str | None, scene_name: str | None) -> None:
        self.calls.append(("ensure_ready", {"maitu_project_code": maitu_project_code, "scene_name": scene_name}))

    def recover_login(self) -> None:
        self.calls.append(("recover_login", None))

    def upload_asset(self, asset: dict[str, Any]) -> None:
        self.calls.append(("upload_asset", asset["asset_code"]))

    def replace_layer_asset(self, operation: dict[str, Any], asset: dict[str, Any]) -> None:
        if self.fail_on_replace is not None:
            raise self.fail_on_replace
        self.calls.append(("replace_layer_asset", {"slot_code": operation.get("slot_code"), "asset_code": asset["asset_code"]}))

    def save_project(self) -> None:
        self.calls.append(("save_project", None))

    def capture_screenshot(self, *, label: str) -> str | None:
        self.calls.append(("capture_screenshot", label))
        return "AG-IMG-SCREENSHOT"

    def execute_generic_operation(self, operation: dict[str, Any], asset: dict[str, Any] | None) -> None:
        self.calls.append(("execute_generic_operation", {"operation_type": operation.get("operation_type"), "asset_code": asset.get("asset_code") if asset else None}))


def asset(asset_code: str = "AG-VID-20260709-000001") -> dict[str, Any]:
    return {
        "asset_code": asset_code,
        "display_code": "MT-VID-0024",
        "local_file_code": "MT-VID-0024",
        "title": "品酒大师 PRO 商品讲解视频",
        "local_relative_path": "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
    }


def operation_plan(operation_type: str, *, asset_code: str | None = "AG-VID-20260709-000001") -> dict[str, Any]:
    operation = {
        "operation_type": operation_type,
        "slot_code": "MT-SLOT-20260709-000001",
        "slot_name": "商品讲解视频",
        "scene_name": "京东空白直播间",
        "layer_name": "layer_8",
        "replacement_policy": "keep_layout",
        "instruction": "只替换素材，不改变布局",
    }
    if asset_code is not None:
        operation["asset_code"] = asset_code
    return {
        "retry_task_code": "MT-RETRY-20260709-000001",
        "maitu_project_code": "MT-PROJ-20260709-000001",
        "scene_name": "京东空白直播间",
        "operations": [operation],
    }


def test_maitu_executor_replaces_layer_asset_and_saves_project() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(
        asset_client=FakeAssetClient({"AG-VID-20260709-000001": asset()}),
        session=session,
    )

    result = executor.execute_operation_plan(operation_plan("retry_replace_layer_asset"))

    assert result.status == "succeeded"
    assert result.screenshot_asset_code == "AG-IMG-SCREENSHOT"
    assert session.calls == [
        ("ensure_ready", {"maitu_project_code": "MT-PROJ-20260709-000001", "scene_name": "京东空白直播间"}),
        ("replace_layer_asset", {"slot_code": "MT-SLOT-20260709-000001", "asset_code": "AG-VID-20260709-000001"}),
        ("save_project", None),
        ("capture_screenshot", "MT-RETRY-20260709-000001"),
    ]


def test_maitu_executor_executes_replacement_plan_operation_type() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(
        asset_client=FakeAssetClient({"AG-VID-20260709-000001": asset()}),
        session=session,
    )
    plan = operation_plan("replace_layer_asset")
    plan["plan_code"] = "MT-PLAN-20260709-000001"
    plan.pop("retry_task_code")

    result = executor.execute_operation_plan(plan)

    assert result.status == "succeeded"
    assert ("replace_layer_asset", {"slot_code": "MT-SLOT-20260709-000001", "asset_code": "AG-VID-20260709-000001"}) in session.calls
    assert ("capture_screenshot", "MT-PLAN-20260709-000001") in session.calls


def test_maitu_executor_uploads_asset_before_replace() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(
        asset_client=FakeAssetClient({"AG-VID-20260709-000001": asset()}),
        session=session,
    )

    result = executor.execute_operation_plan(operation_plan("retry_asset_upload_and_replace"))

    assert result.status == "succeeded"
    call_names = [name for name, _ in session.calls]
    assert call_names == ["ensure_ready", "upload_asset", "replace_layer_asset", "save_project", "capture_screenshot"]


def test_maitu_executor_recover_login_then_retries_operation() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(
        asset_client=FakeAssetClient({"AG-VID-20260709-000001": asset()}),
        session=session,
    )

    result = executor.execute_operation_plan(operation_plan("recover_login_then_retry"))

    assert result.status == "succeeded"
    call_names = [name for name, _ in session.calls]
    assert call_names == ["ensure_ready", "recover_login", "replace_layer_asset", "save_project", "capture_screenshot"]


def test_maitu_executor_rejects_generic_operation_without_explicit_safe_handler() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(
        asset_client=FakeAssetClient({"AG-VID-20260709-000001": asset()}),
        session=session,
    )

    result = executor.execute_operation_plan(operation_plan("retry_browser_use_operation"))

    assert result.status == "manual_required"
    assert "unsupported operation type" in (result.error_message or "").lower()
    assert not any(name == "execute_generic_operation" for name, _ in session.calls)


def test_maitu_executor_missing_asset_requires_manual_intervention() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(asset_client=FakeAssetClient({}), session=session)

    result = executor.execute_operation_plan(operation_plan("retry_replace_layer_asset"))

    assert result.status == "manual_required"
    assert "AssetGraph asset not found" in (result.error_message or "")
    assert [name for name, _ in session.calls] == ["ensure_ready"]


def test_maitu_executor_manual_operation_requires_manual_intervention() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(asset_client=FakeAssetClient({}), session=session)

    result = executor.execute_operation_plan(operation_plan("manual_retry_required", asset_code=None))

    assert result.status == "manual_required"
    assert result.retry_instruction == "只替换素材，不改变布局"


def test_maitu_executor_releases_recoverable_browser_failure() -> None:
    session = FakeMaituSession()
    session.fail_on_replace = MaituBrowserExecutionError("temporary network error", retryable=True)
    executor = MaituBrowserUseExecutor(
        asset_client=FakeAssetClient({"AG-VID-20260709-000001": asset()}),
        session=session,
    )

    result = executor.execute_operation_plan(operation_plan("retry_replace_layer_asset"))

    assert result.status == "released"
    assert "temporary network error" in (result.error_message or "")


def test_maitu_executor_empty_plan_requires_manual_intervention() -> None:
    session = FakeMaituSession()
    executor = MaituBrowserUseExecutor(asset_client=FakeAssetClient({}), session=session)

    result = executor.execute_operation_plan({"retry_task_code": "MT-RETRY-EMPTY", "operations": []})

    assert result.status == "manual_required"
    assert "empty" in (result.error_message or "")
    assert session.calls == []
