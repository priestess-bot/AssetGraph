import { createHash } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(frontendRoot, "..");
const evidenceRoot = resolve(repoRoot, "docs/evidence");
const screenshotRoot = resolve(evidenceRoot, "screenshots");
const baseUrl = process.env.ASSETGRAPH_FRONTEND_URL ?? "http://127.0.0.1:5190";
const chromePath = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const posterPath = resolve(repoRoot, "outputs/customer-v1/v1-0515/AG-VJOB-20260725-000002/attempt-1/poster.jpg");
const videoPath = resolve(repoRoot, "outputs/customer-v1/v1-0515/AG-VJOB-20260725-000002/attempt-1/final.mp4");

const routes = [
  ["overview", "/console/?demo=1", "直播内容生产概览"],
  ["assets", "/console/assets?demo=1", "素材库"],
  ["templates", "/console/templates?demo=1", "直播模板"],
  ["knowledge", "/console/knowledge?demo=1", "知识库"],
  ["projects", "/console/projects?demo=1", "内容项目"],
  ["operations-import", "/console/operations?demo=1", "运营与内容表现"],
  ["operations-analysis", "/console/operations?view=attribution&demo=1", "运营与内容表现"],
  ["learning", "/console/learning?demo=1", "效果学习"],
  ["live-room-editor", "/console/production/live-rooms?run=live-summer&demo=1", "盛夏轻食新品直播间"],
  ["video-editor", "/console/production/videos?plan=video-summer&demo=1", "轻食新品竖屏精华"],
];
const viewports = [["1440x900", 1440, 900], ["1920x1080", 1920, 1080]];

const assets = [
  ["asset-kitchen", "晨间厨房背景", "kitchen.jpg", "image", "background", "maitu_bound"],
  ["asset-gift", "轻食礼盒商品图", "gift.jpg", "image", "product_display", "maitu_bound"],
  ["asset-host", "营养师数字人", "host.png", "image", "digital_human", "maitu_bound"],
  ["asset-title", "夏日优惠标题贴片", "title.png", "image", "promotion_text", "maitu_bound"],
  ["asset-video", "轻食制作过程", "making.mp4", "video", "supporting_video", "local_only"],
  ["asset-music", "轻快晨间音乐", "morning.mp3", "audio", "background_music", "local_only"],
].map(([asset_code, title, original_filename, media_kind, role, execution_capability]) => ({
  asset_code, title, original_filename, asset_type: media_kind === "image" ? "IMG" : media_kind === "video" ? "VID" : "AUD",
  media_kind, material_roles: [role], execution_capability, rights_status: "approved", status: "ready", source_system: "内容团队",
}));

const projects = [
  ["project-summer", "盛夏轻食新品首发", "围绕低负担早餐场景，完成一场有节奏的新品介绍与互动直播。", "active", 4],
  ["project-wine", "产区风味品鉴专场", "用已核验的产区事实支撑故事，突出餐桌搭配和品鉴顺序。", "confirmed", 3],
  ["project-home", "清凉家居焕新直播", "从闷热居家痛点切入，串联三组清凉家居商品。", "draft", 1],
].map(([project_code, title, generation_goal, status, revision_number], index) => ({ project_code, title, generation_goal, status, revision_number, created_at: `2026-07-${20 - index}T03:00:00Z`, updated_at: `2026-07-${28 - index}T09:30:00Z` }));

