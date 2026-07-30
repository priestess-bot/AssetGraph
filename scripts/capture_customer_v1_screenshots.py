#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import websockets


REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture customer-v1 dual-branch acceptance screens")
    parser.add_argument("--base-url", default="http://127.0.0.1:5181")
    parser.add_argument("--debug-port", type=int, default=9330)
    parser.add_argument("--live-plan-code", required=True)
    parser.add_argument("--video-plan-code", required=True)
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=REPO_ROOT / "docs/evidence/customer-v1-v1-0515-dual-branch.json",
    )
    parser.add_argument(
        "--live-output",
        type=Path,
        default=REPO_ROOT / "docs/evidence/screenshots/customer-v1-v1-0515-live-room.png",
    )
    parser.add_argument(
        "--video-output",
        type=Path,
        default=REPO_ROOT / "docs/evidence/screenshots/customer-v1-v1-0515-video.png",
    )
    return parser.parse_args()


class CdpSession:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self.next_id = 1

    async def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        command_id = self.next_id
        self.next_id += 1
        await self.websocket.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(await self.websocket.recv())
            if message.get("id") != command_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return dict(message.get("result") or {})


def wait_for_debug_target(port: int, timeout_seconds: float = 15) -> str:
    deadline = time.monotonic() + timeout_seconds
    endpoint = f"http://127.0.0.1:{port}/json/list"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=1) as response:
                targets = json.load(response)
            page = next((target for target in targets if target.get("type") == "page"), None)
            if page and page.get("webSocketDebuggerUrl"):
                return str(page["webSocketDebuggerUrl"])
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Chrome DevTools target did not become ready")


async def wait_for_text(session: CdpSession, expected: str, timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    expression = f"document.body && document.body.innerText.includes({json.dumps(expected)})"
    while time.monotonic() < deadline:
        result = await session.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        if ((result.get("result") or {}).get("value")) is True:
            return
        await asyncio.sleep(0.25)
    body = await session.command(
        "Runtime.evaluate",
        {"expression": "document.body ? document.body.innerText.slice(0, 2000) : ''", "returnByValue": True},
    )
    raise RuntimeError(
        f"page did not show {expected!r}: {((body.get('result') or {}).get('value') or '')}"
    )


async def navigate_spa(session: CdpSession, path: str, expected: str) -> None:
    expression = (
        f"window.history.pushState(null, '', {json.dumps(path)});"
        "window.dispatchEvent(new PopStateEvent('popstate')); true"
    )
    await session.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    await wait_for_text(session, expected)
    await asyncio.sleep(1)


async def capture_full_page(session: CdpSession, destination: Path) -> None:
    metrics = await session.command("Page.getLayoutMetrics")
    content = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
    width = max(1440, int(float(content.get("width") or 1440)))
    height = max(1000, min(16_000, int(float(content.get("height") or 1000))))
    result = await session.command(
        "Page.captureScreenshot",
        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
        },
    )
    content_bytes = base64.b64decode(str(result["data"]))
    if len(content_bytes) < 10_000:
        raise RuntimeError(f"captured screenshot is unexpectedly small: {len(content_bytes)} bytes")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content_bytes)


async def capture(args: argparse.Namespace, websocket_url: str) -> None:
    async with websockets.connect(websocket_url, max_size=64 * 1024 * 1024) as websocket:
        session = CdpSession(websocket)
        await session.command("Page.enable")
        await session.command("Runtime.enable")
        await session.command(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1440,
                "height": 1000,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        await session.command("Page.navigate", {"url": f"{args.base_url}/console/?demo=1"})
        await wait_for_text(session, "AssetGraph")
        await navigate_spa(
            session,
            "/production/live-rooms?demo=1",
            args.live_plan_code,
        )
        await capture_full_page(session, args.live_output.resolve())
        await navigate_spa(
            session,
            "/production/videos?demo=1",
            args.video_plan_code,
        )
        await wait_for_text(session, "可复现证据")
        await capture_full_page(session, args.video_output.resolve())


def screenshot_evidence(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"screenshot is not a valid PNG: {path}")
    width, height = struct.unpack(">II", content[16:24])
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "width": width,
        "height": height,
        "size_bytes": len(content),
        "checksum_sha256": hashlib.sha256(content).hexdigest(),
    }


def update_acceptance_evidence(args: argparse.Namespace) -> None:
    evidence_path = args.evidence_path.expanduser().resolve()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["screenshots"] = [
        screenshot_evidence(args.live_output.expanduser().resolve()),
        screenshot_evidence(args.video_output.expanduser().resolve()),
    ]
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not chrome:
        raise SystemExit("Google Chrome is required for screenshot capture")
    profile = Path(tempfile.mkdtemp(prefix="assetgraph-customer-v1-chrome-"))
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
        asyncio.run(capture(args, websocket_url))
        update_acceptance_evidence(args)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        shutil.rmtree(profile, ignore_errors=True)
    print(args.live_output.resolve())
    print(args.video_output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
