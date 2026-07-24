from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "phase0-acceptance-package.v1"
OWNER_SCHEMA = "phase-owner-register.v1"
SIGNOFF_SCHEMA = "phase0-acceptance-signoff.v1"
REGRESSION_SCHEMA = "phase0-regression-report.v1"
REQUIRED_PHASES = {str(number) for number in range(9)}
REQUIRED_OWNER_ROLES = {"product", "engineering", "data", "security", "design"}
REQUIRED_SIGNOFF_ROLES = {
    "product",
    "engineering",
    "data",
    "security",
    "operations",
}
REQUIRED_EVIDENCE_PATHS = (
    "docs/plans/2026-07-22-live-content-production-operations-closed-loop-design.md",
    "docs/architecture/phase-0-baseline.md",
    "docs/architecture/provider-adapter-boundary.md",
    "docs/architecture/stable-error-contract.md",
    "docs/security/capability-matrix.md",
    "docs/operations/database-migration-rehearsal.md",
    "docs/operations/disaster-recovery-baseline-runbook.md",
    "docs/operations/legacy-compatibility-audit.md",
    "docs/operations/capacity-baseline-measurement-2026-07-23.md",
    "docs/evidence/phase-0-provider-neutral-producers-validation-2026-07-23.md",
    "docs/evidence/phase-0-legacy-compatibility-validation-2026-07-23.md",
    "docs/evidence/phase-0-disaster-recovery-validation-2026-07-23.md",
)
CHECKBOX_PATTERN = re.compile(
    r"^- \[(?P<state>[ x])\] `(?P<code>CHK-\d+)`", re.MULTILINE
)


class AcceptancePackageError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_report_fingerprint(
    report: dict[str, Any], key: str = "report_fingerprint"
) -> bool:
    claimed = report.get(key)
    unsigned = dict(report)
    unsigned.pop(key, None)
    return isinstance(claimed, str) and claimed == _canonical_fingerprint(unsigned)


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return None, f"file is unavailable: {path}: {error}"
    except json.JSONDecodeError as error:
        return None, f"file is not valid JSON: {path}: {error}"
    if not isinstance(payload, dict):
        return None, f"file root must be an object: {path}"
    return payload, None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report_gate(
    *,
    path: Path,
    schema_version: str,
    qualification_field: str,
    fingerprint_key: str,
) -> dict[str, Any]:
    report, error = _load_json(path)
    if report is None:
        return {"passed": False, "path": str(path), "errors": [error]}
    errors: list[str] = []
    if report.get("schema_version") != schema_version:
        errors.append(f"expected schema_version {schema_version}")
    if report.get("status") != "passed":
        errors.append("report status is not passed")
    if report.get(qualification_field) is not True:
        errors.append(f"{qualification_field} is not true")
    if not verify_report_fingerprint(report, fingerprint_key):
        errors.append("report fingerprint is invalid")
    return {
        "passed": not errors,
        "path": str(path),
        "schema_version": report.get("schema_version"),
        "qualification_field": qualification_field,
        "qualification_value": report.get(qualification_field),
        "source_report_fingerprint": report.get(fingerprint_key),
        "file_sha256": _sha256(path),
        "errors": errors,
    }


