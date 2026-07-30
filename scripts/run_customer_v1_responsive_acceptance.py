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

import websockets

from capture_customer_v1_screenshots import (
    CdpSession,
    screenshot_evidence,
    wait_for_debug_target,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = REPO_ROOT / "docs/evidence/customer-v1-v1-0802-responsive-walkthrough.json"
SCREENSHOT_ROOT = REPO_ROOT / "docs/evidence/screenshots"

ROUTES = [
    ("assets", "/assets/library?demo=1", "素材"),
    ("research", "/research/live-sources?view=sessions&demo=1", "直播研究"),
    ("content", "/content/projects?demo=1", "内容项目"),
    ("live_rooms", "/production/live-rooms?demo=1", "直播间"),
    ("videos", "/production/videos?demo=1", "成片"),
    ("operations", "/operations/live-sessions?demo=1", "运营场次"),
    ("attribution", "/operations/attribution?demo=1", "归因"),
    ("knowledge", "/knowledge/facts?demo=1", "知识库"),
    ("learning", "/learning/effects?demo=1", "效果学习"),
]
SCREENSHOT_ROUTES = {"assets", "live_rooms", "attribution", "learning"}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000, "mobile": False},
    "mobile": {"width": 390, "height": 844, "mobile": True},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk customer-v1 workspaces at desktop and mobile sizes")
    parser.add_argument("--base-url", default="http://127.0.0.1:5181")
    parser.add_argument("--debug-port", type=int, default=9334)
    return parser.parse_args()


