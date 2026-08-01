#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs/plans/2026-07-26-customer-experience-v1-implementation-checklist.md"
NEW_IDS = [
    *(f"V1-{number:04d}" for number in range(520, 525)),
    *(f"V1-{number:04d}" for number in range(530, 534)),
    *(f"V1-{number:04d}" for number in range(540, 545)),
    *(f"V1-{number:04d}" for number in range(550, 553)),
    *(f"V1-{number:04d}" for number in range(810, 815)),
]
LEGACY_ADAPTER_IDS = {"V1-0107", "V1-0108", "V1-0502", "V1-0503", "V1-0506"}
PRODUCT_E2E_IDS = {"V1-0550", "V1-0551", "V1-0552"}


def audit(*, require_complete: bool) -> dict[str, Any]:
    text = CHECKLIST.read_text(encoding="utf-8")
    item_pattern = re.compile(r"^- \[(?P<state>[ x])\] `(?P<id>V1-\d{4})`(?P<body>.*)$", re.MULTILINE)
    items = {match.group("id"): match for match in item_pattern.finditer(text)}
    errors: list[str] = []
    completed: list[str] = []

    for check_id in NEW_IDS:
        match = items.get(check_id)
        if match is None:
            errors.append(f"missing checklist item: {check_id}")
            continue
        checked = match.group("state") == "x"
        if require_complete and not checked:
            errors.append(f"item is not complete: {check_id}")
        if not checked:
            continue
        completed.append(check_id)
        body = match.group("body")
        if "证据：" not in body:
            errors.append(f"checked item has no evidence label: {check_id}")
        evidence_paths = [
            value
            for value in re.findall(r"`([^`]+)`", body)
            if value.startswith("docs/evidence/")
        ]
        if not evidence_paths:
            errors.append(f"checked item has no docs/evidence path: {check_id}")
        for relative_path in evidence_paths:
            if not (ROOT / relative_path).exists():
                errors.append(f"evidence path does not exist for {check_id}: {relative_path}")
        record_pattern = re.compile(
            rf"^\|\s*\d{{4}}-\d{{2}}-\d{{2}}\s*\|\s*`{re.escape(check_id)}`\s*\|",
            re.MULTILINE,
        )
        if record_pattern.search(text) is None:
            errors.append(f"checked item has no single-id execution record: {check_id}")

    for check_id in LEGACY_ADAPTER_IDS:
        match = items.get(check_id)
        if match is None or "`adapter_validation`" not in match.group("body"):
            errors.append(f"legacy Maitu evidence is not labelled adapter_validation: {check_id}")
        if match is not None and "`product_e2e`" in match.group("body"):
            errors.append(f"legacy Maitu evidence is incorrectly labelled product_e2e: {check_id}")

    for check_id in PRODUCT_E2E_IDS & set(completed):
        if "`product_e2e`" not in items[check_id].group("body"):
            errors.append(f"product acceptance is not labelled product_e2e: {check_id}")

    return {
        "schema_version": "customer-v1-e2e-checklist-audit.v1",
        "checklist": str(CHECKLIST.relative_to(ROOT)),
        "required_count": len(NEW_IDS),
        "completed_count": len(completed),
        "completed_ids": completed,
        "require_complete": require_complete,
        "passed": not errors,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the customer-v1 product E2E checklist evidence.")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(require_complete=args.require_complete)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
