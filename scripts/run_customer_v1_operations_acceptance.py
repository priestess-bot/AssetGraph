#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
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
CSV_PATH = EVIDENCE_DIR / "customer-v1-v1-0608-operations-import.csv"
EVIDENCE_PATH = EVIDENCE_DIR / "customer-v1-v1-0608-operations.json"
IMPORT_SCREENSHOT = EVIDENCE_DIR / "screenshots/customer-v1-v1-0608-import.png"
REPORT_SCREENSHOT = EVIDENCE_DIR / "screenshots/customer-v1-v1-0608-attribution.png"

CSV_FIELDS = [
    "场次名称",
    "平台",
    "外部场次ID",
    "账号主体",
    "直播间或渠道ID",
    "来源时区",
    "场次开始时间",
    "场次结束时间",
    "内容类型",
    "内容编码",
    "内容修订",
    "区间对象类型",
    "区间对象编码",
    "区间开始毫秒",
    "区间结束毫秒",
    "指标名称",
    "指标数值",
    "指标单位",
    "指标定义编码",
    "指标定义修订",
    "指标来源时钟",
    "时钟偏移毫秒",
    "时钟漂移PPM",
    "对齐覆盖开始毫秒",
    "对齐覆盖结束毫秒",
    "来源证据备注",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run customer-v1 operation import and attribution acceptance"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8002/api")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5181")
    parser.add_argument("--debug-port", type=int, default=9331)
    parser.add_argument("--skip-screenshots", action="store_true")
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def make_csv(plan: dict[str, Any]) -> tuple[bytes, str]:
    scenes = list((plan.get("blueprint") or {}).get("scenes") or [])
    require(len(scenes) >= 2, "acceptance requires a plan with at least two scenes")
    scenes.sort(key=lambda item: int(item.get("sort_order") or 0))
    coverage_end = max(int(scene.get("estimated_active_end_ms") or 0) for scene in scenes)
    require(coverage_end > 0, "scene timing is missing from the selected plan")

    run_at = datetime.now(UTC).replace(microsecond=0)
    session_start = run_at + timedelta(days=1)
    session_end = session_start + timedelta(milliseconds=coverage_end)
    external_id = f"ASSETGRAPH-V1-0608-{run_at:%Y%m%d%H%M%S}"
    metrics = [("watchers", "1260", "person"), ("orders", "38", "order"), ("likes", "286", "count")]
    rows: list[dict[str, str]] = []
    for index, scene in enumerate(scenes):
        metric_key, value, unit = metrics[index % len(metrics)]
        rows.append(
            {
                "场次名称": "脱敏运营验收场次",
                "平台": "douyin",
                "外部场次ID": external_id,
                "账号主体": "customer-v1-acceptance",
                "直播间或渠道ID": str(plan["target_live_room_id"]),
                "来源时区": "Asia/Shanghai",
                "场次开始时间": session_start.isoformat(),
                "场次结束时间": session_end.isoformat(),
                "内容类型": "live_room_plan",
                "内容编码": str(plan["plan_code"]),
                "内容修订": "",
                "区间对象类型": "maitu_scene",
                "区间对象编码": str(scene["scene_code"]),
                "区间开始毫秒": str(int(scene["estimated_active_start_ms"])),
                "区间结束毫秒": str(int(scene["estimated_active_end_ms"])),
                "指标名称": metric_key,
                "指标数值": value,
                "指标单位": unit,
                "指标定义编码": "",
                "指标定义修订": "",
                "指标来源时钟": "recording_elapsed_ms",
                "时钟偏移毫秒": "250",
                "时钟漂移PPM": "0",
                "对齐覆盖开始毫秒": "0",
                "对齐覆盖结束毫秒": str(coverage_end),
                "来源证据备注": "脱敏平台导出；按录屏锚点校准到实际使用方案。",
            }
        )

    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    content = ("\ufeff" + stream.getvalue()).encode("utf-8")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.write_bytes(content)
    return content, external_id


