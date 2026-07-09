from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .maitu_executor import MaituBrowserExecutionError


class AssetMetadataClient(Protocol):
    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        """Return AssetGraph asset metadata by asset_code."""


class MaituProbeSession(Protocol):
    def probe_current_page(self, *, open_if_needed: bool = True) -> Any:
        """Return a read-only Maitu page probe."""


@dataclass(slots=True)
class PreflightCheck:
    name: str
    status: str
    summary: str
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class PreflightResult:
    status: str
    ready_to_execute: bool
    summary: str
    plan_code: str | None
    operation_count: int
    checks: list[PreflightCheck]
    failure_count: int
    warning_count: int
    skipped_count: int


class ReplacementPlanPreflight:
    """Read-only safety checks before mutating Maitu with a replacement plan.

    Preflight deliberately validates only local prerequisites: operation-plan shape,
    Browser-use-friendly asset identifiers, local asset file availability, and the
    current Maitu browser shell/login state.  It never uploads files, replaces
    layers, or saves the Maitu project.
    """

    SUPPORTED_OPERATION_TYPES = {
        "replace_layer_asset",
        "retry_replace_layer_asset",
        "retry_asset_upload_and_replace",
        "retry_save_project",
        "recover_login_then_retry",
        "retry_browser_use_operation",
    }
    ASSET_OPERATION_TYPES = {
        "replace_layer_asset",
        "retry_replace_layer_asset",
        "retry_asset_upload_and_replace",
    }
    BLOCKING_OPERATION_TYPES = {"manual_retry_required", "resolve_missing_slot_asset"}
    REQUIRED_BROWSER_USE_FIELDS = (
        "asset_display_code",
        "asset_local_file_code",
        "asset_original_filename",
        "asset_browser_use_hint",
    )

    def __init__(
        self,
        *,
        asset_client: AssetMetadataClient,
        assets_root: str | Path,
        session: MaituProbeSession | None = None,
        probe_browser: bool = True,
    ) -> None:
        self.asset_client = asset_client
        self.assets_root = Path(assets_root)
        self.session = session
        self.probe_browser = probe_browser

    def run(self, operation_plan: dict[str, Any]) -> PreflightResult:
        checks: list[PreflightCheck] = []
        operations = operation_plan.get("operations") or []
        plan_code = operation_plan.get("plan_code") or operation_plan.get("retry_task_code")

        if not isinstance(operations, list) or not operations:
            checks.append(
                PreflightCheck(
                    name="operation_plan.operations",
                    status="fail",
                    summary="Operation plan has no executable operations.",
                    details={"plan_code": plan_code, "raw_type": type(operations).__name__},
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    name="operation_plan.operations",
                    status="pass",
                    summary=f"Operation plan contains {len(operations)} operation(s).",
                    details={"plan_code": plan_code, "operation_count": len(operations)},
                )
            )
            self._check_target_context(operation_plan, checks)
            for index, operation in enumerate(operations):
                if isinstance(operation, dict):
                    self._check_operation(index, operation, checks)
                else:
                    checks.append(
                        PreflightCheck(
                            name=f"operation[{index}]",
                            status="fail",
                            summary="Operation entry is not an object.",
                            details={"raw_type": type(operation).__name__},
                        )
                    )

        self._check_browser_probe(operation_plan, checks)
        return self._finalize(plan_code=plan_code, operation_count=len(operations) if isinstance(operations, list) else 0, checks=checks)

    def _check_target_context(self, operation_plan: dict[str, Any], checks: list[PreflightCheck]) -> None:
        project_code = operation_plan.get("maitu_project_code")
        scene_name = operation_plan.get("scene_name")
        missing = [name for name, value in (("maitu_project_code", project_code), ("scene_name", scene_name)) if not value]
        if missing:
            checks.append(
                PreflightCheck(
                    name="maitu_target_context",
                    status="warning",
                    summary="Operation plan is missing target context needed for unattended navigation.",
                    details={"missing_fields": missing, "maitu_project_code": project_code, "scene_name": scene_name},
                )
            )
            return
        checks.append(
            PreflightCheck(
                name="maitu_target_context",
                status="pass",
                summary="Operation plan includes Maitu project and scene context.",
                details={"maitu_project_code": project_code, "scene_name": scene_name},
            )
        )

    def _check_operation(self, index: int, operation: dict[str, Any], checks: list[PreflightCheck]) -> None:
        operation_type = str(operation.get("operation_type") or "")
        operation_name = f"operation[{index}]"
        if not operation_type:
            checks.append(
                PreflightCheck(
                    name=f"{operation_name}.operation_type",
                    status="fail",
                    summary="Operation is missing operation_type.",
                    details={"slot_code": operation.get("slot_code")},
                )
            )
            return
        if operation_type in self.BLOCKING_OPERATION_TYPES:
            checks.append(
                PreflightCheck(
                    name=f"{operation_name}.operation_type",
                    status="fail",
                    summary=f"Operation type {operation_type} requires manual resolution before browser-use execution.",
                    details={"operation_type": operation_type, "instruction": operation.get("instruction")},
                )
            )
            return
        if operation_type not in self.SUPPORTED_OPERATION_TYPES:
            checks.append(
                PreflightCheck(
                    name=f"{operation_name}.operation_type",
                    status="fail",
                    summary=f"Operation type {operation_type} is not supported by the current Browser-use worker.",
                    details={"operation_type": operation_type},
                )
            )
            return
        checks.append(
            PreflightCheck(
                name=f"{operation_name}.operation_type",
                status="pass",
                summary=f"Operation type {operation_type} is supported.",
                details={"operation_type": operation_type, "slot_code": operation.get("slot_code")},
            )
        )

        if operation_type in self.ASSET_OPERATION_TYPES:
            self._check_operation_asset(index, operation, checks)

    def _check_operation_asset(self, index: int, operation: dict[str, Any], checks: list[PreflightCheck]) -> None:
        operation_name = f"operation[{index}]"
        asset_code = operation.get("asset_code")
        if not asset_code:
            checks.append(
                PreflightCheck(
                    name=f"{operation_name}.asset_code",
                    status="fail",
                    summary="Asset replacement operation is missing asset_code.",
                    details={"slot_code": operation.get("slot_code")},
                )
            )
            return

        try:
            asset = self.asset_client.get_asset(str(asset_code))
        except Exception as exc:  # pragma: no cover - runtime boundary
            checks.append(
                PreflightCheck(
                    name=f"{operation_name}.asset_lookup",
                    status="fail",
                    summary=f"AssetGraph lookup failed for {asset_code}: {exc}",
                    details={"asset_code": asset_code},
                )
            )
            return

        if asset is None:
            checks.append(
                PreflightCheck(
                    name=f"{operation_name}.asset_lookup",
                    status="fail",
                    summary=f"AssetGraph asset not found: {asset_code}.",
                    details={"asset_code": asset_code},
                )
            )
            return

        checks.append(
            PreflightCheck(
                name=f"{operation_name}.asset_lookup",
                status="pass",
                summary=f"AssetGraph returned metadata for {asset_code}.",
                details={
                    "asset_code": asset_code,
                    "display_code": asset.get("display_code"),
                    "local_file_code": asset.get("local_file_code"),
                    "title": asset.get("title"),
                },
            )
        )
        self._check_browser_use_asset_fields(index, operation, checks)
        self._check_local_asset_file(index, operation, asset, checks)

    def _check_browser_use_asset_fields(self, index: int, operation: dict[str, Any], checks: list[PreflightCheck]) -> None:
        missing = [field for field in self.REQUIRED_BROWSER_USE_FIELDS if not operation.get(field)]
        if missing:
            checks.append(
                PreflightCheck(
                    name=f"operation[{index}].browser_use_asset_fields",
                    status="fail",
                    summary="Operation is missing Browser-use-friendly asset fields.",
                    details={"missing_fields": missing, "asset_code": operation.get("asset_code")},
                )
            )
            return
        checks.append(
            PreflightCheck(
                name=f"operation[{index}].browser_use_asset_fields",
                status="pass",
                summary="Operation includes Browser-use-friendly asset identifiers and hint text.",
                details={
                    "asset_display_code": operation.get("asset_display_code"),
                    "asset_local_file_code": operation.get("asset_local_file_code"),
                    "asset_original_filename": operation.get("asset_original_filename"),
                    "asset_browser_use_hint": operation.get("asset_browser_use_hint"),
                },
            )
        )

    def _check_local_asset_file(
        self,
        index: int,
        operation: dict[str, Any],
        asset: dict[str, Any],
        checks: list[PreflightCheck],
    ) -> None:
        relative_path = operation.get("asset_local_relative_path") or asset.get("local_relative_path")
        if not relative_path:
            checks.append(
                PreflightCheck(
                    name=f"operation[{index}].local_asset_file",
                    status="fail",
                    summary="Asset metadata does not include a local relative file path.",
                    details={"asset_code": operation.get("asset_code")},
                )
            )
            return

        local_path = self._safe_asset_path(str(relative_path))
        if local_path is None:
            checks.append(
                PreflightCheck(
                    name=f"operation[{index}].local_asset_file",
                    status="fail",
                    summary="Asset relative path is unsafe or absolute.",
                    details={"asset_code": operation.get("asset_code"), "relative_path": relative_path},
                )
            )
            return

        if not local_path.is_file():
            checks.append(
                PreflightCheck(
                    name=f"operation[{index}].local_asset_file",
                    status="fail",
                    summary="Local asset file is missing.",
                    details={
                        "asset_code": operation.get("asset_code"),
                        "relative_path": relative_path,
                        "expected_path": str(local_path),
                    },
                )
            )
            return

        actual_size = local_path.stat().st_size
        expected_size = asset.get("file_size")
        if expected_size and int(expected_size) != actual_size:
            checks.append(
                PreflightCheck(
                    name=f"operation[{index}].local_asset_file_size",
                    status="warning",
                    summary="Local asset file exists but size differs from AssetGraph metadata.",
                    details={
                        "asset_code": operation.get("asset_code"),
                        "path": str(local_path),
                        "expected_size": expected_size,
                        "actual_size": actual_size,
                    },
                )
            )
        checks.append(
            PreflightCheck(
                name=f"operation[{index}].local_asset_file",
                status="pass",
                summary="Local asset file exists and can be uploaded/selected by browser automation.",
                details={
                    "asset_code": operation.get("asset_code"),
                    "relative_path": relative_path,
                    "path": str(local_path),
                    "size": actual_size,
                },
            )
        )

    def _check_browser_probe(self, operation_plan: dict[str, Any], checks: list[PreflightCheck]) -> None:
        if not self.probe_browser:
            checks.append(
                PreflightCheck(
                    name="maitu_browser_probe",
                    status="skipped",
                    summary="Browser probe was skipped by configuration.",
                )
            )
            return
        if self.session is None:
            checks.append(
                PreflightCheck(
                    name="maitu_browser_probe",
                    status="skipped",
                    summary="No Browser-use probe session was provided.",
                )
            )
            return

        try:
            probe = self.session.probe_current_page(open_if_needed=True)
        except MaituBrowserExecutionError as exc:
            checks.append(
                PreflightCheck(
                    name="maitu_browser_probe",
                    status="fail",
                    summary=f"Browser-use Maitu probe failed: {exc}",
                    details={"retryable": exc.retryable, "retry_instruction": exc.retry_instruction},
                )
            )
            return
        except Exception as exc:  # pragma: no cover - runtime boundary
            checks.append(
                PreflightCheck(
                    name="maitu_browser_probe",
                    status="fail",
                    summary=f"Browser-use Maitu probe failed unexpectedly: {exc}",
                )
            )
            return

        title = str(getattr(probe, "title", ""))
        url = str(getattr(probe, "url", ""))
        text = str(getattr(probe, "text", ""))
        logged_in = bool(getattr(probe, "logged_in", False))
        login_required = bool(getattr(probe, "login_required", False))
        opened_home = bool(getattr(probe, "opened_home", False))
        probe_details = {
            "title": title,
            "url": url,
            "logged_in": logged_in,
            "login_required": login_required,
            "opened_home": opened_home,
        }

        if login_required:
            probe_details["retry_instruction"] = "请先在 browser-use 打开的可见 Chrome 窗口人工登录麦兔，再重新运行 --preflight。"
            checks.append(
                PreflightCheck(
                    name="maitu_browser_probe",
                    status="fail",
                    summary="Maitu login page is visible; manual login is required before execution.",
                    details=probe_details,
                )
            )
            return
        if not logged_in:
            probe_details["retry_instruction"] = "确认 browser-use 会话能打开麦兔首页并保持登录态，再重新运行 --preflight。"
            checks.append(
                PreflightCheck(
                    name="maitu_browser_probe",
                    status="fail",
                    summary="Maitu dashboard was not detected in the browser-use session.",
                    details=probe_details,
                )
            )
            return

        checks.append(
            PreflightCheck(
                name="maitu_browser_probe",
                status="pass",
                summary="Browser-use can see a logged-in Maitu page shell.",
                details=probe_details,
            )
        )
        self._check_scene_visibility(operation_plan, title=title, text=text, checks=checks)

    def _check_scene_visibility(self, operation_plan: dict[str, Any], *, title: str, text: str, checks: list[PreflightCheck]) -> None:
        scene_name = operation_plan.get("scene_name")
        if not scene_name:
            return
        combined = f"{title}\n{text}"
        if str(scene_name) in combined:
            checks.append(
                PreflightCheck(
                    name="maitu_scene_visibility",
                    status="pass",
                    summary="Target scene name is visible in the current Maitu page text.",
                    details={"scene_name": scene_name},
                )
            )
            return
        checks.append(
            PreflightCheck(
                name="maitu_scene_visibility",
                status="warning",
                summary="Target scene name was not visible in the current Maitu page text; real executor must navigate/verify the project scene before mutating.",
                details={"scene_name": scene_name},
            )
        )

    def _safe_asset_path(self, relative_path: str) -> Path | None:
        normalized = relative_path.replace("\\", "/").strip()
        parsed = PurePosixPath(normalized)
        has_drive_like_prefix = bool(parsed.parts and parsed.parts[0].endswith(":"))
        if not normalized or parsed.is_absolute() or has_drive_like_prefix or ".." in parsed.parts:
            return None
        return self.assets_root.joinpath(*parsed.parts)

    @staticmethod
    def _finalize(plan_code: str | None, operation_count: int, checks: list[PreflightCheck]) -> PreflightResult:
        failure_count = sum(1 for check in checks if check.status == "fail")
        warning_count = sum(1 for check in checks if check.status == "warning")
        skipped_count = sum(1 for check in checks if check.status == "skipped")
        if failure_count:
            status = "failed"
        elif warning_count or skipped_count:
            status = "warning"
        else:
            status = "passed"
        ready_to_execute = status == "passed"
        pass_count = sum(1 for check in checks if check.status == "pass")
        summary = (
            f"Preflight {status}: {pass_count} passed, {warning_count} warning(s), "
            f"{failure_count} failure(s), {skipped_count} skipped."
        )
        return PreflightResult(
            status=status,
            ready_to_execute=ready_to_execute,
            summary=summary,
            plan_code=plan_code,
            operation_count=operation_count,
            checks=checks,
            failure_count=failure_count,
            warning_count=warning_count,
            skipped_count=skipped_count,
        )
