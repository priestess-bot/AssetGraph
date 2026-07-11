from __future__ import annotations

from typing import Any

import pytest

from browser_use_worker.maitu_executor import MaituBrowserExecutionError, MaituBrowserUseExecutor


class FakeAssetClient:
    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        return {"asset_code": asset_code}


_DEFAULT_EVIDENCE = object()


class EvidenceSession:
    def __init__(self, *, evidence: Any = _DEFAULT_EVIDENCE) -> None:
        self.calls: list[str] = []
        self.evidence = (
            {"verified": True, "source": "readback"}
            if evidence is _DEFAULT_EVIDENCE
            else evidence
        )

    def ensure_ready(self, *, maitu_project_code: str | None, scene_name: str | None) -> None:
        self.calls.append("ensure_ready")

    def recover_login(self) -> dict[str, Any]:
        self.calls.append("recover_login")
        return self.evidence

    def upload_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("upload_asset")
        return self.evidence

    def replace_layer_asset(self, operation: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("replace_layer_asset")
        return self.evidence

    def save_project(self) -> dict[str, Any]:
        self.calls.append("save_project")
        return self.evidence

    def capture_screenshot(self, *, label: str) -> str | None:
        self.calls.append("capture_screenshot")
        return "AG-SCREENSHOT-1"

    def execute_generic_operation(
        self,
        operation: dict[str, Any],
        asset: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raise AssertionError("generic mutation must remain unreachable")


class FakeCheckpointController:
    def __init__(self, decisions: list[str] | None = None) -> None:
        self.retry_task_code = "MT-RETRY-20260711-000001"
        self.decisions = list(decisions or ["execute"])
        self.calls: list[tuple[str, str]] = []
        self.fail_begin = False
        self.fail_complete = False

    def begin(self, operation: dict[str, Any]) -> str:
        self.calls.append(("begin", operation["operation_key"]))
        if self.fail_begin:
            raise MaituBrowserExecutionError("checkpoint begin uncertain", retryable=True)
        return self.decisions.pop(0)

    def complete(
        self,
        operation: dict[str, Any],
        *,
        result_summary: str,
        evidence: dict[str, Any],
    ) -> None:
        self.calls.append(("complete", operation["operation_key"]))
        if self.fail_complete:
            raise MaituBrowserExecutionError("checkpoint complete uncertain", retryable=True)


def operation(
    operation_type: str = "retry_replace_layer_asset",
    *,
    key: str = "replace-layer-01",
    fingerprint: str = "a" * 64,
    status: str = "ready",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation_type": operation_type,
        "operation_key": key,
        "operation_fingerprint": fingerprint,
        "status": status,
    }
    if operation_type not in {"save_project", "retry_save_project"}:
        payload["asset_code"] = "AG-IMG-1"
    return payload


def plan(*operations: dict[str, Any]) -> dict[str, Any]:
    return {
        "retry_task_code": "MT-RETRY-20260711-000001",
        "maitu_project_code": "MT-PROJ-1",
        "scene_name": "scene-1",
        "operations": list(operations),
    }


def executor_with_checkpoint(
    session: EvidenceSession,
    controller: FakeCheckpointController,
) -> MaituBrowserUseExecutor:
    executor = MaituBrowserUseExecutor(asset_client=FakeAssetClient(), session=session)
    executor.set_checkpoint_controller(controller)
    return executor


@pytest.mark.parametrize(
    "bad_operation",
    [
        {"operation_type": "retry_replace_layer_asset", "status": "ready", "operation_fingerprint": "a" * 64},
        operation(status="blocked"),
        operation(status="drift"),
        operation(fingerprint="A" * 64),
        operation(fingerprint="a" * 63),
        operation(key=" save "),
    ],
)
def test_retry_plan_rejects_missing_blocked_or_noncanonical_identity_before_session_call(
    bad_operation: dict[str, Any],
) -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController()
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(bad_operation))

    assert result.status == "manual_required"
    assert session.calls == []
    assert controller.calls == []


def test_retry_plan_rejects_duplicate_operation_keys_before_session_call() -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController()
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation(), operation(operation_type="save_project")))

    assert result.status == "manual_required"
    assert session.calls == []
    assert controller.calls == []


def test_checkpoint_skip_causes_zero_session_mutation_and_no_complete() -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController(["skip"])
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation()))

    assert result.status == "succeeded"
    assert session.calls == []
    assert controller.calls == [("begin", "replace-layer-01")]