const templates = [
  { template_code: "template-launch", name: "高效新品首发结构", source_session_code: "source-launch", template_kind: "content_strategy", status: "published", published_revision_number: 2, published_content_readiness: "ready", published_layout_fidelity: "approximate", published_buildability: "reference_only", content_strategy: { target_category: "食品新品", compatibility_tags: ["新品首发", "轻食", "强互动"], program_outline: [{ module_key: "opening", title: "痛点开场", purpose: "快速建立早餐场景", start_ms: 0, end_ms: 180000 }, { module_key: "demo", title: "制作与品尝", purpose: "展示真实使用过程", start_ms: 180000, end_ms: 720000 }, { module_key: "offer", title: "组合权益", purpose: "集中解释购买方案", start_ms: 720000, end_ms: 960000 }], duration_policy: { target_duration_seconds: 960, pacing: "前快后稳" }, host_style: { tone: "自然可信", delivery: "短句互动" }, material_cues: ["商品近景", "制作过程"] }, scenes: [{ scene_code: "opening", title: "早餐痛点开场", start_seconds: 0, end_seconds: 180, purpose: "建立共鸣", material_slots: ["background", "digital_human"], components: [] }, { scene_code: "demo", title: "商品制作演示", start_seconds: 180, end_seconds: 720, purpose: "展示使用", material_slots: ["product_display", "supporting_video"], components: [] }], updated_at: "2026-07-27T08:20:00Z" },
  { template_code: "template-table", name: "餐桌品鉴空间", source_session_code: "source-table", template_kind: "layout_hypothesis", status: "published", published_revision_number: 3, published_content_readiness: "ready", published_layout_fidelity: "verified_layout", published_buildability: "executable", content_strategy: { target_category: "餐饮品鉴", compatibility_tags: ["桌面陈列", "品鉴"], program_outline: [], material_cues: ["餐桌背景", "商品陈列"] }, scenes: [{ scene_code: "table", title: "桌面品鉴", start_seconds: 0, end_seconds: 420, purpose: "讲解风味", material_slots: ["background", "product_display"], components: [] }], updated_at: "2026-07-26T07:10:00Z" },
  { template_code: "template-story", name: "产地故事慢节奏结构", source_session_code: "source-story", template_kind: "content_strategy", status: "draft", latest_revision_number: 1, content_readiness: "review_required", layout_fidelity: "none", buildability: "reference_only", content_strategy: { target_category: "品牌故事", compatibility_tags: ["产地故事"], program_outline: [], material_cues: [] }, scenes: [], updated_at: "2026-07-25T06:10:00Z" },
];

const facts = [
  ["fact-oat", "燕麦坚果杯产品事实", "晨光燕麦坚果杯", ["每杯含 12 克蛋白质", "常温保存 9 个月"], "approved"],
  ["fact-wine", "赤霞珠风味与产区事实", "山麓赤霞珠", ["葡萄来自海拔 1100 米以上地块", "建议醒酒 20 分钟"], "approved"],
  ["fact-offer", "夏日组合权益", "早餐组合装", ["活动期内两盒组合享赠品"], "draft"],
].map(([fact_card_code, title, product_name, verified_facts, status], index) => ({ fact_card_code, title, status: status === "approved" ? "active" : "draft", current_approved_version: status === "approved" ? 1 : null, versions: [{ version_code: `${fact_card_code}-v1`, version_number: 1, status, content: { product_name, positioning: "日常生活方式商品", verified_facts, scenarios: ["早餐", "家庭分享"], source_references: [{ evidence_code: `source-${index + 1}` }] }, created_at: "2026-07-24T06:00:00Z" }], updated_at: "2026-07-27T06:00:00Z" }));

const sources = [
  ["source-1", "燕麦坚果杯产品规格书", "规格书确认每杯蛋白质含量及保存期限。", "approved", "https://example.com/oat-spec"],
  ["source-2", "酒庄批次与品鉴说明", "酒庄提供本批次地块海拔和醒酒建议。", "approved", "https://example.com/wine-note"],
  ["source-3", "夏季活动运营确认", "活动权益等待最终确认。", "draft", ""],
].map(([evidence_code, title, excerpt, status, source_url], index) => ({ evidence_code, source_type: "document", title, source_url: source_url || undefined, excerpt, content_sha256: String(index + 1).repeat(64), access_scope: "internal", status, updated_at: "2026-07-27T06:00:00Z" }));

