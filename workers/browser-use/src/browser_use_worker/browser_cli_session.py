from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MethodType
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .jd_metrics import JdLiveDashboardParser, JdLiveDashboardState
from .maitu_executor import MaituBrowserExecutionError

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


@dataclass(slots=True)
class MaituSceneState:
    name: str
    scene_type: str | None = None
    active: bool = False
    status: str | None = None


@dataclass(slots=True)
class MaituLayerState:
    name: str
    active: bool = False


@dataclass(slots=True)
class MaituTabState:
    name: str
    active: bool = False


@dataclass(slots=True)
class MaituCurrentState:
    title: str
    url: str
    text: str
    live_room_id: str | None = None
    live_room_name: str | None = None
    platform: str | None = None
    logged_in: bool = False
    login_required: bool = False
    scenes: list[MaituSceneState] | None = None
    active_scene_name: str | None = None
    layers: list[MaituLayerState] | None = None
    material_tabs: list[MaituTabState] | None = None
    active_material_tab: str | None = None
    workbench_tabs: list[MaituTabState] | None = None
    active_workbench_tab: str | None = None
    script_texts: list[str] | None = None


class BrowserUseCliSession:
    """Visible Maitu session backed by the local browser-use CLI.

    Read/probe operations remain non-destructive. Mutating methods are narrowly
    scoped to safe draft editing and Stage 5D regular image/video upload; final
    save/go-live controls are never clicked by this session.
    """

    __slots__ = ("config", "_runner", "_execution_guard", "last_probe")

    PAGE_SUMMARY_SCRIPT = "(() => JSON.stringify({title:document.title,href:location.href,text:document.body?.innerText||''}))()"
    IMAGE_UPLOAD_LAYER_TYPES = {
        "background_image",
        "product_image",
        "promotion_sticker",
        "brand_logo_title",
    }
    VISUAL_UPLOAD_LAYER_TYPES = {"supporting_visual"}
    VIDEO_UPLOAD_LAYER_TYPES = {"product_video"}
    CURRENT_STATE_SCRIPT = r"""
(() => {
  const rect = (el) => { const r = el.getBoundingClientRect(); return {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}; };
  const textOf = (el) => (el.innerText || el.textContent || '').trim();
  const pickDivs = (needle) => [...document.querySelectorAll('div')]
    .map((el, i) => ({i, className:String(el.className), text:textOf(el), active:String(el.className).includes('Active'), rect:rect(el)}))
    .filter((item) => item.className.includes(needle) && item.text);
  return JSON.stringify({
    title: document.title,
    href: location.href,
    text: document.body?.innerText || '',
    scenes: [...document.querySelectorAll('[role=button]')]
      .map((el, i) => ({i, className:String(el.className), text:textOf(el), active:String(el.className).includes('Active'), rect:rect(el)}))
      .filter((item) => /场景\s*\d+/.test(item.text)),
    layers: pickDivs('layerBox'),
    materialTabs: pickDivs('Fitment__tabItem'),
    workbenchTabs: pickDivs('Workbench__tabItem'),
    textareas: [...document.querySelectorAll('textarea')]
      .map((el, i) => ({i, placeholder:el.placeholder || '', value:el.value || '', maxlength:el.maxLength, rect:rect(el)})),
  });
})()
""".strip()

    def __init__(
        self,
        config: BrowserUseCliSessionConfig | None = None,
        *,
        runner: Callable[[Sequence[str]], str] | Callable[..., str] | None = None,
    ) -> None:
        self.config = config or BrowserUseCliSessionConfig()
        # Bind the import-time trusted function directly. Resolving
        # ``self._run_command`` here would execute a class descriptor replaced
        # before construction, earlier than the Worker's pre-claim trust gate.
        self._runner = (
            runner
            if runner is not None
            else MethodType(_TRUSTED_BROWSER_USE_CLI_SESSION_RUN_COMMAND, self)
        )
        self._execution_guard: Callable[[], bool] | None = None
        self.last_probe: MaituPageProbe | None = None

    def set_execution_guard(self, guard: Callable[[], bool] | None) -> None:
        self._execution_guard = guard

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

    def read_current_state(self, *, open_if_needed: bool = True) -> MaituCurrentState:
        if open_if_needed:
            self.probe_current_page(open_if_needed=True)
        output = self._call_browser_use(["eval", self.CURRENT_STATE_SCRIPT])
        raw = self._parse_json_object(output) or {}
        return self._current_state_from_payload(raw)

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
        self.open_url(self.config.home_url)

    def open_url(self, url: str) -> None:
        args = ["open", url]
        if self.config.headed:
            args = ["--headed", *args]
        try:
            self._call_browser_use(args)
        except MaituBrowserExecutionError as exc:
            if self.config.headed and "different config" in str(exc):
                self._call_browser_use(["open", url])
                return
            raise

    def read_jd_live_dashboard_state(self, *, open_url: str | None = None) -> JdLiveDashboardState:
        if open_url:
            self.open_url(open_url)
        summary = self.read_page_summary()
        return JdLiveDashboardParser().parse_state(
            title=summary.get("title", ""),
            url=summary.get("href", ""),
            text=summary.get("text", ""),
        )

    def list_maitu_materials(self) -> list[dict[str, Any]]:
        script = """
(() => {
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  const pageItems = (r, path) => {
    const value = unwrap(r);
    if (Array.isArray(value)) return value;
    if (value && Array.isArray(value.items)) return value.items;
    throw new Error('Unexpected inventory response schema for ' + path);
  };
  function xhr(path) {
    const x = new XMLHttpRequest();
    x.open('GET', 'https://api.maituai.com/' + path, false);
    if (token) x.setRequestHeader('Authorization', token);
    x.send(null);
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!(x.status >= 200 && x.status < 300)) throw new Error('GET ' + path + ' failed ' + x.status);
    return data;
  }
  function allPages(basePath) {
    const result = [];
    const limit = 100;
    for (let page = 0; page < 100; page += 1) {
      const path = basePath + '&offset=' + (page * limit) + '&limit=' + limit;
      const batch = pageItems(xhr(path), path);
      result.push(...batch);
      if (batch.length < limit) return result;
    }
    throw new Error('Maitu inventory pagination exceeded safety limit for ' + basePath);
  }
  const materials = allPages('materials?is_pub=false');
  const digitalHumans = allPages('materials/digital_human?access_rule=private');
  return JSON.stringify({materials, digital_humans: digitalHumans});
})()
""".strip()
        payload = self._eval_json(script)
        materials = self._validated_material_inventory(payload.get("materials"), collection_name="materials")
        digital_humans = self._validated_material_inventory(
            payload.get("digital_humans"),
            collection_name="digital_humans",
        )
        return [*materials, *digital_humans]

    def upload_maitu_material(
        self,
        *,
        asset: dict[str, Any],
        local_path: Path,
        layer_type: str | None,
    ) -> dict[str, Any]:
        path = Path(local_path)
        suffix = path.suffix.lower()
        planned_layer_type = str(layer_type or "").strip().lower()
        planned_kind = (
            "video"
            if planned_layer_type in self.VIDEO_UPLOAD_LAYER_TYPES
            else "image"
            if planned_layer_type in self.IMAGE_UPLOAD_LAYER_TYPES
            else "visual"
            if planned_layer_type in self.VISUAL_UPLOAD_LAYER_TYPES
            else None
        )
        suffix_kind = (
            "video"
            if suffix in {".mp4", ".mov", ".m4v", ".avi"}
            else "image"
            if suffix in {".png", ".jpg", ".jpeg", ".gif"}
            else None
        )
        if planned_kind == "visual":
            planned_kind = suffix_kind
        if not path.is_file():
            raise MaituBrowserExecutionError(
                f"Local asset file does not exist: {path}",
                retryable=False,
                retry_instruction="Verify AssetGraph local_relative_path before retrying Maitu upload.",
            )
        if planned_kind is None or suffix_kind is None or planned_kind != suffix_kind:
            raise MaituBrowserExecutionError(
                f"Maitu upload type mismatch: layer_type={layer_type!r}, file_suffix={suffix!r}",
                retryable=False,
                retry_instruction="Use a supported layer type and a local file whose extension matches the planned image/video kind.",
            )
        is_video = planned_kind == "video"
        is_image = planned_kind == "image"
        expected_file_key = self._normalize_material_name(path.name)
        if not expected_file_key:
            raise MaituBrowserExecutionError(
                f"Maitu upload filename has no stable match key: {path.name!r}",
                retryable=False,
                retry_instruction="Rename the local file to include letters, digits, or CJK characters before retrying upload.",
            )
        expected_suffix_pattern = re.compile(re.escape(expected_file_key) + r"\d{3,4}$")

        self.open_url("https://live2.maituai.com/MaterialManage")
        self._wait_for_material_manage()
        if is_video:
            target_tab = "视频"
        elif "background" in str(layer_type or "").lower():
            target_tab = "背景"
        else:
            target_tab = "装饰"
        self._click_existing_text_target(
            target=target_tab,
            selectors=('div', 'button'),
            action_name="select_material_upload_tab",
        )
        self._verify_material_upload_target(target_tab=target_tab, kind="video" if is_video else "image")
        state_output = self._call_browser_use(["state"])
        input_indices = self._file_input_indices(state_output, kind="video" if is_video else "image")
        if len(input_indices) != 1:
            raise MaituBrowserExecutionError(
                f"Maitu {target_tab} page exposed {len(input_indices)} matching file inputs; refusing an ambiguous upload target.",
                retryable=True,
                retry_instruction="Re-open 素材管理 and verify exactly one visible upload control before retrying.",
            )
        input_index = input_indices[0]
        before_materials = self.list_maitu_materials()
        before_material_ids: set[int] = set()
        for material in before_materials:
            material_id = material.get("id")
            try:
                if material_id is not None:
                    before_material_ids.add(int(material_id))
            except (TypeError, ValueError) as exc:
                raise MaituBrowserExecutionError(
                    f"Maitu inventory returned a non-numeric material id: {material_id!r}",
                    retryable=True,
                    retry_instruction="Refresh the complete material inventory before retrying upload.",
                ) from exc
        self._verify_material_upload_target(target_tab=target_tab, kind="video" if is_video else "image")
        self._call_browser_use(["upload", str(input_index), str(path)])

        for _attempt in range(10):
            time.sleep(2)
            materials = self.list_maitu_materials()
            candidates: list[dict[str, Any]] = []
            for material in materials:
                material_id = material.get("id")
                try:
                    numeric_id = int(material_id)
                except (TypeError, ValueError):
                    continue
                if numeric_id in before_material_ids:
                    continue
                material_type = str(material.get("type") or "").lower()
                if is_video and material_type not in {"video", "decorative_video"}:
                    continue
                if is_image and material_type != "image":
                    continue
                material_keys = {
                    self._normalize_material_name(material.get("name")),
                    self._normalize_material_name(self._url_basename(material.get("url"))),
                }
                if any(key and (key == expected_file_key or expected_suffix_pattern.fullmatch(key)) for key in material_keys):
                    candidates.append(material)
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                raise MaituBrowserExecutionError(
                    f"Maitu upload readback is ambiguous for {path.name}: {len(candidates)} new records matched.",
                    retryable=False,
                    retry_instruction="Review the newly created Maitu records and bind the intended material manually.",
                )
        raise MaituBrowserExecutionError(
            f"Maitu upload completed but no material record was found for {path.name}.",
            retryable=True,
            retry_instruction="Check 素材管理 processing state and retry resolution after the material appears.",
        )

    def _wait_for_material_manage(self) -> None:
        script = """
(() => {
  const text = document.body?.innerText || '';
  const ready = location.origin === 'https://live2.maituai.com'
    && location.pathname === '/MaterialManage'
    && text.includes('素材管理')
    && text.includes('背景')
    && text.includes('装饰')
    && text.includes('视频');
  return JSON.stringify({ready, href: location.href});
})()
""".strip()
        last_result: dict[str, Any] = {}
        for _attempt in range(5):
            last_result = self._parse_json_object(self._call_browser_use(["eval", script])) or {}
            if last_result.get("ready"):
                return
            time.sleep(0.5)
        raise MaituBrowserExecutionError(
            f"Maitu MaterialManage did not become ready: {last_result.get('href') or 'unknown page'}",
            retryable=True,
            retry_instruction="Wait for 素材管理 to finish loading in the visible browser and retry.",
        )

    def _verify_material_upload_target(self, *, target_tab: str, kind: str) -> None:
        args = json.dumps({"targetTab": target_tab, "kind": kind}, ensure_ascii=False)
        script = """
(() => {
  const args = __ARGS__;
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const tabs = [...document.querySelectorAll('div[class*=MaterialManage__tabBox]')]
    .filter(visible)
    .filter((el) => (el.innerText || el.textContent || '').trim() === args.targetTab);
  const activeTabs = tabs.filter((el) => String(el.className).includes('active'));
  const kindInputs = [...document.querySelectorAll('input[type=file]')].filter((el) => {
    const accept = String(el.accept || '').toLowerCase();
    return args.kind === 'video' ? accept.includes('video/') : accept.includes('image/');
  });
  const inputs = kindInputs.filter((el) => Boolean(el.closest('div[class*=MaterialManage__container]')));
  return JSON.stringify({
    verified: location.origin === 'https://live2.maituai.com'
      && location.pathname === '/MaterialManage'
      && tabs.length === 1
      && activeTabs.length === 1
      && kindInputs.length === 1
      && inputs.length === 1,
    href: location.href,
    tab_count: tabs.length,
    active_tab_count: activeTabs.length,
    kind_input_count: kindInputs.length,
    input_count: inputs.length,
  });
})()
""".strip().replace("__ARGS__", args)
        result = self._parse_json_object(self._call_browser_use(["eval", script])) or {}
        if not result.get("verified"):
            raise MaituBrowserExecutionError(
                f"Maitu upload target verification failed: {result}",
                retryable=True,
                retry_instruction="Verify the exact live2.maituai.com MaterialManage origin, active tab, and unique upload input.",
            )

    @staticmethod
    def _file_input_indices(state_output: str, *, kind: str) -> list[int]:
        indices: list[int] = []
        for match in re.finditer(r"\[(\d+)\]<input\b([^>]*)>", state_output):
            attributes = match.group(2).lower()
            if "type=file" not in attributes:
                continue
            accepts_video = "video/" in attributes
            accepts_image = "image/" in attributes
            if (kind == "video" and accepts_video) or (kind == "image" and accepts_image):
                indices.append(int(match.group(1)))
        return indices

    @staticmethod
    def _url_basename(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return Path(unquote(urlparse(text).path)).name

    @staticmethod
    def _normalize_material_name(value: Any) -> str:
        text = unquote(str(value or "")).strip().lower()
        text = Path(text).name
        text = re.sub(r"\.(?:png|jpe?g|gif|webp|mp4|mov|m4v|avi)$", "", text, flags=re.IGNORECASE)
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)

    def read_live_room(self, live_room_id: str) -> dict[str, Any]:
        args = {
            "liveRoomId": str(live_room_id),
            "roomPath": f"live_rooms/{live_room_id}?env=working&include_qa_clips=true",
        }
        script = """
(() => {
  const args = __ARGS__;
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  function xhr(method, path, body) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status);
    return data;
  }
  const room = unwrap(xhr('GET', args.roomPath));
  if (!room || typeof room !== 'object' || Array.isArray(room)) throw new Error('working live room response is not an object');
  return JSON.stringify({...room, _assetgraph_read_environment:'working'});
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def rename_clip(self, clip_id: int, name: str) -> dict[str, Any]:
        args = {"clipId": int(clip_id), "name": name, "clipPath": f"clips/{int(clip_id)}"}
        script = """