def checklist_gate(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        return {"passed": False, "errors": [str(error)]}
    phase_start = content.find("## Phase 0.")
    phase_end = content.find("## Phase 1.")
    if phase_start < 0 or phase_end <= phase_start:
        return {"passed": False, "errors": ["Phase 0 checklist boundary is missing"]}
    usage_section = content[:phase_start]
    phase_section = content[phase_start:phase_end]
    usage = {
        match.group("code"): match.group("state") == "x"
        for match in CHECKBOX_PATTERN.finditer(usage_section)
    }
    phase = {
        match.group("code"): match.group("state") == "x"
        for match in CHECKBOX_PATTERN.finditer(phase_section)
    }
    required_usage = sorted(code for code in usage if code not in {"CHK-0012"})
    required_phase = sorted(code for code in phase if code not in {"CHK-0296"})
    incomplete_usage = [code for code in required_usage if not usage[code]]
    incomplete_phase = [code for code in required_phase if not phase[code]]
    errors: list[str] = []
    if incomplete_usage:
        errors.append(f"incomplete usage controls: {', '.join(incomplete_usage)}")
    if incomplete_phase:
        errors.append(
            f"incomplete Phase 0 prerequisites: {', '.join(incomplete_phase)}"
        )
    if "CHK-0296" not in phase:
        errors.append("CHK-0296 is absent from Phase 0")
    return {
        "passed": not errors,
        "checklist_path": str(path),
        "checklist_sha256": _sha256(path),
        "completed_usage_controls": [code for code in required_usage if usage[code]],
        "incomplete_usage_controls": incomplete_usage,
        "completed_phase0_prerequisites": [
            code for code in required_phase if phase[code]
        ],
        "incomplete_phase0_prerequisites": incomplete_phase,
        "acceptance_checkbox_currently_checked": phase.get("CHK-0296", False),
        "archive_checkbox_currently_checked": usage.get("CHK-0012", False),
        "errors": errors,
    }


def owner_register_gate(path: Path) -> dict[str, Any]:
    payload, error = _load_json(path)
    if payload is None:
        return {"passed": False, "path": str(path), "errors": [error]}
    errors: list[str] = []
    if payload.get("schema_version") != OWNER_SCHEMA:
        errors.append(f"expected schema_version {OWNER_SCHEMA}")
    phases = payload.get("phases")
    if not isinstance(phases, list):
        errors.append("phases must be a list")
        phases = []
    by_code: dict[str, dict[str, Any]] = {}
    for item in phases:
        if not isinstance(item, dict):
            errors.append("phase owner item must be an object")
            continue
        phase_code = str(item.get("phase") or "")
        if phase_code in by_code:
            errors.append(f"duplicate phase owner item: {phase_code}")
        by_code[phase_code] = item
    if set(by_code) != REQUIRED_PHASES:
        errors.append(
            "phase owner coverage mismatch: "
            f"missing={sorted(REQUIRED_PHASES - set(by_code))}, "
            f"extra={sorted(set(by_code) - REQUIRED_PHASES)}"
        )
    for phase_code, item in sorted(by_code.items()):
        owners = item.get("owners")
        if not isinstance(owners, dict):
            errors.append(f"phase {phase_code} owners must be an object")
            continue
        for role in sorted(REQUIRED_OWNER_ROLES):
            owner = owners.get(role)
            if not isinstance(owner, str) or not owner.strip():
                errors.append(f"phase {phase_code} owner {role} is missing")
        appointment_ref = item.get("appointment_ref")
        if not isinstance(appointment_ref, str) or not appointment_ref.strip():
            errors.append(f"phase {phase_code} appointment_ref is missing")
    return {
        "passed": not errors,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "phase_count": len(by_code),
        "file_sha256": _sha256(path),
        "errors": errors,
    }


def regression_gate(path: Path) -> dict[str, Any]:
    payload, error = _load_json(path)
    if payload is None:
        return {"passed": False, "path": str(path), "errors": [error]}
    errors: list[str] = []
    if payload.get("schema_version") != REGRESSION_SCHEMA:
        errors.append(f"expected schema_version {REGRESSION_SCHEMA}")
    if payload.get("status") != "passed":
        errors.append("regression report status is not passed")
    if not verify_report_fingerprint(payload):
        errors.append("regression report fingerprint is invalid")
    suites = payload.get("suites")
    if not isinstance(suites, list) or not suites:
        errors.append("regression report suites are missing")
        suites = []
    elif any(
        not isinstance(item, dict)
        or item.get("status") != "passed"
        or not str(item.get("command") or "").strip()
        or not str(item.get("result") or "").strip()
        for item in suites
    ):
        errors.append("every regression suite must retain a passing command/result")
    return {
        "passed": not errors,
        "path": str(path),
        "suite_count": len(suites),
        "source_report_fingerprint": payload.get("report_fingerprint"),
        "file_sha256": _sha256(path),
        "errors": errors,
    }


def evidence_gate(extra_paths: tuple[Path, ...]) -> dict[str, Any]:
    paths = (
        tuple(REPO_ROOT / relative for relative in REQUIRED_EVIDENCE_PATHS)
        + extra_paths
    )
    missing = [str(path) for path in paths if not path.is_file()]
    files = [
        {
            "path": str(path.relative_to(REPO_ROOT))
            if path.is_relative_to(REPO_ROOT)
            else str(path),
            "sha256": _sha256(path),
            "byte_size": path.stat().st_size,
        }
        for path in paths
        if path.is_file()
    ]
    return {"passed": not missing, "files": files, "missing": missing}


def _valid_signed_at(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def signoff_gate(
    path: Path | None, technical_package_fingerprint: str
) -> dict[str, Any]:
    if path is None:
        return {
            "passed": False,
            "path": None,
            "errors": ["signoff input was not supplied"],
        }
    payload, error = _load_json(path)
    if payload is None:
        return {"passed": False, "path": str(path), "errors": [error]}
    errors: list[str] = []
    if payload.get("schema_version") != SIGNOFF_SCHEMA:
        errors.append(f"expected schema_version {SIGNOFF_SCHEMA}")
    if payload.get("technical_package_fingerprint") != technical_package_fingerprint:
        errors.append(
            "signoff technical_package_fingerprint does not match this package"
        )
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict):
        errors.append("decisions must be an object")
        decisions = {}
    if set(decisions) != REQUIRED_SIGNOFF_ROLES:
        errors.append(
            "signoff role coverage mismatch: "
            f"missing={sorted(REQUIRED_SIGNOFF_ROLES - set(decisions))}, "
            f"extra={sorted(set(decisions) - REQUIRED_SIGNOFF_ROLES)}"
        )
    for role, decision in sorted(decisions.items()):
        if not isinstance(decision, dict):
            errors.append(f"signoff {role} must be an object")
            continue
        if decision.get("decision") != "approved":
            errors.append(f"signoff {role} is not approved")
        for field in ("signer_id", "evidence_ref"):
            if not isinstance(decision.get(field), str) or not decision[field].strip():
                errors.append(f"signoff {role}.{field} is missing")
        if not _valid_signed_at(decision.get("signed_at")):
            errors.append(f"signoff {role}.signed_at is invalid")
    return {
        "passed": not errors,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "decision_roles": sorted(decisions),
        "file_sha256": _sha256(path),
        "errors": errors,
    }


def assemble_package(
    *,
    checklist_path: Path,
    owner_register_path: Path,
    capacity_report_path: Path,
    migration_report_path: Path,
    compatibility_report_path: Path,
    disaster_recovery_report_path: Path,
    regression_report_path: Path,
    signoff_path: Path | None,
) -> dict[str, Any]:
    checklist = checklist_gate(checklist_path)
    owners = owner_register_gate(owner_register_path)
    capacity = _report_gate(
        path=capacity_report_path,
        schema_version="capacity-baseline-report.v1",
        qualification_field="qualifies_for_chk_0110",
        fingerprint_key="report_fingerprint",
    )
    migration = _report_gate(
        path=migration_report_path,
        schema_version="migration-rehearsal-report.v1",
        qualification_field="qualifies_for_chk_0260",
        fingerprint_key="report_fingerprint_sha256",
    )
    compatibility = _report_gate(
        path=compatibility_report_path,
        schema_version="legacy-compatibility-audit.v1",
        qualification_field="qualifies_for_chk_0294",
        fingerprint_key="report_fingerprint",
    )
    disaster_recovery = _report_gate(
        path=disaster_recovery_report_path,
        schema_version="disaster-recovery-rehearsal.v1",
        qualification_field="qualifies_for_chk_0295",
        fingerprint_key="report_fingerprint_sha256",
    )
    regression = regression_gate(regression_report_path)
    evidence = evidence_gate(
        (
            capacity_report_path,
            migration_report_path,
            compatibility_report_path,
            disaster_recovery_report_path,
            regression_report_path,
            owner_register_path,
        )
    )
    technical_payload = {
        "schema_version": "phase0-technical-package.v1",
        "checklist": checklist,
        "owners": owners,
        "capacity": capacity,
        "migration": migration,
        "compatibility": compatibility,
        "disaster_recovery": disaster_recovery,
        "regression": regression,
        "evidence": evidence,
    }
    technical_fingerprint = _canonical_fingerprint(technical_payload)
    signoff = signoff_gate(signoff_path, technical_fingerprint)
    gates = {
        "checklist_prerequisites_complete": checklist["passed"],
        "phase_owners_assigned": owners["passed"],
        "capacity_baseline_qualified": capacity["passed"],
        "production_copy_migration_qualified": migration["passed"],
        "legacy_compatibility_qualified": compatibility["passed"],
        "disaster_recovery_qualified": disaster_recovery["passed"],
        "full_regression_qualified": regression["passed"],
        "evidence_archive_complete": evidence["passed"],
        "five_party_signoff_matches_package": signoff["passed"],
    }
    qualifies = all(gates.values())
    technical_ready = all(value for key, value in gates.items() if "signoff" not in key)
    package: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "generated_at": _utc_now(),
        "status": (
            "accepted"
            if qualifies
            else "ready_for_signoff"
            if technical_ready
            else "blocked"
        ),
        "technical_package": technical_payload,
        "technical_package_fingerprint": technical_fingerprint,
        "signoff": signoff,
        "qualification_gates": gates,
        "required_checkbox_updates_after_acceptance": [
            "CHK-0002",
            "CHK-0012",
            "CHK-0296",
        ],
        "qualifies_for_chk_0296": qualifies,
        "credentials_retained": False,
        "raw_business_rows_retained": False,
    }
    package["report_fingerprint"] = _canonical_fingerprint(package)
    return package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble and verify the AssetGraph Phase 0 acceptance package"
    )
    parser.add_argument(
        "--checklist",
        type=Path,
        default=REPO_ROOT
        / "docs"
        / "plans"
        / "2026-07-23-live-content-production-operations-implementation-checklist.md",
    )
    parser.add_argument("--owner-register", type=Path, required=True)
    parser.add_argument("--capacity-report", type=Path, required=True)
    parser.add_argument("--migration-report", type=Path, required=True)
    parser.add_argument("--compatibility-report", type=Path, required=True)
    parser.add_argument("--disaster-recovery-report", type=Path, required=True)
    parser.add_argument("--regression-report", type=Path, required=True)
    parser.add_argument("--signoff", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"acceptance package already exists: {args.output}")
    package = assemble_package(
        checklist_path=args.checklist,
        owner_register_path=args.owner_register,
        capacity_report_path=args.capacity_report,
        migration_report_path=args.migration_report,
        compatibility_report_path=args.compatibility_report,
        disaster_recovery_report_path=args.disaster_recovery_report,
        regression_report_path=args.regression_report,
        signoff_path=args.signoff,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"status={package['status']} qualifies_for_chk_0296="
        f"{str(package['qualifies_for_chk_0296']).lower()} "
        f"technical_package_fingerprint={package['technical_package_fingerprint']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