const scene = (scene_code, shot_code, title, script, layers) => ({ scene_code, shot_code, title, script, layers });
const layer = (role, asset_code, x, y, width, height, z_order) => ({ role, asset_code, execution_capability: "maitu_bound", normalized_geometry: { x, y, width, height }, z_order });
const livePlan = {
  plan_code: "live-summer", project_code: "project-summer", variant_code: "default", configuration_code: "summer-layout", target_live_room_id: "39826", expected_title: "盛夏轻食新品直播间", primary_template_code: "template-table", secondary_template_codes: ["template-launch"], selected_asset_codes: ["asset-kitchen", "asset-gift", "asset-host", "asset-title"], selected_group_codes: ["group-breakfast"], selected_material_pack_codes: [], selected_asset_gap_codes: [],
  blueprint: { schema_version: "maitu-scene-blueprint.v1", scenes: [
    scene("scene-opening", "shot-opening", "清爽开场", "早上时间紧，也可以认真吃一顿轻负担早餐。", [layer("background", "asset-kitchen", 0, 0, 1, 1, 0), layer("digital_human", "asset-host", .06, .18, .38, .68, 10), layer("promotion_text", "asset-title", .08, .78, .84, .12, 30)]),
    scene("scene-product", "shot-product", "商品近景", "这一杯的谷物、坚果和果干分层清晰，打开即可食用。", [layer("background", "asset-kitchen", 0, 0, 1, 1, 0), layer("product_display", "asset-gift", .48, .3, .44, .4, 20)]),
    scene("scene-offer", "shot-offer", "组合权益", "现在选择两盒组合，还会附带一份便携餐具。", [layer("background", "asset-kitchen", 0, 0, 1, 1, 0), layer("promotion_text", "asset-title", .08, .12, .84, .14, 30)]),
  ] },
  build_plan: { schema_version: "build-plan.v1", build_plan_code: "summer-draft", target_live_room_id: "39826", go_live: false, inventory_snapshot: { asset_codes: ["asset-kitchen", "asset-gift", "asset-host", "asset-title"], assets: [] }, operations: [{ operation_type: "create_scene", operation_name: "创建直播场景", status: "planned", instruction: "依次建立三个场景。" }, { operation_type: "add_layer", operation_name: "添加画面素材", status: "planned", instruction: "按场景清单放置素材。" }, { operation_type: "save_draft", operation_name: "保存直播草稿", status: "planned", instruction: "只保存草稿，不执行开播。" }] },
  gate_results: [{ gate: "draft_ready", status: "passed", rule_code: "ready" }], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, updated_at: "2026-07-28T08:00:00Z",
};

const videoClip = (kind, index, start, duration, text, headline) => ({ clip_code: `clip-${kind}-${index}`, source_shot_code: ["shot-opening", "shot-product", "shot-offer"][index - 1], timeline_range: { start_ms: start, duration_ms: duration }, ...(kind === "video" ? { source_range: { asset_code: "asset-video", start_seconds: start / 1000, end_seconds: (start + duration) / 1000 }, transition: index === 1 ? "cut" : "fade", fit: "cover", playback_rate: 1 } : kind === "subtitle" ? { subtitle_text: text, headline_text: headline, caption_position: "bottom" } : { gain_db: -2 }) });
const videoPlan = {
  plan_code: "video-summer", project_code: "project-summer", variant_code: "vertical", video_job_code: "summer-render", title: "轻食新品竖屏精华", timeline_revision: 3,
  production_timeline: { global_end_ms: 18000, poster_time_ms: 2200, subtitle_style: { preset: "standard", safe_bottom_px: 160 }, tracks: [
    { track_kind: "video", clips: [videoClip("video", 1, 0, 5000), videoClip("video", 2, 5000, 8000), videoClip("video", 3, 13000, 5000)] },
    { track_kind: "subtitle", clips: [videoClip("subtitle", 1, 0, 5000, "时间再紧，也值得认真吃早餐。", "轻负担早餐"), videoClip("subtitle", 2, 5000, 8000, "谷物、坚果和果干清晰可见。", "真实配料"), videoClip("subtitle", 3, 13000, 5000, "两盒组合附带便携餐具。", "直播组合")] },
    { track_kind: "audio", clips: [videoClip("audio", 1, 0, 5000), videoClip("audio", 2, 5000, 8000), videoClip("audio", 3, 13000, 5000)] },
  ] }, render_profile: { target_duration_seconds: 18, canvas: { width: 1080, height: 1920, fps: 30 }, visual_selection: { direct_asset_codes: ["asset-video"], group_refs: [], material_pack_refs: [] } }, job_status: "completed", current_stage: "completed", progress_percent: 100,
  quality_report: { passed: true, checks: { picture: true, audio: true, subtitles: true, duration: true }, media: { duration_seconds: 18, width: 1080, height: 1920, video_codec: "h264", audio_codec: "aac" }, black_segments: [], silence_segments: [], freeze_segments: [] },
  workflow_stages: ["prepare", "render", "quality_check", "package"].map((stage_name, index) => ({ stage_name, stage_order: index + 1, status: "completed", attempt: 1 })),
  artifacts: [{ artifact_key: "video", download_url: "/api/demo/video", mime_type: "video/mp4", metadata: {} }, { artifact_key: "poster", download_url: "/api/demo/poster", mime_type: "image/jpeg", metadata: {} }, { artifact_key: "contact_sheet", download_url: "/api/demo/poster", mime_type: "image/jpeg", metadata: {} }], reproducibility: { timeline_revision: 3, timeline_fingerprint_sha256: "d".repeat(64), manifest_covers: ["timeline", "assets"], retry_difference_recorded: false }, timeline_segments: [],
};