async def evaluate_value(session: CdpSession, expression: str) -> Any:
    response = await session.command(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    result = response.get("result") or {}
    if result.get("subtype") == "error":
        raise RuntimeError(str(result.get("description") or "browser evaluation failed"))
    return result.get("value")


async def wait_for_workspace(
    session: CdpSession,
    expected_title: str,
    *,
    timeout_seconds: float = 30,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        ready = await evaluate_value(
            session,
            """(() => {
              const heading = document.querySelector('.console-page-title h1');
              const main = document.querySelector('.console-workspace');
              return Boolean(heading && heading.textContent.trim() === %s && main && main.innerText.trim().length > 40);
            })()""" % json.dumps(expected_title),
        )
        if ready:
            await asyncio.sleep(1)
            return
        await asyncio.sleep(0.25)
    debug = await evaluate_value(
        session,
        """(() => ({
          url: location.href,
          heading: document.querySelector('.console-page-title h1')?.textContent?.trim() || null,
          main_text_length: (document.querySelector('.console-workspace')?.innerText || '').trim().length,
          body: (document.body?.innerText || '').slice(0, 500),
          runtime_errors: window.__assetGraphAcceptanceErrors || []
        }))()""",
    )
    raise RuntimeError(
        f"workspace {expected_title!r} did not become ready: {json.dumps(debug, ensure_ascii=False)}"
    )


async def navigate(
    session: CdpSession,
    base_url: str,
    path: str,
    expected_title: str,
) -> None:
    await session.command("Page.navigate", {"url": f"{base_url}/console{path}"})
    await wait_for_workspace(session, expected_title)


AUDIT_EXPRESSION = r"""(() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 && rect.width > 1 && rect.height > 1;
  };
  const selector = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary';
  const controls = [...document.querySelectorAll(selector)].filter(visible);
  const scrollableAncestor = (element) => {
    let current = element.parentElement;
    while (current && current !== document.body) {
      const style = getComputedStyle(current);
      if (/(auto|scroll)/.test(style.overflowX) && current.scrollWidth > current.clientWidth + 1) return true;
      current = current.parentElement;
    }
    return false;
  };
  const unreachable = controls.filter((element) => {
    const rect = element.getBoundingClientRect();
    return (rect.right > innerWidth + 2 || rect.left < -2) && !scrollableAncestor(element) && !element.closest('.console-sidebar:not(.is-open)');
  }).map((element) => ({
    tag: element.tagName.toLowerCase(),
    text: (element.getAttribute('aria-label') || element.getAttribute('title') || element.textContent || '').trim().slice(0, 80),
    rect: {left: Math.round(element.getBoundingClientRect().left), right: Math.round(element.getBoundingClientRect().right)}
  }));
  const overlaps = [];
  for (let index = 0; index < controls.length; index += 1) {
    const left = controls[index];
    const leftRect = left.getBoundingClientRect();
    for (let otherIndex = index + 1; otherIndex < controls.length; otherIndex += 1) {
      const right = controls[otherIndex];
      if (left.parentElement !== right.parentElement || left.contains(right) || right.contains(left)) continue;
      const rightRect = right.getBoundingClientRect();
      const width = Math.min(leftRect.right, rightRect.right) - Math.max(leftRect.left, rightRect.left);
      const height = Math.min(leftRect.bottom, rightRect.bottom) - Math.max(leftRect.top, rightRect.top);
      if (width > 4 && height > 4) {
        overlaps.push({
          first: (left.getAttribute('aria-label') || left.getAttribute('title') || left.textContent || '').trim().slice(0, 60),
          second: (right.getAttribute('aria-label') || right.getAttribute('title') || right.textContent || '').trim().slice(0, 60),
          pixels: Math.round(width * height)
        });
      }
    }
  }
  const canvases = [...document.querySelectorAll('canvas')].filter(visible).map((canvas) => {
    try {
      const context = canvas.getContext('2d');
      if (!context || !canvas.width || !canvas.height) return {status: 'blank', width: canvas.width, height: canvas.height};
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let nonBlank = false;
      const stride = Math.max(4, Math.floor(pixels.length / 4096 / 4) * 4);
      for (let offset = 0; offset < pixels.length; offset += stride) {
        if (pixels[offset + 3] > 0 && (pixels[offset] || pixels[offset + 1] || pixels[offset + 2])) { nonBlank = true; break; }
      }
      return {status: nonBlank ? 'painted' : 'blank', width: canvas.width, height: canvas.height};
    } catch (error) {
      return {status: 'unreadable', detail: error.constructor.name};
    }
  });
  const rootWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  const mainText = (document.querySelector('.console-workspace')?.innerText || '').trim();
  return {
    title: document.querySelector('.console-page-title h1')?.textContent?.trim() || '',
    main_text_length: mainText.length,
    root_width: rootWidth,
    viewport_width: innerWidth,
    horizontal_overflow_px: Math.max(0, rootWidth - innerWidth),
    control_count: controls.length,
    unreachable_controls: unreachable,
    sibling_control_overlaps: overlaps,
    canvases,
    danger_notices: [...document.querySelectorAll('.wb-inline-notice.danger')].filter(visible).map((item) => item.innerText.trim().slice(0, 200)),
    runtime_errors: [...(window.__assetGraphAcceptanceErrors || [])]
  };
})()"""


async def capture_viewport(session: CdpSession, destination: Path) -> None:
    result = await session.command(
        "Page.captureScreenshot",
        {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
    )
    import base64

    content = base64.b64decode(str(result["data"]))
    if len(content) < 5_000:
        raise RuntimeError(f"viewport screenshot is unexpectedly small: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


async def run_walkthrough(args: argparse.Namespace, websocket_url: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    screenshots: list[dict[str, Any]] = []
    async with websockets.connect(websocket_url, max_size=64 * 1024 * 1024) as websocket:
        session = CdpSession(websocket)
        await session.command("Page.enable")
        await session.command("Runtime.enable")
        await session.command(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """window.__assetGraphAcceptanceErrors = [];
                window.addEventListener('error', event => window.__assetGraphAcceptanceErrors.push(String(event.message || event.error || 'window error')));
                window.addEventListener('unhandledrejection', event => window.__assetGraphAcceptanceErrors.push(String(event.reason || 'unhandled rejection')));"""
            },
        )
        for viewport_name, viewport in VIEWPORTS.items():
            await session.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": viewport["width"],
                    "height": viewport["height"],
                    "deviceScaleFactor": 1,
                    "mobile": viewport["mobile"],
                },
            )
            await session.command(
                "Page.navigate",
                {"url": f"{args.base_url}/console/?demo=1"},
            )
            await wait_for_workspace(session, "我的任务与异常")
            for route_name, path, expected_title in ROUTES:
                await navigate(session, args.base_url, path, expected_title)
                audit = dict(await evaluate_value(session, AUDIT_EXPRESSION) or {})
                audit.update({"viewport": viewport_name, "route": route_name, "path": path})
                failures = []
                if audit.get("main_text_length", 0) < 40:
                    failures.append("blank_workspace")
                if audit.get("horizontal_overflow_px", 0) > 1:
                    failures.append("root_horizontal_overflow")
                if audit.get("unreachable_controls"):
                    failures.append("unreachable_controls")
                if audit.get("sibling_control_overlaps"):
                    failures.append("sibling_control_overlap")
                if any(canvas.get("status") == "blank" for canvas in audit.get("canvases") or []):
                    failures.append("blank_canvas")
                if audit.get("runtime_errors"):
                    failures.append("runtime_error")
                audit["failures"] = failures
                results.append(audit)

                if route_name in SCREENSHOT_ROUTES:
                    destination = SCREENSHOT_ROOT / f"customer-v1-v1-0802-{viewport_name}-{route_name}.png"
                    await capture_viewport(session, destination)
                    screenshots.append(screenshot_evidence(destination))

    failures = [
        {"viewport": item["viewport"], "route": item["route"], "failures": item["failures"]}
        for item in results
        if item["failures"]
    ]
    return {
        "schema_version": "customer-v1.responsive-walkthrough.v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "frontend_url": args.base_url,
        "viewports": VIEWPORTS,
        "route_count": len(ROUTES),
        "audit_count": len(results),
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "audits": results,
        "screenshots": screenshots,
    }


def main() -> int:
    args = parse_args()
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not chrome:
        raise SystemExit("Google Chrome is required for responsive acceptance")
    profile = Path(tempfile.mkdtemp(prefix="assetgraph-responsive-"))
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
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        evidence = asyncio.run(run_walkthrough(args, wait_for_debug_target(args.debug_port)))
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        shutil.rmtree(profile, ignore_errors=True)
    print(EVIDENCE_PATH)
    print(evidence["status"])
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
