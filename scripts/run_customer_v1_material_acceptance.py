#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import websockets

from capture_customer_v1_screenshots import (
    CdpSession,
    capture_full_page,
    screenshot_evidence,
    wait_for_debug_target,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = REPO_ROOT / "docs/evidence/customer-v1-v1-0212-material-acceptance.json"
SCREENSHOT_PATH = REPO_ROOT / "docs/evidence/screenshots/customer-v1-v1-0212-material-group.png"
GROUP_TITLE = "V1 四角色桌面陈列验收"
ROLES = ("background", "product_display", "promotion_text", "digital_human")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the customer-v1 four-role material acceptance")
    parser.add_argument("--api-base", default="http://127.0.0.1:8002/api")
    parser.add_argument("--ui-base", default="http://127.0.0.1:5181")
    parser.add_argument("--debug-port", type=int, default=9336)
    return parser.parse_args()


def request_json(
    api_base: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    allow_not_found: bool = False,
) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        if allow_not_found and exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc
    return json.loads(content) if content else None


def choose_assets(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    for role in ROLES:
        candidates = [
            row
            for row in rows
            if role in (row.get("material_roles") or [])
            and row.get("rights_status") == "approved"
            and row.get("execution_capability") == "maitu_bound"
            and str(row.get("asset_code") or "") not in used
        ]
        if not candidates:
            raise RuntimeError(f"no approved maitu_bound sample is available for {role}")
        selected[role] = candidates[0]
        used.add(str(candidates[0]["asset_code"]))
    return selected


def desired_constraints(selected: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        str(selected["background"]["asset_code"]): [
            {"kind": "allowed_region", "hard": True, "parameters": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"kind": "pin_layer_bottom", "hard": True, "parameters": {}},
            {
                "kind": "table_surface",
                "hard": True,
                "parameters": {
                    "name": "product_table",
                    "x": 0.18,
                    "y": 0.64,
                    "width": 0.64,
                    "height": 0.22,
                    "product_role": "product_display",
                    "product_anchor": "bottom_center",
                },
            },
        ],
        str(selected["product_display"]["asset_code"]): [
            {"kind": "require_named_region", "hard": True, "parameters": {"region": "product_table"}},
            {"kind": "preserve_aspect_ratio", "hard": True, "parameters": {}},
            {
                "kind": "size_range",
                "hard": True,
                "parameters": {"min_width": 0.18, "max_width": 0.45, "min_height": 0.18, "max_height": 0.45},
            },
            {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
        ],
        str(selected["promotion_text"]["asset_code"]): [
            {"kind": "allowed_region", "hard": True, "parameters": {"x": 0.08, "y": 0.06, "width": 0.84, "height": 0.18}},
            {"kind": "preserve_aspect_ratio", "hard": True, "parameters": {}},
            {"kind": "pin_layer_top", "hard": True, "parameters": {}},
            {"kind": "above_role", "hard": True, "parameters": {"role": "product_display"}},
        ],
        str(selected["digital_human"]["asset_code"]): [
            {"kind": "allowed_region", "hard": True, "parameters": {"x": 0.05, "y": 0.2, "width": 0.46, "height": 0.72}},
            {"kind": "preserve_aspect_ratio", "hard": True, "parameters": {}},
            {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
            {"kind": "below_role", "hard": True, "parameters": {"role": "promotion_text"}},
        ],
    }


def normalize_constraints(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized = [
        {
            "kind": str(row.get("kind") or ""),
            "hard": row.get("hard") is not False,
            "parameters": row.get("parameters") if isinstance(row.get("parameters"), dict) else {},
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return sorted(normalized, key=lambda row: row["kind"])


def ensure_profiles(
    api_base: str,
    constraints_by_asset: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for asset_code, constraints in constraints_by_asset.items():
        current = request_json(
            api_base,
            f"/assets/{asset_code}/constraint-profile",
            allow_not_found=True,
        )
        if not isinstance(current, dict) or normalize_constraints(current.get("constraints")) != normalize_constraints(constraints):
            current = request_json(
                api_base,
                f"/assets/{asset_code}/constraint-profile",
                method="POST",
                payload={"constraints": constraints},
            )
        if not isinstance(current, dict):
            raise RuntimeError(f"constraint profile for {asset_code} was not returned")
        profiles[asset_code] = current
    return profiles


def ensure_group(api_base: str, asset_codes: list[str]) -> dict[str, Any]:
    groups = request_json(api_base, "/assets/groups")
    existing = next(
        (row for row in groups if isinstance(row, dict) and row.get("title") == GROUP_TITLE),
        None,
    )
    if existing is None:
        group = request_json(
            api_base,
            "/assets/groups",
            method="POST",
            payload={
                "title": GROUP_TITLE,
                "description": "背景提供桌面区域，商品位于桌面并高于背景，贴片置顶，数字人位于背景与贴片之间。",
                "asset_codes": asset_codes,
            },
        )
    else:
        group = request_json(
            api_base,
            f"/assets/groups/{existing['group_code']}/members",
            method="PUT",
            payload={"asset_codes": asset_codes},
        )
    if not isinstance(group, dict) or set(group.get("asset_codes") or []) != set(asset_codes):
        raise RuntimeError("four-role material group did not round-trip")
    return group


async def capture_group(args: argparse.Namespace, websocket_url: str) -> None:
    async with websockets.connect(websocket_url, max_size=64 * 1024 * 1024) as websocket:
        session = CdpSession(websocket)
        await session.command("Page.enable")
        await session.command("Runtime.enable")
        await session.command(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        await session.command(
            "Page.navigate",
            {"url": f"{args.ui_base}/console/assets/library?tab=groups&demo=1"},
        )
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            response = await session.command(
                "Runtime.evaluate",
                {
                    "expression": f"document.body?.innerText.includes({json.dumps(GROUP_TITLE)}) === true",
                    "returnByValue": True,
                },
            )
            if (response.get("result") or {}).get("value") is True:
                await asyncio.sleep(1)
                await capture_full_page(session, SCREENSHOT_PATH)
                return
            await asyncio.sleep(0.25)
        raise RuntimeError("material acceptance group did not appear in the UI")


def capture_screenshot(args: argparse.Namespace) -> None:
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not chrome:
        raise RuntimeError("Google Chrome is required for the material acceptance screenshot")
    profile = Path(tempfile.mkdtemp(prefix="assetgraph-material-acceptance-"))
    process = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            f"--remote-debugging-port={args.debug_port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        asyncio.run(capture_group(args, wait_for_debug_target(args.debug_port)))
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
    rows = request_json(args.api_base, "/assets?limit=200")
    if not isinstance(rows, list):
        raise RuntimeError("asset list response is invalid")
    selected = choose_assets([row for row in rows if isinstance(row, dict)])
    constraints = desired_constraints(selected)
    profiles = ensure_profiles(args.api_base, constraints)
    asset_codes = [str(selected[role]["asset_code"]) for role in ROLES]
    group = ensure_group(args.api_base, asset_codes)
    capture_screenshot(args)

    evidence = {
        "schema_version": "customer-v1.material-acceptance.v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "group": {
            "group_code": group["group_code"],
            "title": group["title"],
            "asset_codes": group["asset_codes"],
        },
        "roles": {
            role: {
                "asset_code": selected[role]["asset_code"],
                "title": selected[role].get("title"),
                "rights_status": selected[role]["rights_status"],
                "execution_capability": selected[role]["execution_capability"],
                "constraint_profile_code": profiles[str(selected[role]["asset_code"])]["profile_code"],
                "constraint_revision": profiles[str(selected[role]["asset_code"])]["revision_number"],
                "constraint_fingerprint": profiles[str(selected[role]["asset_code"])]["fingerprint_sha256"],
                "constraint_kinds": [row["kind"] for row in constraints[str(selected[role]["asset_code"])]],
            }
            for role in ROLES
        },
        "relationship_assertions": [
            "background defines product_table and is pinned to bottom",
            "product_display requires product_table and is above background",
            "promotion_text is pinned to top and above product_display",
            "digital_human is above background and below promotion_text",
        ],
        "screenshot": screenshot_evidence(SCREENSHOT_PATH),
    }
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(EVIDENCE_PATH)
    print("passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