def test_checkpoint_reconcile_returns_manual_required_with_zero_session_mutation() -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController(["reconcile"])
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation()))

    assert result.status == "manual_required"
    assert result.retry_instruction is not None
    assert (
        "/api/maitu/retry-tasks/MT-RETRY-20260711-000001/operations/replace-layer-01/reconcile"
        in result.retry_instruction
    )
    assert "confirmed_not_applied" in result.retry_instruction
    assert session.calls == []
    assert controller.calls == [("begin", "replace-layer-01")]


def test_uncertain_checkpoint_begin_causes_zero_session_mutation() -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController()
    controller.fail_begin = True
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation()))

    assert result.status == "released"
    assert session.calls == []
    assert controller.calls == [("begin", "replace-layer-01")]


def test_uncertain_checkpoint_complete_stops_before_downstream_operation() -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController(["execute", "execute"])
    controller.fail_complete = True
    executor = executor_with_checkpoint(session, controller)
    save = operation(operation_type="save_project", key="save-project-01", fingerprint="b" * 64)

    result = executor.execute_operation_plan(plan(operation(), save))

    assert result.status == "released"
    assert session.calls == ["ensure_ready", "replace_layer_asset"]
    assert controller.calls == [
        ("begin", "replace-layer-01"),
        ("complete", "replace-layer-01"),
    ]


@pytest.mark.parametrize("evidence", [None, False, {}, {"verified": False}])
def test_mutation_requires_verified_evidence_before_checkpoint_complete(evidence: Any) -> None:
    session = EvidenceSession(evidence=evidence)
    controller = FakeCheckpointController()
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation()))

    assert result.status == "manual_required"
    assert session.calls == ["ensure_ready", "replace_layer_asset"]
    assert controller.calls == [("begin", "replace-layer-01")]


def test_verified_evidence_rejects_nested_claim_token_before_checkpoint_complete() -> None:
    session = EvidenceSession(
        evidence={"verified": True, "readback": {"claim_token": "must-not-leak"}},
    )
    controller = FakeCheckpointController()
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation()))

    assert result.status == "manual_required"
    assert "forbidden secret" in (result.error_message or "")
    assert controller.calls == [("begin", "replace-layer-01")]


@pytest.mark.parametrize(
    "evidence",
    [
        {"verified": True, "Authorization": "Bearer secret"},
        {"verified": True, "readback": {"api-token": "secret"}},
        {"verified": True, "steps": [{"verified": True, "password": "secret"}]},
        {"verified": True, "cookie": "session=secret"},
    ],
)
def test_verified_evidence_rejects_normalized_secret_keys_before_checkpoint_complete(
    evidence: dict[str, Any],
) -> None:
    session = EvidenceSession(evidence=evidence)
    controller = FakeCheckpointController()
    executor = executor_with_checkpoint(session, controller)

    result = executor.execute_operation_plan(plan(operation()))

    assert result.status == "manual_required"
    assert "forbidden secret" in (result.error_message or "")
    assert controller.calls == [("begin", "replace-layer-01")]


@pytest.mark.parametrize("operation_type", ["save_project", "retry_save_project"])
def test_save_is_explicit_operation_and_runs_exactly_once(operation_type: str) -> None:
    session = EvidenceSession()
    controller = FakeCheckpointController()
    executor = executor_with_checkpoint(session, controller)
    save = operation(operation_type=operation_type, key="save-project-01", fingerprint="b" * 64)

    result = executor.execute_operation_plan(plan(save))

    assert result.status == "succeeded"
    assert session.calls.count("save_project") == 1
    assert controller.calls == [
        ("begin", "save-project-01"),
        ("complete", "save-project-01"),
    ]


def test_explicit_save_never_resolves_unneeded_asset_metadata() -> None:
    class AssetLookupMustNotRun:
        def get_asset(self, asset_code: str) -> dict[str, Any] | None:
            raise AssertionError(f"save operation must not resolve asset {asset_code}")

    session = EvidenceSession()
    controller = FakeCheckpointController()
    executor = MaituBrowserUseExecutor(asset_client=AssetLookupMustNotRun(), session=session)
    executor.set_checkpoint_controller(controller)
    save = operation(operation_type="retry_save_project", key="save-project-01", fingerprint="b" * 64)
    save["asset_code"] = "AG-STALE-ASSET"

    result = executor.execute_operation_plan(plan(save))

    assert result.status == "succeeded"
    assert session.calls.count("save_project") == 1