const sessions = [["session-1", "新品首发晚场", 428, 63, 22], ["session-2", "轻食早餐午间场", 516, 74, 31], ["session-3", "周末家庭分享场", 389, 52, 18]].map(([session_code, title, product_clicks, comments, orders], index) => ({ session_code, title, platform: "抖音", source_timezone: "Asia/Shanghai", content_project_code: "project-summer", live_room_plan_code: "live-summer", binding_status: "resolved", source_kind: "manual_import", started_at: `2026-07-${24 + index}T11:00:00Z`, ended_at: `2026-07-${24 + index}T12:30:00Z`, metrics: { product_clicks, comments, orders } }));
const reports = [{ report_code: "report-clicks", metric_key: "product_clicks", evidence_level: "associational", status: "published", session_codes: sessions.map((item) => item.session_code), created_at: "2026-07-28T07:00:00Z", quality_snapshot: { publication_scope: "descriptive_only", reasons: [], eligible_for_descriptive_publication: true }, results: { dimension_groups: [{ dimension_type: "program_segment", dimension_code: "opening", display_label: "痛点开场", metric_key: "product_clicks", descriptive_value_total: 390, average_per_session: 130, sample_size: 3, session_codes: sessions.map((item) => item.session_code), evidence_level: "associational", effect_signal_eligible: true }, { dimension_type: "template", dimension_code: "template-launch", display_label: "高效新品首发结构", metric_key: "product_clicks", descriptive_value_total: 870, average_per_session: 290, sample_size: 3, session_codes: sessions.map((item) => item.session_code), evidence_level: "associational", effect_signal_eligible: true }, { dimension_type: "asset", dimension_code: "asset-gift", display_label: "轻食礼盒商品图", metric_key: "product_clicks", descriptive_value_total: 642, average_per_session: 214, sample_size: 3, session_codes: sessions.map((item) => item.session_code), evidence_level: "associational", effect_signal_eligible: true }] } }];
const effects = [{ effect_code: "effect-closeup", attribution_report_code: "report-clicks", subject_code: "project-summer", metric_key: "product_clicks", evidence_level: "associational", status: "approved", note: "商品近景出现后的互动和点击表现更高，下一版保留近景演示段。", effect_payload: { subject_snapshot: { content: { theme: "轻食新品", story: "从忙碌早餐切入", primary_template_ref: { template_code: "template-launch", revision: 2 } }, script_blocks: [{ block_code: "opening" }], production_variants: [{ material_snapshot_ref: { asset_codes: ["asset-gift", "asset-video"] } }] } }, eligibility_snapshot: { selected_session_count: 3, observed_session_count: 3, recommendation_eligible: true, association_blockers: [] } }, { effect_code: "effect-offer", attribution_report_code: "report-clicks", subject_code: "project-summer", metric_key: "orders", evidence_level: "descriptive", status: "candidate", note: "权益说明集中在结尾时，用户提问更聚焦，但还需要更多场次验证。", effect_payload: { subject_snapshot: { content: { theme: "轻食新品" }, script_blocks: [{ block_code: "offer" }] } }, eligibility_snapshot: { selected_session_count: 2, observed_session_count: 2, recommendation_eligible: false, association_blockers: ["EFFECT_SAMPLE_SIZE_BELOW_MINIMUM"] } }];