def run_api_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    with httpx.Client(base_url=args.api_url, timeout=30) as client:
        plans_response = client.get("/functional-live-room-plans")
        plans_response.raise_for_status()
        plans = plans_response.json()
        plan = next((item for item in plans if item.get("status") == "ready"), None)
        require(plan is not None, "no ready live-room plan is available for acceptance")
        content, external_id = make_csv(plan)

        preview_response = client.post(
            "/functional-operations/import-batches/preview",
            files={"file": (CSV_PATH.name, content, "text/csv")},
            data={"actor": "customer-v1-acceptance"},
        )
        preview_response.raise_for_status()
        preview = preview_response.json()
        summary = preview["preview_summary"]
        require(summary["invalid_row_count"] == 0, "import preview contains invalid rows")
        require(summary["pending_binding_row_count"] == 0, "content binding was not resolved")
        require(summary["ready_row_count"] == len(preview["rows"]), "not all rows are ready")

        confirm_response = client.post(
            f"/functional-operations/import-batches/{preview['batch_code']}/confirm",
            json={"actor": "customer-v1-acceptance"},
        )
        confirm_response.raise_for_status()
        confirmed = confirm_response.json()
        session_codes = {
            row.get("imported_session_code") for row in confirmed["rows"] if row.get("imported_session_code")
        }
        require(len(session_codes) == 1, "confirmed rows did not resolve to one operation session")
        session_code = next(iter(session_codes))

        timeline_response = client.get(
            f"/functional-operations/sessions/{session_code}/content-timeline"
        )
        timeline_response.raise_for_status()
        timeline = timeline_response.json()
        require(timeline.get("time_mapping"), "explicit TimeMapping was not persisted")
        require(
            timeline["time_mapping"]["source_clock"] == "recording_elapsed_ms",
            "unexpected source clock",
        )
        require(len(timeline["spans"]) == len(confirmed["rows"]), "content spans were lost")
        require(
            all(span["alignment_status"] == "aligned" for span in timeline["spans"]),
            "not every content interval is explicitly aligned",
        )

        report_response = client.post(
            "/functional-operations/attribution-reports",
            json={"metric_key": "watchers", "session_codes": [session_code]},
        )
        report_response.raise_for_status()
        report = report_response.json()
        dimensions: dict[str, list[dict[str, Any]]] = {}
        for member in report["results"]["dimension_groups"]:
            dimensions.setdefault(member["dimension_type"], []).append(member)
        require("operation_session" in dimensions, "session dimension is missing")
        require("content_segment" in dimensions, "content segment dimension is missing")
        require("material" in dimensions, "material dimension is missing")
        require(
            all(
                not member["effect_signal_eligible"]
                for members in dimensions.values()
                for member in members
            ),
            "descriptive acceptance data became effect-eligible",
        )

        source_response = client.get(
            f"/functional-operations/import-batches/{preview['batch_code']}/source"
        )
        source_response.raise_for_status()
        require(source_response.content == content, "preserved source file does not match upload")

    return {
        "schema_version": "customer-v1.operations-acceptance.v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "source_file": {
            "path": CSV_PATH.relative_to(REPO_ROOT).as_posix(),
            "external_session_id": external_id,
            "size_bytes": len(content),
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
        },
        "content_binding": {
            "kind": "live_room_plan",
            "plan_code": plan["plan_code"],
            "variant_code": plan["variant_code"],
            "scene_codes": [span["scene_code"] for span in timeline["spans"]],
        },
        "import": {
            "batch_code": confirmed["batch_code"],
            "session_code": session_code,
            "status": confirmed["status"],
            "preview_summary": confirmed["preview_summary"],
            "source_file_roundtrip_verified": True,
        },
        "time_mapping": timeline["time_mapping"],
        "timeline": {
            "span_count": len(timeline["spans"]),
            "alignment_coverage_ratio": timeline["alignment_coverage_ratio"],
            "spans": [
                {
                    "exposure_code": span["exposure_code"],
                    "scene_code": span["scene_code"],
                    "source_start_ms": span["source_start_ms"],
                    "source_end_ms": span["source_end_ms"],
                    "alignment_status": span["alignment_status"],
                }
                for span in timeline["spans"]
            ],
        },
        "report": {
            "report_code": report["report_code"],
            "metric_key": report["metric_key"],
            "evidence_level": report["evidence_level"],
            "status": report["status"],
            "fingerprint_sha256": report["fingerprint_sha256"],
            "quality_snapshot": report["quality_snapshot"],
            "dimensions": {
                key: {
                    "member_count": len(value),
                    "effect_eligible": any(
                        member["effect_signal_eligible"] for member in value
                    ),
                }
                for key, value in dimensions.items()
            },
        },
        "tests": {
            "source_file_roundtrip": "passed",
            "explicit_time_mapping": "passed",
            "all_intervals_aligned": "passed",
            "descriptive_only_gate": "passed",
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
        await navigate(session, "/operations/live-sessions?demo=1", "批量导入运营数据")
        await evaluate(
            session,
            "[...document.querySelectorAll('button')].find((button) => "
            "button.textContent?.includes('打开导入'))?.click(); true",
        )
        await wait_for_text(session, CSV_PATH.name)
        await evaluate(
            session,
            f"[...document.querySelectorAll('button')].find((button) => "
            f"button.textContent?.includes({json.dumps(CSV_PATH.name)}))?.click(); true",
        )
        await wait_for_text(session, evidence["import"]["batch_code"])
        await asyncio.sleep(0.5)
        await capture_full_page(session, IMPORT_SCREENSHOT)

        await navigate(
            session,
            "/operations/attribution?demo=1",
            evidence["report"]["report_code"],
        )
        await wait_for_text(session, "四维描述统计")
        await capture_full_page(session, REPORT_SCREENSHOT)


def run_screenshot_acceptance(args: argparse.Namespace, evidence: dict[str, Any]) -> None:
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    require(chrome is not None, "Google Chrome is required for screenshot acceptance")
    profile = Path(tempfile.mkdtemp(prefix="assetgraph-v1-0608-chrome-"))
    process = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
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
            screenshot_evidence(IMPORT_SCREENSHOT),
            screenshot_evidence(REPORT_SCREENSHOT),
        ]
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(EVIDENCE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
