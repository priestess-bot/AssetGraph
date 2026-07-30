#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import websockets

from capture_customer_v1_screenshots import (
    CdpSession,
    capture_full_page,
    screenshot_evidence,
    wait_for_debug_target,
    wait_for_text,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs/evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "customer-v1-v1-0708-effect-reproduction.json"
LEARNING_SCREENSHOT = EVIDENCE_DIR / "screenshots/customer-v1-v1-0708-learning.png"
CONTENT_SCREENSHOT = EVIDENCE_DIR / "screenshots/customer-v1-v1-0708-content-project.png"
DEFAULT_REPORT_CODE = "ATTR-20260725-000016"
DEFAULT_PROJECT_CODE = "CONTENT-20260725-000002"
DEFAULT_IMPORTED_SESSION_CODE = "OPS-20260725-000029"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run customer-v1 imported-session to effect-reproduction acceptance"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8002/api")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5181")
    parser.add_argument("--debug-port", type=int, default=9332)
    parser.add_argument("--report-code", default=DEFAULT_REPORT_CODE)
    parser.add_argument("--project-code", default=DEFAULT_PROJECT_CODE)
    parser.add_argument("--session-code", default=DEFAULT_IMPORTED_SESSION_CODE)
    parser.add_argument("--skip-screenshots", action="store_true")
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def template_choices(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    content = snapshot.get("content") or {}
    refs = [content.get("primary_template_ref"), *(content.get("secondary_template_refs") or [])]
    seen: set[str] = set()
    choices: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("template_code"):
            continue
        code = str(ref["template_code"])
        if code in seen:
            continue
        seen.add(code)
        choices.append({"source_template_code": code, "action": "preserve"})
    return choices


def paragraph_choices(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    content = snapshot.get("content") or {}
    choices = [
        {"field_key": field, "action": "preserve"}
        for field in ("theme", "story", "detailed_design")
        if content.get(field)
    ]
    choices.extend(
        {
            "source_block_code": str(block["block_code"]),
            "action": "preserve",
        }
        for block in snapshot.get("script_blocks") or []
        if isinstance(block, dict) and block.get("block_code")
    )
    return choices


def material_choices(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    variants = [item for item in snapshot.get("production_variants") or [] if isinstance(item, dict)]
    material_snapshot = (variants[0].get("material_snapshot_ref") if variants else None) or {}
    return [
        {"source_asset_code": str(code), "action": "preserve"}
        for code in dict.fromkeys(material_snapshot.get("asset_codes") or [])
    ]


def run_api_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    with httpx.Client(base_url=args.api_url, timeout=60) as client:
        reports_response = client.get("/functional-operations/attribution-reports")
        reports_response.raise_for_status()
        report = next(
            (item for item in reports_response.json() if item["report_code"] == args.report_code),
            None,
        )
        require(report is not None, f"attribution report {args.report_code} was not found")
        require(
            args.session_code in report.get("session_codes", []),
            "the selected report is not bound to the imported acceptance session",
        )
        require(report.get("evidence_level") == "descriptive", "source report is not descriptive")

        source_response = client.get(f"/content-projects/{args.project_code}")
        source_response.raise_for_status()
        source = source_response.json()
        require(source.get("generated") is True, "source content chain is incomplete")

        create_response = client.post(
            "/functional-learning/effects",
            json={
                "attribution_report_code": args.report_code,
                "subject_type": "content_project",
                "subject_code": args.project_code,
                "evidence_level": "descriptive",
                "context": {
                    "acceptance_session_code": args.session_code,
                    "workflow": "customer-v1-v1-0708",
                },
                "note": "已导入场次的描述性结果仅作再生产提示；保留冻结输入后独立评估新草稿。",
            },
        )
        create_response.raise_for_status()
        effect = create_response.json()
        eligibility = effect["eligibility_snapshot"]
        require(
            eligibility.get("qualification") == "descriptive_hint_only",
            "descriptive effect was not labelled as a hint",
        )
        require(
            eligibility.get("recommendation_eligible") is False,
            "descriptive effect unexpectedly became recommendation-eligible",
        )
        require(effect["status"] == "candidate", "effect was not created as a candidate")

        approve_response = client.post(
            f"/functional-learning/effects/{effect['effect_code']}/approve",
            json={"actor": "customer-v1-acceptance"},
        )
        approve_response.raise_for_status()
        approved = approve_response.json()
        require(approved["status"] == "approved", "effect approval failed")

        snapshot = (approved.get("effect_payload") or {}).get("subject_snapshot") or {}
        explicit_templates = template_choices(snapshot)
        explicit_paragraphs = paragraph_choices(snapshot)
        explicit_materials = material_choices(snapshot)
        require(explicit_paragraphs, "source snapshot has no reproducible paragraphs")
        require(explicit_materials, "source snapshot has no reproducible production materials")

        reproduce_payload = {
            "title": f"{source['title']} - 效果再生产验收",
            "change_hypothesis": "保留原主题、剧本结构和素材，仅将已导入场次的描述性洞察作为提示，独立评估新草稿。",
            "template_choices": explicit_templates,
            "paragraph_choices": explicit_paragraphs,
            "material_choices": explicit_materials,
            "actor": "customer-v1-acceptance",
        }
        reproduce_response = client.post(
            f"/functional-learning/effects/{effect['effect_code']}/reproduce",
            json=reproduce_payload,
        )
        reproduce_response.raise_for_status()
        reproduction = reproduce_response.json()

        result_response = client.get(
            f"/content-projects/{reproduction['reproduced_project_code']}"
        )
        result_response.raise_for_status()
        result = result_response.json()
        require(result.get("status") == "confirmed", "reproduced content project is not confirmed")
        require(result.get("generated") is True, "reproduced content chain is incomplete")
        require(result.get("story_brief"), "reproduced StoryBrief is missing")
        require(result.get("script"), "reproduced ScriptRevision is missing")
        require(result.get("program"), "reproduced ProgramRevision is missing")
        require(result.get("shot_list"), "reproduced ShotListRevision is missing")
        selection = (result.get("content") or {}).get("effect_reproduction_selection") or {}
        require(
            selection.get("paragraph_choices") == explicit_paragraphs,
            "paragraph choices were not frozen into the result",
        )
        require(
            len(selection.get("material_choices") or []) == len(explicit_materials),
            "material choices were not frozen into the result",
        )

        decisions_response = client.get("/functional-learning/decisions")
        decisions_response.raise_for_status()
        decision = next(
            (
                item
                for item in decisions_response.json()
                if item["decision_code"] == reproduction["decision_code"]
            ),
            None,
        )
        require(decision is not None, "reproduction DecisionLog was not persisted")
        require(
            decision.get("decision_type") == "effect_reproduction",
            "reproduction decision type is incorrect",
        )
        decision_payload = decision.get("decision_payload") or {}
        require(
            decision_payload.get("effect_code") == effect["effect_code"],
            "DecisionLog lost the source effect",
        )
        require(
            decision_payload.get("applied_choices") == reproduction.get("applied_choices"),
            "DecisionLog lost the applied choices",
        )

        recommendation_response = client.get(
            f"/functional-learning/recommendations/{args.project_code}"
        )
        recommendation_response.raise_for_status()
        recommendations = recommendation_response.json()
        effect_hint = next(
            (
                hint
                for hint in recommendations.get("project_effect_hints") or []
                if hint["effect_code"] == effect["effect_code"]
            ),
            None,
        )
        require(effect_hint is not None, "the effect is missing from project hints")
        require(effect_hint["eligible"] is False, "descriptive effect became score-eligible")
        require(float(effect_hint["contribution"]) == 0, "descriptive effect changed a score")

        chain_response = client.get(
            f"/content-projects/{reproduction['reproduced_project_code']}/content-chain-revisions"
        )
        chain_response.raise_for_status()
        chain = chain_response.json()
        chain_types = {item["object_type"] for item in chain}
        require(
            {"content_project", "design_brief", "story_brief", "script", "program", "shot_list"}
            <= chain_types,
            "reproduced revision chain is incomplete",
        )

    return {
        "schema_version": "customer-v1.learning-acceptance.v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "imported_evidence": {
            "session_code": args.session_code,
            "attribution_report_code": report["report_code"],
            "report_status": report["status"],
            "report_evidence_level": report["evidence_level"],
            "quality_snapshot": report.get("quality_snapshot") or {},
        },
        "source": {
            "project_code": source["project_code"],
            "revision_number": source["revision_number"],
            "title": source["title"],
            "generated": source["generated"],
        },
        "effect": {
            "effect_code": effect["effect_code"],
            "status": approved["status"],
            "evidence_level": effect["evidence_level"],
            "eligibility_snapshot": eligibility,
            "recommendation_hint": effect_hint,
        },
        "explicit_choices": {
            "template_choices": explicit_templates,
            "paragraph_choices": explicit_paragraphs,
            "material_choices": explicit_materials,
        },
        "result": {
            **reproduction,
            "content_status": result["status"],
            "generated": result["generated"],
            "content_chain_types": sorted(chain_types),
            "production_boundary": "draft_non_executable",
        },
        "tests": {
            "imported_session_bound": "passed",
            "descriptive_hint_only": "passed",
            "explicit_choices_frozen": "passed",
            "new_content_chain_complete": "passed",
            "draft_production_revision_created": "passed",
            "decision_lineage_complete": "passed",
            "effect_score_contribution_zero": "passed",
        },
    }


async def evaluate(session: CdpSession, expression: str) -> Any:
    result = await session.command(
        "Runtime.evaluate", {"expression": expression, "returnByValue": True}
    )
    return (result.get("result") or {}).get("value")


async def navigate(session: CdpSession, path: str, expected: str) -> None:
    await evaluate(
        session,
        f"window.history.pushState(null, '', {json.dumps(path)});"
        "window.dispatchEvent(new PopStateEvent('popstate')); true",
    )
    await wait_for_text(session, expected)
    await asyncio.sleep(1)


async def capture_screenshots(
    args: argparse.Namespace, websocket_url: str, evidence: dict[str, Any]
) -> None:
    effect_code = evidence["effect"]["effect_code"]
    project_code = evidence["result"]["reproduced_project_code"]
    async with websockets.connect(websocket_url, max_size=64 * 1024 * 1024) as websocket:
        session = CdpSession(websocket)
        await session.command("Page.enable")
        await session.command("Runtime.enable")
        await session.command(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        await session.command("Page.navigate", {"url": f"{args.frontend_url}/console/?demo=1"})
        await wait_for_text(session, "AssetGraph")
        await navigate(session, "/learning/effects?demo=1", effect_code)
        await evaluate(
            session,
            "(() => {"
            f"const item=[...document.querySelectorAll('.learning-effect')].find((node)=>node.textContent?.includes({json.dumps(effect_code)}));"
            "const button=[...(item?.querySelectorAll('button') || [])].find((node)=>node.textContent?.includes('配置再生产'));"
            "button?.click(); item?.scrollIntoView({block:'start'}); return Boolean(button); })()",
        )
        await wait_for_text(session, "主题、故事与剧本段落")
        await asyncio.sleep(0.5)
        await capture_full_page(session, LEARNING_SCREENSHOT)

        await navigate(
            session,
            f"/content/projects?demo=1&project={project_code}",
            project_code,
        )
        await wait_for_text(session, "内容链修订")
        await capture_full_page(session, CONTENT_SCREENSHOT)


def run_screenshot_acceptance(args: argparse.Namespace, evidence: dict[str, Any]) -> None:
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    require(chrome is not None, "Google Chrome is required for screenshot acceptance")
    profile = Path(tempfile.mkdtemp(prefix="assetgraph-v1-0708-chrome-"))
    process = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-software-rasterizer",
            "--hide-scrollbars",
            f"--remote-debugging-port={args.debug_port}",
            f"--user-data-dir={profile}",
            "--window-size=1440,1000",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        websocket_url = wait_for_debug_target(args.debug_port)
        asyncio.run(capture_screenshots(args, websocket_url, evidence))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    args = parse_args()
    evidence = run_api_acceptance(args)
    if not args.skip_screenshots:
        run_screenshot_acceptance(args, evidence)
        evidence["screenshots"] = [
            screenshot_evidence(LEARNING_SCREENSHOT),
            screenshot_evidence(CONTENT_SCREENSHOT),
        ]
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(EVIDENCE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