const fulfillJson = (route, value) => route.fulfill({ status: 200, contentType: "application/json; charset=utf-8", body: JSON.stringify(value) });
async function fixture(route) {
  const path = new URL(route.request().url()).pathname;
  if (path === "/api/demo/video") return route.fulfill({ contentType: "video/mp4", body: await readFile(videoPath) });
  if (path === "/api/demo/poster") return route.fulfill({ contentType: "image/jpeg", body: await readFile(posterPath) });
  if (/^\/api\/assets\/[^/]+\/preview$/.test(path)) return route.fulfill({ contentType: path.includes("asset-video") ? "video/mp4" : "image/jpeg", body: await readFile(path.includes("asset-video") ? videoPath : posterPath) });
  if (path === "/api/assets/groups") return fulfillJson(route, [{ group_code: "group-breakfast", title: "轻食早餐标准素材", description: "适合早餐与轻食主题直播", asset_codes: ["asset-kitchen", "asset-gift", "asset-host", "asset-title"], asset_count: 4 }]);
  if (path === "/api/assets") return fulfillJson(route, assets);
  if (path === "/api/live-research/room-templates") return fulfillJson(route, templates);
  if (path === "/api/live-research/capture-sessions") return fulfillJson(route, []);
  if (path === "/api/maitu/workbench/product-fact-cards") return fulfillJson(route, facts);
  if (/^\/api\/maitu\/workbench\/product-fact-cards\/[^/]+\/versions\/\d+\/usage$/.test(path)) return fulfillJson(route, []);
  if (path === "/api/functional-knowledge/source-evidences") return fulfillJson(route, sources);
  if (path === "/api/content-projects") return fulfillJson(route, projects);
  if (path === "/api/functional-operations/pending-bindings") return fulfillJson(route, []);
  if (path === "/api/functional-operations/sessions") return fulfillJson(route, sessions);
  if (path === "/api/functional-operations/attribution-reports") return fulfillJson(route, reports);
  if (path === "/api/data-governance/metrics") return fulfillJson(route, [{ metric_code: "product_clicks", revision_number: 1, status: "active", metric_status: "active", owner_principal: "运营团队", name: "商品点击次数", description: "直播期间商品卡片被点击的次数", unit: "次", value_type: "integer", aggregation: "sum", dimensions: ["内容", "模板", "素材"], event_contract_refs: [], deduplication_keys: [], null_rule: {}, outlier_rule: {}, schema_compatibility: {}, quality_slo: {}, fingerprint_sha256: "e".repeat(64) }]);
  if (path === "/api/data-governance/contracts") return fulfillJson(route, []);
  if (path === "/api/functional-learning/effects") return fulfillJson(route, effects);
  if (path === "/api/functional-live-room-plans/maitu-capabilities") return fulfillJson(route, { schema_version: "maitu-capability-matrix.v1", adapter_contract: "browser-draft.v1", contract_fingerprint: "a".repeat(64), source: "验收环境", can_execute_draft: true, manual_handoff_available: true, unverified_required_capabilities: [], capabilities: [{ key: "scene", title: "创建与调整场景", status: "verified", required_for_draft: true, evidence_level: "verified", evidence_refs: [], customer_message: "可以写入并保存场景草稿" }, { key: "layer", title: "放置画面素材", status: "verified", required_for_draft: true, evidence_level: "verified", evidence_refs: [], customer_message: "可以按方案放置素材" }, { key: "go-live", title: "正式开播", status: "unsupported", required_for_draft: false, evidence_level: "not_available", evidence_refs: [], customer_message: "当前版本不会执行正式开播" }] });
  if (path === "/api/functional-live-room-plans") return fulfillJson(route, [livePlan]);
  if (path === "/api/functional-live-room-plans/live-summer") return fulfillJson(route, livePlan);
  if (path === "/api/functional-video-plans") return fulfillJson(route, [videoPlan]);
  if (path === "/api/functional-video-plans/video-summer") return fulfillJson(route, videoPlan);
  if (path.startsWith("/api/functional-learning/recommendations/")) return fulfillJson(route, { candidates: [], project_effect_hints: [] });
  return fulfillJson(route, []);
}