(() => {
  const args = __ARGS__;
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  function xhr(method, path, body) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status);
    return data;
  }
  const roomId = new URLSearchParams(location.search).get('liveRoomId');
  let clip = {id: args.clipId};
  if (roomId) {
    const room = unwrap(xhr('GET', 'live_rooms/' + roomId + '?env=working&include_qa_clips=true'));
    const clips = ((room.topics || [])[0] || {}).clips || [];
    clip = clips.find((item) => String(item.id) === String(args.clipId)) || clip;
  }
  const payload = {...clip, name: args.name};
  delete payload.clip_materials;
  const response = unwrap(xhr('PUT', args.clipPath, payload));
  return JSON.stringify({clip_id: args.clipId, name: args.name, response});
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def fill_clip_from_template(
        self,
        *,
        live_room_id: str,
        target_clip_id: int,
        reference_room_id: str,
        reference_clip_id: str,
        scene_name: str,
        component_operations: list[dict[str, Any]],
        script_content: str | None,
    ) -> dict[str, Any]:
        args = {
            "liveRoomId": str(live_room_id),
            "targetClipId": int(target_clip_id),
            "referenceRoomId": str(reference_room_id),
            "referenceClipId": str(reference_clip_id),
            "sceneName": scene_name,
            "componentOperations": component_operations,
            "scriptContent": script_content,
        }
        script = """
(() => {
  const args = __ARGS__;
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  const arr = (x) => Array.isArray(x) ? x : [];
  function xhr(method, path, body, allowFail=false) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!allowFail && !(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status);
    return {status:x.status, ok:x.status >= 200 && x.status < 300, data};
  }
  function visualPayload(m, clipId) {
    const sf = {...(m.style_front || {})};
    if (sf.top == null && m.top != null) sf.top = m.top;
    if (sf.left == null && m.left != null) sf.left = m.left;
    return {
      url: m.url || null,
      type: m.type,
      layer_n: m.layer_n,
      width: m.width,
      height: m.height,
      left: m.left || 0,
      top: m.top || 0,
      clip_id: clipId,
      digital_human_image_id: m.digital_human_image_id || null,
      speaker_id: m.speaker_id || null,
      name: m.name || null,
      tags: m.tags || null,
      cover_url: m.cover_url || m.url || null,
      dhi_clip: m.dhi_clip || null,
      material_id: m.material_id || null,
      style_front: JSON.stringify(sf),
      duration: m.duration || null,
      sound_enabled: m.sound_enabled,
      play_mode: m.play_mode || null,
      scale: m.scale || null,
    };
  }
  const refRoom = unwrap(xhr('GET', 'live_rooms/' + args.referenceRoomId + '?env=working&include_qa_clips=true').data);
  const refClips = arr(((refRoom.topics || [])[0] || {}).clips);
  const refClip = refClips.find((clip) => String(clip.id) === String(args.referenceClipId));
  if (!refClip) throw new Error('reference clip not found: ' + args.referenceClipId);
  const visualMaterials = arr(refClip.clip_materials).filter((m) => m.type !== 'text' && m.type !== 'audio');
  const count = args.componentOperations.length;
  const selectedVisuals = visualMaterials.slice(0, count).map((m) => visualPayload(m, args.targetClipId));
  const cumulative = [];
  for (let i = 0; i < selectedVisuals.length; i += 1) {
    cumulative.push(selectedVisuals[i]);
    xhr('POST', 'clips/' + args.targetClipId + '/replace_clip_materials', {view_clip_materials: cumulative});
  }
  const targetBeforeText = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const targetClipBeforeText = arr(((targetBeforeText.topics || [])[0] || {}).clips).find((clip) => String(clip.id) === String(args.targetClipId));
  const existingTexts = arr(targetClipBeforeText && targetClipBeforeText.clip_materials).filter((material) => material.type === 'text');
  let textMaterial = null;
  if (args.scriptContent) {
    if (existingTexts.length > 0) {
      const primary = existingTexts[0];
      textMaterial = unwrap(xhr('PUT', 'clip_materials/' + primary.id, {...primary, content:args.scriptContent, clip_id:args.targetClipId}).data);
      for (const duplicate of existingTexts.slice(1)) {
        xhr('DELETE', 'clip_materials/' + duplicate.id, {});
      }
    } else {
      textMaterial = unwrap(xhr('POST', 'clip_materials', {type:'text', clip_id:args.targetClipId, content:args.scriptContent, order_num:0}).data);
    }
  } else {
    for (const existingText of existingTexts) {
      xhr('DELETE', 'clip_materials/' + existingText.id, {});
    }
  }
  const verifiedRoom = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const verifiedClip = arr(((verifiedRoom.topics || [])[0] || {}).clips).find((clip) => String(clip.id) === String(args.targetClipId)) || {};
  const materials = arr(verifiedClip.clip_materials);
  const visuals = materials.filter((m) => m.type !== 'text' && m.type !== 'audio');
  const texts = materials.filter((m) => m.type === 'text');
  const matchingTexts = texts.filter((m) => m.content === args.scriptContent);
  if (args.scriptContent && (texts.length !== 1 || matchingTexts.length !== 1)) {
    throw new Error('template script write readback was not unique and authoritative');
  }
  if (!args.scriptContent && texts.length !== 0) {
    throw new Error('template script clear readback still contains text materials');
  }
  return JSON.stringify({
    live_room_id: args.liveRoomId,
    target_clip_id: args.targetClipId,
    target_clip_name: verifiedClip.name || args.sceneName,
    reference_clip_id: args.referenceClipId,
    visual_count: visuals.length,
    text_count: texts.length,
    layer_names: visuals.map((m) => m.name || ''),
    text_material_id: (textMaterial && textMaterial.id) || (matchingTexts[0] && matchingTexts[0].id),
    script_content_verified: true,
    go_live_clicked: false,
  });
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def create_scene(self, *, live_room_id: str, scene_name: str, scene_index: int) -> dict[str, Any]:
        args = {"liveRoomId": str(live_room_id), "sceneName": scene_name, "sceneIndex": int(scene_index)}
        script = """
