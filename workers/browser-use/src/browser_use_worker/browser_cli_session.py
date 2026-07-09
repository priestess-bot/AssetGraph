from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Callable

from .maitu_executor import MaituBrowserExecutionError, MaituBrowserSession

CommandRunner = Callable[[Sequence[str],], str]


@dataclass(slots=True)
class BrowserUseCliSessionConfig:
    browser_use_repo: str = "D:/browser-use"
    home_url: str = "https://live2.maituai.com/"
    login_url: str = "https://live2.maituai.com/Login"
    headed: bool = True
    timeout_seconds: float = 60.0
    read_only: bool = True


@dataclass(slots=True)
class MaituPageProbe:
    title: str
    url: str
    text: str
    logged_in: bool
    login_required: bool
    opened_home: bool = False


class BrowserUseCliSession(MaituBrowserSession):
    """Read-only Maitu session backed by the local browser-use CLI.

    This first concrete session intentionally probes browser/page state only.  It
    does not click upload/save/replace controls, so it is safe to use for mapping
    login status and the Maitu page shell before wiring mutating automation.
    """

    PAGE_SUMMARY_SCRIPT = "(() => JSON.stringify({title:document.title,href:location.href,text:document.body?.innerText||''}))()"

    def __init__(
        self,
        config: BrowserUseCliSessionConfig | None = None,
        *,
        runner: Callable[[Sequence[str]], str] | Callable[..., str] | None = None,
    ) -> None:
        self.config = config or BrowserUseCliSessionConfig()
        self._runner = runner or self._run_command
        self.last_probe: MaituPageProbe | None = None

    def ensure_ready(self, *, maitu_project_code: str | None, scene_name: str | None) -> None:
        probe = self.probe_current_page(open_if_needed=True)
        if probe.login_required:
            raise MaituBrowserExecutionError(
                f"Maitu login page is visible at {probe.url}; browser-use worker cannot continue safely.",
                retryable=False,
                retry_instruction="请先在可见 Chrome 窗口人工登录麦兔，然后重新运行只读探测。",
            )
        if not probe.logged_in:
            raise MaituBrowserExecutionError(
                f"Maitu dashboard was not detected. Current page: {probe.title} {probe.url}",
                retryable=True,
                retry_instruction="Open Maitu home in browser-use and verify network/login state before retrying.",
            )

    def recover_login(self) -> None:
        probe = self.probe_current_page(open_if_needed=True)
        if probe.login_required:
            raise MaituBrowserExecutionError(
                "Maitu login recovery requires manual operator action in the visible browser.",
                retryable=False,
                retry_instruction="请在 browser-use 打开的 Chrome 中人工完成麦兔登录，再重试 worker。",
            )

    def upload_asset(self, asset: dict[str, Any]) -> None:
        self._raise_read_only("upload_asset")

    def replace_layer_asset(self, operation: dict[str, Any], asset: dict[str, Any]) -> None:
        self._raise_read_only("replace_layer_asset")

    def save_project(self) -> None:
        self._raise_read_only("save_project")

    def capture_screenshot(self, *, label: str) -> str | None:
        return None

    def execute_generic_operation(self, operation: dict[str, Any], asset: dict[str, Any] | None) -> None:
        self._raise_read_only(str(operation.get("operation_type") or "execute_generic_operation"))

    def probe_current_page(self, *, open_if_needed: bool = True) -> MaituPageProbe:
        summary = self.read_page_summary()
        probe = self._probe_from_summary(summary)
        if open_if_needed and not self._is_maitu_url(probe.url):
            self.open_home()
            summary = self.read_page_summary()
            probe = self._probe_from_summary(summary)
            probe.opened_home = True
        self.last_probe = probe
        return probe

    def read_page_summary(self) -> dict[str, str]:
        state_output = self._call_browser_use(["state"])
        parsed = self._parse_json_object(state_output)
        if parsed is not None:
            return {
                "title": str(parsed.get("title") or ""),
                "href": str(parsed.get("href") or parsed.get("url") or ""),
                "text": str(parsed.get("text") or parsed.get("bodyText") or ""),
            }
        summary = self._summary_from_state_text(state_output)
        if not summary.get("href"):
            eval_output = self._call_browser_use(["eval", self.PAGE_SUMMARY_SCRIPT])
            parsed_eval = self._parse_json_object(eval_output)
            if parsed_eval is not None:
                return {
                    "title": str(parsed_eval.get("title") or ""),
                    "href": str(parsed_eval.get("href") or parsed_eval.get("url") or ""),
                    "text": str(parsed_eval.get("text") or parsed_eval.get("bodyText") or ""),
                }
        return summary

    def open_home(self) -> None:
        args = ["open", self.config.home_url]
        if self.config.headed:
            args = ["--headed", *args]
        try:
            self._call_browser_use(args)
        except MaituBrowserExecutionError as exc:
            if self.config.headed and "different config" in str(exc):
                self._call_browser_use(["open", self.config.home_url])
                return
            raise

    def _probe_from_summary(self, summary: dict[str, str]) -> MaituPageProbe:
        title = summary.get("title", "")
        url = summary.get("href", "")
        text = summary.get("text", "")
        login_required = self._looks_like_login(url, text)
        logged_in = self._looks_like_logged_in(title, url, text) and not login_required
        return MaituPageProbe(title=title, url=url, text=text, logged_in=logged_in, login_required=login_required)

    def _call_browser_use(self, args: Sequence[str]) -> str:
        command = ("uv", "run", "browser-use", *args)
        try:
            return self._runner(command, cwd=self.config.browser_use_repo, timeout_seconds=self.config.timeout_seconds)  # type: ignore[misc]
        except TypeError:
            return self._runner(command)  # type: ignore[misc]

    def _run_command(self, args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        env = self._subprocess_env(cwd)
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise MaituBrowserExecutionError(
                f"browser-use CLI command failed with exit code {completed.returncode}: {output.strip()}",
                retryable=True,
                retry_instruction="Verify D:/browser-use, uv, and the browser-use session before retrying.",
            )
        return output

    @staticmethod
    def _subprocess_env(cwd: str | None) -> dict[str, str]:
        env = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(key, None)
        if cwd:
            env.setdefault("UV_PROJECT_ENVIRONMENT", os.path.join(cwd, ".venv"))
        return env

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        if not stripped:
            return None
        candidates = [stripped]
        first = stripped.find("{")
        last = stripped.rfind("}")
        if first >= 0 and last > first:
            candidates.append(stripped[first : last + 1])
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    @staticmethod
    def _summary_from_state_text(text: str) -> dict[str, str]:
        title = ""
        href = ""
        body_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            lower = line.lower()
            if lower.startswith("title:"):
                title = line.split(":", 1)[1].strip()
                continue
            if lower.startswith("url:") or lower.startswith("href:"):
                href = line.split(":", 1)[1].strip()
                continue
            if line:
                body_lines.append(line)
        return {"title": title, "href": href, "text": "\n".join(body_lines)}

    @staticmethod
    def _is_maitu_url(url: str) -> bool:
        return "maituai.com" in url.lower()

    @staticmethod
    def _looks_like_login(url: str, text: str) -> bool:
        lowered_url = url.lower()
        compact_text = text.replace(" ", "")
        if "login" in lowered_url:
            return True
        return "登录" in compact_text and ("密码" in compact_text or "手机号" in compact_text or "验证码" in compact_text)

    @staticmethod
    def _looks_like_logged_in(title: str, url: str, text: str) -> bool:
        combined = "\n".join([title, url, text])
        return "maituai.com" in url.lower() and any(
            marker in combined
            for marker in (
                "MyTwins",
                "麦兔",
                "首页",
                "数字分身",
                "素材管理",
                "直播间",
                "商品库",
            )
        )

    @staticmethod
    def _raise_read_only(operation_name: str) -> None:
        raise MaituBrowserExecutionError(
            f"BrowserUseCliSession is read-only; refusing to run mutating operation: {operation_name}",
            retryable=False,
            retry_instruction="当前只读探测会话不会上传、替换或保存；等页面结构探测稳定后再启用真实执行器。",
        )