const auditExpression = `(() => {
  const visible = (element) => { const style = getComputedStyle(element); const rect = element.getBoundingClientRect(); return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 && rect.width > 1 && rect.height > 1; };
  const scrollable = (element) => { let current = element.parentElement; while (current && current !== document.body) { const style = getComputedStyle(current); if (/(auto|scroll)/.test(style.overflowX) && current.scrollWidth > current.clientWidth + 1) return true; current = current.parentElement; } return false; };
  const controls = [...document.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary')].filter(visible);
  const unreachableControls = controls.filter((element) => { const rect = element.getBoundingClientRect(); return (rect.right > innerWidth + 2 || rect.left < -2) && !scrollable(element); }).map((element) => ({ text: (element.getAttribute('aria-label') || element.getAttribute('title') || element.textContent || '').trim().slice(0, 60), left: Math.round(element.getBoundingClientRect().left), right: Math.round(element.getBoundingClientRect().right) }));
  const siblingControlOverlaps = [];
  for (let index = 0; index < controls.length; index += 1) for (let otherIndex = index + 1; otherIndex < controls.length; otherIndex += 1) { const left = controls[index], right = controls[otherIndex]; if (left.parentElement !== right.parentElement || left.contains(right) || right.contains(left)) continue; if (left.closest('.live-phone-canvas') && right.closest('.live-phone-canvas')) continue; const a = left.getBoundingClientRect(), b = right.getBoundingClientRect(); const width = Math.min(a.right, b.right) - Math.max(a.left, b.left); const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top); if (width > 4 && height > 4) siblingControlOverlaps.push({ first: (left.textContent || left.getAttribute('title') || '').trim().slice(0, 50), second: (right.textContent || right.getAttribute('title') || '').trim().slice(0, 50), pixels: Math.round(width * height) }); }
  const text = (document.querySelector('.console-workspace')?.innerText || '').trim();
  const leakedInternalTokens = [...new Set([...(text.match(/[A-Z][A-Z0-9]+(?:[_-][A-Z0-9]+){1,}/g) || []), ...(text.match(/\\b(?:fingerprint|trace[_ -]?id|schema_version|error_code)\\b/gi) || [])])].filter((token) => token.toUpperCase() !== 'ASSETGRAPH');
  const rootWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  return { heading: document.querySelector('h1')?.textContent?.trim() || '', textLength: text.length, horizontalOverflowPx: Math.max(0, rootWidth - innerWidth), unreachableControls, siblingControlOverlaps, leakedInternalTokens, runtimeErrors: window.__productAuditErrors || [] };
})()`;

await mkdir(screenshotRoot, { recursive: true });
await stat(posterPath); await stat(videoPath);
const browser = await chromium.launch({ headless: true, executablePath: chromePath, args: ["--disable-dev-shm-usage"] });
const audits = [];
try {
  for (const [viewport, width, height] of viewports) {
    const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
    await context.addInitScript(() => { window.__productAuditErrors = []; window.addEventListener("error", (event) => window.__productAuditErrors.push(String(event.message || "页面脚本错误"))); window.addEventListener("unhandledrejection", (event) => window.__productAuditErrors.push(String(event.reason || "未处理的页面错误"))); });
    const page = await context.newPage();
    await page.route("**/api/**", fixture);
    for (const [routeName, path, expectedHeading] of routes) {
      await page.goto(`${baseUrl}${path}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(".console-shell", { timeout: 30_000 });
      await page.waitForFunction((heading) => { const workspace = document.querySelector(".console-workspace"); return Boolean(workspace && workspace.textContent?.includes(heading) && workspace.textContent.trim().length > 80 && !workspace.querySelector(".wb-loading")); }, expectedHeading, { timeout: 30_000 });
      await page.waitForTimeout(700);
      const audit = await page.evaluate(auditExpression);
      const output = resolve(screenshotRoot, `frontend-product-redesign-${viewport}-${routeName}.png`);
      await page.screenshot({ path: output, fullPage: false, animations: "disabled" });
      const bytes = await readFile(output);
      const failures = [];
      if (audit.textLength < 80) failures.push("blank-workspace");
      if (audit.horizontalOverflowPx > 1) failures.push("horizontal-overflow");
      if (audit.unreachableControls.length) failures.push("unreachable-controls");
      if (audit.siblingControlOverlaps.length) failures.push("overlapping-controls");
      if (audit.leakedInternalTokens.length) failures.push("internal-token-leak");
      if (audit.runtimeErrors.length) failures.push("runtime-error");
      audits.push({ viewport, route: routeName, path, ...audit, failures, screenshot: { path: output.slice(repoRoot.length + 1), width, height, sizeBytes: bytes.length, checksumSha256: createHash("sha256").update(bytes).digest("hex") } });
    }
    await context.close();
  }
} finally { await browser.close(); }

const failed = audits.filter((item) => item.failures.length);
const evidence = { schemaVersion: "frontend-product-redesign-visual-audit.v1", completedAt: new Date().toISOString(), baseUrl, viewportCount: viewports.length, routeCount: routes.length, screenshotCount: audits.length, status: failed.length ? "failed" : "passed", failures: failed.map(({ viewport, route, failures }) => ({ viewport, route, failures })), audits };
const evidencePath = resolve(evidenceRoot, "frontend-product-redesign-visual-audit-2026-07-28.json");
await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
console.log(`Captured ${audits.length} screenshots; ${failed.length} audits failed.`);
console.log(`Evidence: ${evidencePath}`);
if (failed.length) process.exitCode = 1;