(() => {
  const args = __ARGS__;
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  const arr = (x) => Array.isArray(x) ? x : [];
  function xhr(method, path, body, allowFail=false) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!allowFail && !(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status + ': ' + x.responseText);
    return {status:x.status, ok:x.status >= 200 && x.status < 300, data};
  }
  const room = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const topic = arr(room.topics)[0] || {};
  const clips = arr(topic.clips);
  const template = clips[0] || {};
  const payload = {...template, name: args.sceneName, order_num: args.sceneIndex, live_room_id: Number(args.liveRoomId), topic_id: topic.id || template.topic_id};
  delete payload.id;
  delete payload.clip_materials;
  delete payload.created_at;
  delete payload.updated_at;
  const created = unwrap(xhr('POST', 'clips', payload).data);
  const verifyRoom = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const verifyClips = arr((arr(verifyRoom.topics)[0] || {}).clips);
  const matched = verifyClips.find((clip) => String(clip.id) === String(created && created.id))
    || verifyClips.find((clip) => clip.name === args.sceneName && Number(clip.order_num || 0) === args.sceneIndex)
    || created;
  return JSON.stringify({
    status: 'created',
    live_room_id: args.liveRoomId,
    clip_id: matched && matched.id,
    name: matched && matched.name || args.sceneName,
    order_num: matched && matched.order_num,
    response: created,
    go_live_clicked: false,
  });
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    @classmethod
    def _resolved_operation_material_type(cls, operation: dict[str, Any]) -> str | None:
        layer_type = str(operation.get("layer_type") or "").strip().lower()
        source_type = str(operation.get("source_material_type") or "").strip().lower()
        if layer_type in cls.IMAGE_UPLOAD_LAYER_TYPES:
            return "image" if source_type == "image" else None
        if layer_type in cls.VIDEO_UPLOAD_LAYER_TYPES:
            return "video" if source_type in {"video", "decorative_video"} else None
        if layer_type in cls.VISUAL_UPLOAD_LAYER_TYPES:
            if source_type == "image":
                return "image"
            if source_type in {"video", "decorative_video"}:
                return "video"
            return None
        if layer_type == "digital_human":
            return "digital_human" if source_type == "digital_human" else None
        return None

    def insert_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        material_type = self._resolved_operation_material_type(operation)
        if material_type is None:
            raise MaituBrowserExecutionError(
                "Resolved Maitu binding type is incompatible with the planned layer type.",
                retryable=False,
                retry_instruction="Re-run Stage 5D material resolution and do not execute a wrong-type asset binding.",
            )
        args = {
            "liveRoomId": str(live_room_id),
            "clipId": int(clip_id),
            "materialType": material_type,
            "operation": operation,
        }
        script = """
(() => {
  const args = __ARGS__;
  const op = args.operation || {};
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  function xhr(method, path, body, allowFail=false) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!allowFail && !(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status + ': ' + x.responseText);
    return {status:x.status, ok:x.status >= 200 && x.status < 300, data};
  }
  const sourceUrl = op.source_material_url || op.asset_url || op.url || null;
  const coverUrl = op.source_cover_url || op.cover_url || sourceUrl || null;
  const materialId = op.material_id || op.maitu_material_id || null;
  const digitalHumanImageId = op.digital_human_image_id || null;
  const speakerId = op.speaker_id || null;
  const materialType = args.materialType;
  const bindingComplete = materialType === 'digital_human'
    ? Boolean(digitalHumanImageId && speakerId)
    : Boolean(sourceUrl && materialId);
  if (!bindingComplete) {
    return JSON.stringify({
      status: 'manual_required',
      reason: 'missing_maitu_material_binding',
      asset_code: op.asset_code || null,
      asset_display_code: op.asset_display_code || null,
      asset_local_file_code: op.asset_local_file_code || null,
      asset_local_relative_path: op.asset_local_relative_path || null,
      go_live_clicked: false,
    });
  }
  const style = {left: op.x || 0, top: op.y || 0, width: op.width || null, height: op.height || null, zIndex: op.z_index || 1, fit: op.fit || 'contain'};
  const payload = {
    type: materialType,
    clip_id: args.clipId,
    name: op.layer_id || op.layer_type || op.asset_display_code || op.asset_code || 'script_asset_layer',
    url: sourceUrl,
    cover_url: coverUrl,
    material_id: materialId,
    digital_human_image_id: digitalHumanImageId,
    speaker_id: speakerId,
    width: op.width || null,
    height: op.height || null,
    left: op.x || 0,
    top: op.y || 0,
    layer_n: op.z_index || 1,
    style_front: JSON.stringify(style),
  };
  const created = unwrap(xhr('POST', 'clip_materials', payload).data);
  return JSON.stringify({
    status: 'inserted',
    live_room_id: args.liveRoomId,
    clip_id: args.clipId,
    layer_id: op.layer_id || null,
    asset_code: op.asset_code || null,
    material_id: created && created.id,
    response: created,
    go_live_clicked: false,
  });
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def position_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        args = {"liveRoomId": str(live_room_id), "clipId": int(clip_id), "operation": operation}
        script = """
(() => {
  const args = __ARGS__;
  const op = args.operation || {};
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  const arr = (x) => Array.isArray(x) ? x : [];
  function xhr(method, path, body, allowFail=false) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!allowFail && !(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status + ': ' + x.responseText);
    return {status:x.status, ok:x.status >= 200 && x.status < 300, data};
  }
  const room = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const clips = arr((arr(room.topics)[0] || {}).clips);
  const clip = clips.find((item) => String(item.id) === String(args.clipId)) || {};
  const materials = arr(clip.clip_materials);
  const material = materials.find((item) => String(item.id) === String(op.material_id || op.maitu_material_id || ''))
    || materials.find((item) => item.name === op.layer_id || item.name === op.layer_type)
    || materials.find((item) => item.asset_code && item.asset_code === op.asset_code);
  if (!material || !material.id) {
    return JSON.stringify({status:'manual_required', reason:'target_material_not_found', layer_id:op.layer_id || null, asset_code:op.asset_code || null, go_live_clicked:false});
  }
  const style = {...(typeof material.style_front === 'string' ? JSON.parse(material.style_front || '{}') : (material.style_front || {}))};
  style.left = op.x || 0;
  style.top = op.y || 0;
  style.width = op.width || material.width || null;
  style.height = op.height || material.height || null;
  style.zIndex = op.z_index || material.layer_n || 1;
  const payload = {...material, left: style.left, top: style.top, width: style.width, height: style.height, layer_n: style.zIndex, style_front: JSON.stringify(style)};
  const updated = unwrap(xhr('PUT', 'clip_materials/' + material.id, payload).data);
  return JSON.stringify({status:'positioned', clip_id:args.clipId, material_id:material.id, layer_id:op.layer_id || null, response:updated, go_live_clicked:false});
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def write_script(self, *, live_room_id: str, clip_id: int, scene_name: str, script_text: str) -> dict[str, Any]:
        args = {"liveRoomId": str(live_room_id), "clipId": int(clip_id), "sceneName": scene_name, "scriptText": script_text}
        script = """
(() => {
  const args = __ARGS__;
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  const arr = (x) => Array.isArray(x) ? x : [];
  function xhr(method, path, body, allowFail=false) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!allowFail && !(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status + ': ' + x.responseText);
    return {status:x.status, ok:x.status >= 200 && x.status < 300, data};
  }
  const room = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const clips = arr((arr(room.topics)[0] || {}).clips);
  const clip = clips.find((item) => String(item.id) === String(args.clipId)) || {};
  const existingTexts = arr(clip.clip_materials).filter((material) => material.type === 'text');
  let textMaterial = null;
  if (existingTexts.length > 0) {
    const primary = existingTexts[0];
    textMaterial = unwrap(xhr('PUT', 'clip_materials/' + primary.id, {...primary, content:args.scriptText, clip_id:args.clipId}).data);
    for (const duplicate of existingTexts.slice(1)) {
      xhr('DELETE', 'clip_materials/' + duplicate.id, {});
    }
  } else {
    textMaterial = unwrap(xhr('POST', 'clip_materials', {type:'text', clip_id:args.clipId, content:args.scriptText, order_num:0}).data);
  }
  const verifyRoom = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const verifyClip = arr((arr(verifyRoom.topics)[0] || {}).clips).find((item) => String(item.id) === String(args.clipId)) || {};
  const verifiedTexts = arr(verifyClip.clip_materials).filter((material) => material.type === 'text');
  if (verifiedTexts.length !== 1 || verifiedTexts[0].content !== args.scriptText) {
    throw new Error('script write readback was not unique and authoritative');
  }
  return JSON.stringify({status:'written', live_room_id:args.liveRoomId, clip_id:args.clipId, scene_name:args.sceneName, text_material_id:(textMaterial && textMaterial.id) || verifiedTexts[0].id, script_length:(args.scriptText || '').length, script_content_verified:true, go_live_clicked:false});
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def verify_scene(self, *, live_room_id: str, clip_id: int, scene_name: str, operation: dict[str, Any]) -> dict[str, Any]:
        args = {"liveRoomId": str(live_room_id), "clipId": int(clip_id), "sceneName": scene_name, "operation": operation}
        script = """
(() => {
  const args = __ARGS__;
  const token = (localStorage.getItem('token') || '').trim();
  if (location.origin !== 'https://live2.maituai.com') throw new Error('unexpected Maitu origin: ' + location.origin);
  if (!token) throw new Error('missing authenticated Maitu token');
  const unwrap = (r) => (r && typeof r === 'object' && r.success === true && 'data' in r) ? r.data : r;
  const arr = (x) => Array.isArray(x) ? x : [];
  function xhr(method, path, body) {
    const x = new XMLHttpRequest();
    x.open(method, 'https://api.maituai.com/' + path, false);
    x.setRequestHeader('Content-Type', 'application/json');
    if (token) x.setRequestHeader('Authorization', token);
    x.send(body === undefined ? null : JSON.stringify(body));
    let data = null;
    try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = {raw:x.responseText}; }
    if (!(x.status >= 200 && x.status < 300)) throw new Error(method + ' ' + path + ' failed ' + x.status + ': ' + x.responseText);
    return {status:x.status, ok:x.status >= 200 && x.status < 300, data};
  }
  const room = unwrap(xhr('GET', 'live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true').data);
  const clips = arr((arr(room.topics)[0] || {}).clips);
  const clip = clips.find((item) => String(item.id) === String(args.clipId)) || {};
  const materials = arr(clip.clip_materials);
  const texts = materials.filter((m) => m.type === 'text');
  const visuals = materials.filter((m) => m.type !== 'text' && m.type !== 'audio');
  return JSON.stringify({status:'verified', live_room_id:args.liveRoomId, clip_id:args.clipId, scene_name:clip.name || args.sceneName, visual_count:visuals.length, text_count:texts.length, script_present:texts.length > 0, material_ids:materials.map((m) => m.id), go_live_clicked:false});
})()
""".strip().replace("__ARGS__", json.dumps(args, ensure_ascii=False))
        return self._eval_json(script)

    def select_scene(self, scene_name: str) -> dict[str, Any]:
        return self._click_existing_text_target(
            target=scene_name,
            selectors=("[role=button]", "button", "div"),
            action_name="select_scene",
        )

    def open_material_tab(self, tab_name: str) -> dict[str, Any]:
        return self._click_existing_text_target(
            target=tab_name,
            selectors=('div[class*="Fitment__tabItem"]', "button", "div"),
            action_name="open_material_tab",
        )

    def open_workbench_tab(self, tab_name: str) -> dict[str, Any]:
        return self._click_existing_text_target(
            target=tab_name,
            selectors=('div[class*="Workbench__tabItem"]', "button", "div"),
            action_name="open_workbench_tab",
        )

    def _click_existing_text_target(self, *, target: str, selectors: Sequence[str], action_name: str) -> dict[str, Any]:
        selector_js = json.dumps(",".join(selectors), ensure_ascii=False)
        target_js = json.dumps(target, ensure_ascii=False)
        script = f"""
(() => {{
  const target = {target_js};
  const selectors = {selector_js};
  const textOf = (el) => (el.innerText || el.textContent || '').trim();
  const isVisible = (el) => {{
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }};
  const candidates = [...document.querySelectorAll(selectors)]
    .filter(isVisible)
    .map((el, i) => {{
      const text = textOf(el);
      const firstLine = text.split(/\\n/).map((line) => line.trim()).find(Boolean) || '';
      return {{el, i, text, firstLine, className: String(el.className)}};
    }})
    .filter((item) => item.text);
  const match = candidates.find((item) => item.firstLine === target)
    || candidates.find((item) => item.text === target)
    || candidates.find((item) => item.text.includes(target));
  if (!match) {{
    return JSON.stringify({{clicked:false, reason:'target_not_found', target, candidate_count:candidates.length}});
  }}
  match.el.click();
  return JSON.stringify({{clicked:true, target, text:match.text, className:match.className}});
}})()
""".strip()
        result = self._parse_json_object(self._call_browser_use(["eval", script])) or {}
        if not result.get("clicked"):
            raise MaituBrowserExecutionError(
                f"Non-destructive Browser-use action {action_name} could not find target: {target}",
                retryable=False,
                retry_instruction="Re-observe the current Maitu page and confirm the target scene/tab text before retrying.",
            )
        return result

    def _current_state_from_payload(self, payload: dict[str, Any]) -> MaituCurrentState:
        title = str(payload.get("title") or "")
        url = str(payload.get("href") or payload.get("url") or "")
        text = str(payload.get("text") or payload.get("bodyText") or "")
        probe = self._probe_from_summary({"title": title, "href": url, "text": text})
        scenes = [self._scene_state_from_item(item) for item in self._list_payload(payload.get("scenes"))]
        layers = [self._layer_state_from_item(item) for item in self._list_payload(payload.get("layers"))]
        material_tabs = [self._tab_state_from_item(item) for item in self._list_payload(payload.get("materialTabs"))]
        workbench_tabs = [self._tab_state_from_item(item) for item in self._list_payload(payload.get("workbenchTabs"))]
        script_texts = [
            str(item.get("value") or "").strip()
            for item in self._list_payload(payload.get("textareas"))
            if str(item.get("value") or "").strip()
        ]
        return MaituCurrentState(
            title=title,
            url=url,
            text=text,
            live_room_id=self._extract_live_room_id(url, text),
            live_room_name=self._extract_live_room_name(text),
            platform=self._extract_platform(text),
            logged_in=probe.logged_in,
            login_required=probe.login_required,
            scenes=scenes,
            active_scene_name=next((scene.name for scene in scenes if scene.active), None),
            layers=layers,
            material_tabs=material_tabs,
            active_material_tab=next((tab.name for tab in material_tabs if tab.active), None),
            workbench_tabs=workbench_tabs,
            active_workbench_tab=next((tab.name for tab in workbench_tabs if tab.active), None),
            script_texts=script_texts,
        )

    @staticmethod
    def _validated_material_inventory(value: Any, *, collection_name: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise MaituBrowserExecutionError(
                f"Maitu inventory collection {collection_name!r} is not a list.",
                retryable=True,
                retry_instruction="Refresh 素材管理 and retry only after the complete inventory schema is available.",
            )
        records: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            material_id = item.get("id") if isinstance(item, dict) else None
            material_type = str(item.get("type") or "").strip() if isinstance(item, dict) else ""
            try:
                numeric_id = int(material_id)
                valid_id = not isinstance(material_id, bool) and numeric_id > 0 and str(material_id).strip() == str(numeric_id)
            except (TypeError, ValueError):
                valid_id = False
            if not isinstance(item, dict) or not valid_id or not material_type:
                raise MaituBrowserExecutionError(
                    f"Maitu inventory collection {collection_name!r} has an invalid record at index {index}.",
                    retryable=True,
                    retry_instruction="Refresh 素材管理 and retry only after every inventory record has a numeric id and type.",
                )
            records.append(item)
        return records

    @staticmethod
    def _list_payload(value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _scene_state_from_item(item: dict[str, Any]) -> MaituSceneState:
        lines = [line.strip() for line in str(item.get("text") or "").splitlines() if line.strip()]
        name = lines[0] if lines else ""
        status = next((line for line in lines[1:] if line in {"已激活", "未激活"}), None)
        scene_type = next((line for line in lines[1:] if line not in {"已激活", "未激活"}), None)
        return MaituSceneState(name=name, scene_type=scene_type, status=status, active=bool(item.get("active")))

    @staticmethod
    def _layer_state_from_item(item: dict[str, Any]) -> MaituLayerState:
        return MaituLayerState(name=str(item.get("text") or "").strip(), active=bool(item.get("active")))

    @staticmethod
    def _tab_state_from_item(item: dict[str, Any]) -> MaituTabState:
        return MaituTabState(name=str(item.get("text") or "").strip(), active=bool(item.get("active")))

    @staticmethod
    def _extract_live_room_id(url: str, text: str) -> str | None:
        url_match = re.search(r"liveRoomId=(\d+)", url)
        if url_match:
            return url_match.group(1)
        text_match = re.search(r"ID[:：]?\s*(\d+)", text)
        return text_match.group(1) if text_match else None

    @staticmethod
    def _extract_live_room_name(text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.startswith("(ID:") and index + 1 < len(lines):
                return lines[index + 1]
            if line.startswith("ID:") and index + 1 < len(lines):
                return lines[index + 1]
        return None

    @staticmethod
    def _extract_platform(text: str) -> str | None:
        for line in (line.strip() for line in text.splitlines()):
            if line.endswith("版") and line in {"京东版", "淘宝版", "抖音版", "视频号版"}:
                return line
        return None

    def _probe_from_summary(self, summary: dict[str, str]) -> MaituPageProbe:
        title = summary.get("title", "")
        url = summary.get("href", "")
        text = summary.get("text", "")
        login_required = self._looks_like_login(url, text)
        logged_in = self._looks_like_logged_in(title, url, text) and not login_required
        return MaituPageProbe(title=title, url=url, text=text, logged_in=logged_in, login_required=login_required)

    def _call_browser_use(self, args: Sequence[str]) -> str:
        if self._execution_guard is not None and not self._execution_guard():
            raise MaituBrowserExecutionError(
                "retry lease guard rejected browser command before execution",
                retryable=True,
                retry_instruction="Reclaim the retry task with a fresh lease before continuing.",
            )
        command = ("uv", "run", "browser-use", *args)
        try:
            return self._runner(command, cwd=self.config.browser_use_repo, timeout_seconds=self.config.timeout_seconds)  # type: ignore[misc]
        except TypeError:
            return self._runner(command)  # type: ignore[misc]

    def _eval_json(self, script: str) -> dict[str, Any]:
        result = self._parse_json_object(self._call_browser_use(["eval", script]))
        if result is None:
            raise MaituBrowserExecutionError(
                "browser-use eval returned no JSON object for Maitu API operation.",
                retryable=True,
                retry_instruction="Re-run observe and verify the browser is on an authenticated Maitu page before retrying.",
            )
        return result

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
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname == "live2.maituai.com"
            and port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )

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
        return BrowserUseCliSession._is_maitu_url(url) and any(
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


# Capture every method/property descriptor once when the built-in implementation
# is defined. The queue trust gate therefore cannot miss an internal helper
# reached indirectly by an allowed session entry point.
_TRUSTED_BROWSER_USE_CLI_SESSION_METHODS = tuple(
    (method_name, descriptor)
    for method_name, descriptor in vars(BrowserUseCliSession).items()
    if callable(descriptor) or type(descriptor) in {staticmethod, classmethod, property}
)
_TRUSTED_BROWSER_USE_CLI_SESSION_RUN_COMMAND = vars(BrowserUseCliSession)["_run_command"]
