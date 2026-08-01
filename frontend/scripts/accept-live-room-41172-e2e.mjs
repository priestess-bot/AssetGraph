import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_ORIGIN = process.env.ASSETGRAPH_APP_ORIGIN || "http://127.0.0.1:5190";
const API_ORIGIN = process.env.ASSETGRAPH_API_ORIGIN || "http://127.0.0.1:8000";
const CHROME_PATH = process.env.CHROME_PATH || "/usr/bin/google-chrome";
const EXECUTE = process.argv.includes("--execute");
const WRITE_AUTHORIZED = process.env.ASSETGRAPH_E2E_WRITE_41172 === "1";
const HEADLESS = process.env.ASSETGRAPH_E2E_HEADLESS !== "0";
const ROOM_ID = "41172";
const ROOM_TITLE = "asser测试";
const THEME = "介绍张裕品酒大师PRO";
const GOAL = "生成一场恰好三段的离线测试直播草稿，完整介绍张裕品酒大师PRO的产品特点、品鉴方法与适合场景。";
const STORY = "从第一次选酒的困惑切入，用看色、闻香、品味三个动作完成产品介绍，最后回顾适合人群与品鉴建议。";
const DETAILED_DESIGN = [
  "第一段开场建立品牌和品鉴目标；第二段展示商品或酒体视频并讲解品鉴步骤；第三段总结卖点和互动问题。",
  "背景必须置底，桌面承托商品，商品或视频位于背景之上，数字人位于商品内容之上，品牌标题或前景装饰位于高层。",
  "最终只生成三个场景，只写入离线测试草稿，不排播、不开播。",
].join("\n");
const VIEWPORT = { width: 1600, height: 1000 };
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const runId = new Date().toISOString().replace(/[:.]/g, "-");
const evidenceDir = path.join(repoRoot, "docs/evidence", `live-room-41172-product-e2e-${runId}`);

if (EXECUTE && !WRITE_AUTHORIZED) {
  throw new Error(
    "真实写入被拒绝：必须同时传入 --execute 和 ASSETGRAPH_E2E_WRITE_41172=1。默认模式只做无写入预检。",
  );
}

const startedAt = new Date();
let clickCount = 0;
let planCode = "";
let projectCode = "";
let terminalStatus = "not_started";
const selectedMaterials = [];
const interactionLog = [];
const workflowDurationsMs = {};
const pageErrors = [];
const consoleErrors = [];
const requestFailures = [];
const httpErrors = [];
const mutationRequests = [];
const networkEvidence = [];
const networkTasks = [];
const stageScreenshots = {};
const manualInterventionPoints = [];

function nowIso() {
  return new Date().toISOString();
}

function jsonValue(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text.length > 20_000 ? `${text.slice(0, 20_000)}\n...[truncated]` : text;
  }
}

function apiPath(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

function isIgnoredConsoleError(item) {
  return String(item?.url || "").endsWith("/favicon.ico");
}

function assertNoBrowserErrors(phase) {
  const blockingConsoleErrors = consoleErrors.filter((item) => !isIgnoredConsoleError(item));
  const count = pageErrors.length + blockingConsoleErrors.length + requestFailures.length + httpErrors.length;
  if (!count) return;
  throw new Error(
    `${phase}发现 ${count} 个浏览器或接口错误（页面 ${pageErrors.length}、控制台 ${blockingConsoleErrors.length}、请求 ${requestFailures.length}、HTTP ${httpErrors.length}）`,
  );
}

function isJsonApiResponse(response) {
  const contentType = response.headers()["content-type"] || "";
  return response.url().includes("/api/") && contentType.includes("json");
}

async function saveJson(name, value) {
  await fs.mkdir(evidenceDir, { recursive: true });
  await fs.writeFile(path.join(evidenceDir, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function screenshot(page, name, metadata = {}) {
  await fs.mkdir(evidenceDir, { recursive: true });
  const filename = `${name}.png`;
  await page.screenshot({ path: path.join(evidenceDir, filename), fullPage: true });
  interactionLog.push({ at: nowIso(), kind: "screenshot", name, file: filename, ...metadata });
  return filename;
}

async function uiClick(locator, label) {
  await locator.waitFor({ state: "visible", timeout: 20_000 });
  if (!(await locator.isEnabled())) throw new Error(`控件不可用：${label}`);
  clickCount += 1;
  interactionLog.push({ at: nowIso(), kind: "click", label, clickNumber: clickCount });
  await locator.click();
}

async function fill(locator, value, label) {
  await locator.waitFor({ state: "visible", timeout: 20_000 });
  await locator.fill(value);
  interactionLog.push({ at: nowIso(), kind: "fill", label, characterCount: value.length });
}

async function timed(name, action) {
  const started = Date.now();
  try {
    return await action();
  } finally {
    workflowDurationsMs[name] = Date.now() - started;
  }
}

function latestNetworkBody(predicate) {
  for (let index = networkEvidence.length - 1; index >= 0; index -= 1) {
    const item = networkEvidence[index];
    if (predicate(item)) return item.responseBody;
  }
  return undefined;
}

function planFromUiResponse() {
  return latestNetworkBody((item) => {
    const body = item.responseBody;
    return body && typeof body === "object" && body.plan_code === planCode && body.blueprint;
  });
}

function latestExecutionFromUiResponse() {
  return latestNetworkBody((item) => {
    const pathname = item.path.split("?")[0];
    return item.source === "console-page-network"
      && item.method === "GET"
      && pathname.endsWith(`/${planCode}/execution`);
  });
}

async function waitUntil(name, predicate, timeoutMs, intervalMs = 300) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`${name} 等待超时`);
}

async function findReadyAssetForRole(page, roleLabel, preferredTitlePatterns = []) {
  const rows = page.locator(".live-asset-choice");
  let fallback = null;
  for (let index = 0; index < await rows.count(); index += 1) {
    const row = rows.nth(index);
    const roleSummary = (await row.locator("small").first().innerText()).split("·")[0].trim();
    const displayedRoles = roleSummary.split("、").map((value) => value.trim()).filter(Boolean);
    const rowText = await row.innerText();
    const checkbox = row.getByRole("checkbox");
    if (
      displayedRoles.includes(roleLabel)
      && await checkbox.isEnabled()
      && (rowText.includes("仅限测试草稿") || rowText.includes("可写入草稿"))
    ) {
      const title = (await row.locator("strong").first().innerText()).trim();
      const candidate = { row, checkbox, index, displayedRoles, rowText, title };
      if (preferredTitlePatterns.some((pattern) => title.includes(pattern))) return candidate;
      fallback ||= candidate;
    }
  }
  return fallback;
}

async function selectAssetForRole(page, roleKey, roleLabels) {
  const expectedBindings = {
    background: { assetCode: "AG-IMG-20260729-000002", maituMaterialId: "37262" },
    set_surface: { assetCode: "AG-IMG-20260729-000028", maituMaterialId: "39157" },
    product: { assetCode: "AG-IMG-20260729-000025", maituMaterialId: "40999" },
    video: { assetCode: "AG-VID-20260729-000019", maituMaterialId: "40774" },
    digital_human: { assetCode: "AG-VID-20260731-000001", maituMaterialId: "37200" },
    top: { assetCode: "AG-IMG-20260729-000021", maituMaterialId: "40101" },
  }[roleKey];
  const preferredTitles = {
    background: ["背景-3"],
    set_surface: ["39157_底"],
    product: ["品酒大师PRO"],
    video: ["商品讲解视频 - 品酒大师PRO"],
    digital_human: ["张裕定制形象"],
    top: ["张裕百年", "标题+logo"],
  }[roleKey] || [];
  let candidate;
  let matchedLabel;
  for (const label of roleLabels) {
    candidate = await findReadyAssetForRole(page, label, preferredTitles);
    if (candidate) {
      matchedLabel = label;
      break;
    }
  }
  if (!candidate || !matchedLabel) {
    throw new Error(`没有找到可写入麦兔测试草稿的${roleLabels.join("或")}素材`);
  }
  const title = candidate.title;
  if (!(await candidate.checkbox.isChecked())) {
    await uiClick(candidate.checkbox, `选择${matchedLabel}素材：${title}`);
  }
  await Promise.allSettled(networkTasks);
  const assets = latestNetworkBody(
    (item) => item.method === "GET" && item.path.startsWith("/api/assets?limit=") && Array.isArray(item.responseBody),
  ) || [];
  const source = assets.find((item) => item?.title === title);
  if (!source) throw new Error(`没有在素材接口回读中找到已选${matchedLabel}素材：${title}`);
  if (!expectedBindings || source.asset_code !== expectedBindings.assetCode) {
    throw new Error(`已选${matchedLabel}素材不是本次 41172 验收锁定的主题素材`);
  }
  if (roleKey === "digital_human") {
    if (
      source.execution_capability !== "maitu_bound"
      || String(source.maitu_source_material_id || "") !== "37200"
      || String(source.digital_human_image_id || "") !== "7717"
      || String(source.speaker_id || "") !== "3760"
    ) {
      throw new Error("数字人素材没有冻结 37200 / 7717 / 3760 的可执行绑定");
    }
  } else {
    if (String(source.maitu_material_id || "") !== expectedBindings.maituMaterialId) {
      throw new Error(`已选${matchedLabel}素材没有冻结预期的麦兔素材绑定`);
    }
    const preview = candidate.row.locator("img");
    if (await preview.count() !== 1) throw new Error(`已选${matchedLabel}素材没有图片预览`);
    await waitUntil(`${matchedLabel}素材预览加载`, async () => preview.evaluate(
      (image) => image.complete && image.naturalWidth > 0 && image.naturalHeight > 0,
    ), 20_000, 100);
  }
  selectedMaterials.push({
    roleKey,
    matchedLabel,
    title,
    assetCode: source.asset_code,
    materialRoles: source.material_roles || [],
    displayedRoles: candidate.displayedRoles,
    previewVerified: roleKey === "digital_human" ? "maitu_binding" : "decoded_image",
  });
}

function layerRole(layer) {
  return String(layer?.role || layer?.material_role || "");
}

function assertRolesBelow(layers, lowerRoles, upperRoles, sceneNumber) {
  const lowers = layers.filter((layer) => lowerRoles.includes(layerRole(layer)));
  const uppers = layers.filter((layer) => upperRoles.includes(layerRole(layer)));
  for (const lower of lowers) {
    for (const upper of uppers) {
      if (!(Number(lower.z_order) < Number(upper.z_order))) {
        throw new Error(
          `第 ${sceneNumber} 场图层关系错误：${layerRole(lower)} 必须位于 ${layerRole(upper)} 下方`,
        );
      }
    }
  }
}

function assertProductOnSurface(layers, sceneNumber) {
  const surface = layers.find((layer) => layerRole(layer) === "set_surface");
  const products = layers.filter((layer) => layerRole(layer) === "product_display");
  if (!surface || !products.length) return;
  const surfaceRule = (surface.constraint_evidence?.applied_rules || []).find(
    (rule) => ["provide_named_region", "table_surface"].includes(rule.kind)
      && [rule.parameters?.region, rule.parameters?.name].includes("table_surface"),
  );
  const rect = surfaceRule?.parameters?.rect;
  if (!Array.isArray(rect) || rect.length !== 4 || rect.some((value) => !Number.isFinite(Number(value)))) {
    throw new Error(`第 ${sceneNumber} 场桌面素材没有提供可执行的 table_surface 区域`);
  }
  const surfaceRect = { x: Number(rect[0]), y: Number(rect[1]), width: Number(rect[2]), height: Number(rect[3]) };
  for (const product of products) {
    const rect = product.normalized_geometry;
    const epsilon = 0.002;
    const contained = rect.x + epsilon >= surfaceRect.x
      && rect.y + epsilon >= surfaceRect.y
      && rect.x + rect.width <= surfaceRect.x + surfaceRect.width + epsilon
      && rect.y + rect.height <= surfaceRect.y + surfaceRect.height + epsilon;
    const bottomAligned = Math.abs(
      (rect.y + rect.height) - (surfaceRect.y + surfaceRect.height),
    ) <= epsilon;
    const centered = Math.abs(
      (rect.x + rect.width / 2) - (surfaceRect.x + surfaceRect.width / 2),
    ) <= epsilon;
    const appliedRules = product.constraint_evidence?.applied_rules || [];
    const requiresSurface = appliedRules.some(
      (rule) => rule.kind === "require_named_region" && rule.parameters?.region === "table_surface",
    );
    const placedOnSurface = appliedRules.some(
      (rule) => rule.kind === "table_surface_placement"
        && rule.parameters?.name === "table_surface"
        && rule.parameters?.product_anchor === "bottom_center",
    );
    if (!contained || !bottomAligned || !centered || !requiresSurface || !placedOnSurface) {
      throw new Error(`第 ${sceneNumber} 场商品没有按桌面区域完整底部居中摆放`);
    }
  }
}

function validatePlan(plan) {
  if (!plan || typeof plan !== "object") throw new Error("没有从页面创建方案的响应中取得 BuildPlan");
  const scenes = plan.blueprint?.scenes;
  if (!Array.isArray(scenes) || scenes.length !== 3) {
    throw new Error(`方案场景数不是 3：${Array.isArray(scenes) ? scenes.length : "缺失"}`);
  }
  if (plan.target_live_room_id !== ROOM_ID || plan.expected_title !== ROOM_TITLE) {
    throw new Error("方案绑定的直播间或标题不正确");
  }
  if (plan.build_plan?.go_live !== false) throw new Error("BuildPlan 未保持 go_live=false");
  const selectedAssetCodes = new Set(selectedMaterials.map((item) => item.assetCode));
  const blueprintAssetCodes = new Set(
    scenes.flatMap((scene) => (scene.layers || []).map((layer) => layer.asset_code)).filter(Boolean),
  );
  const insertOperations = (plan.build_plan?.operations || []).filter(
    (operation) => operation?.operation_type === "insert_asset_layer",
  );
  const insertedAssetCodes = new Set(insertOperations.map((operation) => operation.asset_code).filter(Boolean));
  const missingFromBlueprint = [...selectedAssetCodes].filter((assetCode) => !blueprintAssetCodes.has(assetCode));
  const missingFromBuildPlan = [...selectedAssetCodes].filter((assetCode) => !insertedAssetCodes.has(assetCode));
  const unexpectedBlueprintAssets = [...blueprintAssetCodes].filter((assetCode) => !selectedAssetCodes.has(assetCode));
  if (missingFromBlueprint.length || missingFromBuildPlan.length || unexpectedBlueprintAssets.length) {
    throw new Error(
      `页面选材与执行方案不一致：Blueprint 缺少 ${missingFromBlueprint.join(", ") || "无"}，`
      + `BuildPlan 缺少 ${missingFromBuildPlan.join(", ") || "无"}，`
      + `Blueprint 出现未选择素材 ${unexpectedBlueprintAssets.join(", ") || "无"}`,
    );
  }
  const positionOperations = (plan.build_plan?.operations || []).filter(
    (operation) => operation?.operation_type === "position_asset_layer",
  );
  const scripts = scenes.map((scene) => String(scene.script || "").trim());
  if (scripts.some((script) => !script)) throw new Error("三段场景中存在空话术");
  const combinedScript = scripts.join("\n").replace(/\s+/g, "");
  if (!combinedScript.includes("张裕") || !combinedScript.toUpperCase().includes("品酒大师PRO")) {
    throw new Error("三段话术没有围绕张裕品酒大师PRO生成");
  }
  const roles = new Set(scenes.flatMap((scene) => (scene.layers || []).map(layerRole)));
  const missing = ["background", "set_surface", "digital_human"].filter((role) => !roles.has(role));
  if (!roles.has("product_display") && !roles.has("supporting_video")) missing.push("product_display/supporting_video");
  if (!["brand_title", "decoration_foreground", "promotion_text"].some((role) => roles.has(role))) missing.push("top_visual");
  if (missing.length) throw new Error(`三场方案没有投影全部验收用途：${missing.join(", ")}`);
  for (const [index, scene] of scenes.entries()) {
    const layers = scene.layers || [];
    const sceneRoles = new Set(layers.map(layerRole));
    const selectedRoles = new Set(selectedMaterials.flatMap((item) => item.materialRoles || []));
    const expectedSceneRoles = ["background", "set_surface", "digital_human", "brand_title", "decoration_foreground"]
      .filter((role) => selectedRoles.has(role));
    if (index === 1) {
      for (const role of ["supporting_video", "product_display"]) {
        if (selectedRoles.has(role)) expectedSceneRoles.push(role);
      }
    }
    if (index === 2) {
      for (const role of ["product_display", "promotion_text"]) {
        if (selectedRoles.has(role)) expectedSceneRoles.push(role);
      }
    }
    const missingSceneRoles = expectedSceneRoles.filter((role) => !sceneRoles.has(role));
    if (missingSceneRoles.length) {
      throw new Error(`第 ${index + 1} 场缺少选材意图要求的图层：${missingSceneRoles.join(", ")}`);
    }
    const orders = layers.map((layer) => layer.z_order).sort((left, right) => left - right);
    const expected = Array.from({ length: layers.length }, (_, order) => order + 1);
    if (JSON.stringify(orders) !== JSON.stringify(expected)) {
      throw new Error(`第 ${index + 1} 场图层不是从 1 开始的连续顺序`);
    }
    const sceneNumber = index + 1;
    const topRoles = ["brand_title", "promotion_text", "decoration_foreground"];
    const contentRoles = ["product_display", "supporting_video"];
    assertRolesBelow(layers, ["background"], ["set_surface", ...contentRoles, "digital_human", ...topRoles], sceneNumber);
    assertRolesBelow(layers, ["set_surface"], [...contentRoles, "digital_human", ...topRoles], sceneNumber);
    assertRolesBelow(layers, contentRoles, ["digital_human", ...topRoles], sceneNumber);
    assertRolesBelow(layers, ["digital_human"], topRoles, sceneNumber);
    assertProductOnSurface(layers, sceneNumber);
    for (const layer of layers) {
      const role = layerRole(layer);
      const blueprintFit = layer.visual_properties?.crop_policy;
      const buildOperation = positionOperations.find(
        (operation) => Number(operation.scene_index) === index
          && operation.layer_id === layer.layer_blueprint_code,
      );
      if (role === "background" && (blueprintFit !== "cover" || buildOperation?.fit !== "cover")) {
        throw new Error(`第 ${sceneNumber} 场背景没有按等比例裁切铺满`);
      }
      if (contentRoles.includes(role) && (blueprintFit !== "contain" || buildOperation?.fit !== "contain")) {
        throw new Error(`第 ${sceneNumber} 场商品或视频没有保持完整可见`);
      }
    }
    const highest = [...layers].sort((left, right) => right.z_order - left.z_order)[0];
    if (layerRole(highest) === "supporting_video") throw new Error(`第 ${sceneNumber} 场的视频位于最高图层`);
    if (layers.some((layer) => topRoles.includes(layerRole(layer))) && !topRoles.includes(layerRole(highest))) {
      throw new Error(`第 ${sceneNumber} 场品牌标题或前景没有处于最高语义层级`);
    }
  }
  return {
    sceneCount: scenes.length,
    roles: [...roles].sort(),
    selectedAssetCodes: [...selectedAssetCodes].sort(),
    projectedAssetCodes: [...blueprintAssetCodes].sort(),
  };
}

async function createPlanThroughUi(page) {
  await uiClick(page.getByRole("button", { name: "生成直播间方案", exact: true }), "生成直播间方案");
  let blockerRounds = 0;
  await waitUntil("页面生成三场直播间方案", async () => {
    if (await page.locator(".live-room-editor-v2").count()) return true;
    const error = page.locator(".live-room-builder > .live-friendly-error");
    if (await error.count()) throw new Error((await error.innerText()).trim());
    const questions = page.locator(".live-brief-questions");
    const continueButton = page.getByRole("button", { name: "采用补充并继续", exact: true });
    if (await questions.count() && await continueButton.count() && await continueButton.isEnabled()) {
      if (blockerRounds >= 3) throw new Error("生成简报连续三次要求补充，自动建议仍未解除阻断");
      const textareas = questions.locator("textarea");
      for (let index = 0; index < await textareas.count(); index += 1) {
        const textarea = textareas.nth(index);
        if (!(await textarea.inputValue()).trim()) {
          await fill(textarea, "按三段产品介绍、品鉴演示和总结互动完成。", `补充简报问题 ${index + 1}`);
        }
      }
      blockerRounds += 1;
      await uiClick(continueButton, `采用简报补充并继续（第 ${blockerRounds} 次）`);
    }
    return false;
  }, 240_000, 400);
  const params = new URL(page.url()).searchParams;
  planCode = params.get("run") || "";
  projectCode = params.get("project") || "";
  if (!planCode || !projectCode) throw new Error("方案页面 URL 没有项目编码或方案编码");
  await Promise.allSettled(networkTasks);
  const uiPlan = planFromUiResponse();
  const validation = validatePlan(uiPlan);
  await saveJson("build-plan-from-ui-response.json", {
    capturedAt: nowIso(),
    planCode,
    projectCode,
    validation,
    blueprint: uiPlan.blueprint,
    buildPlan: uiPlan.build_plan,
    materialSnapshot: uiPlan.material_snapshot,
    blockedReasons: uiPlan.blocked_reasons,
  });
  return { uiPlan, validation };
}

async function inspectGeneratedCanvas(page) {
  const scenes = page.locator(".live-scene-outline > section");
  const count = await scenes.count();
  if (count !== 3) throw new Error(`画布左侧显示 ${count} 个场景，不是预期的 3 个`);
  const outline = [];
  for (let index = 0; index < count; index += 1) {
    const scene = scenes.nth(index);
    await uiClick(scene.locator(":scope > button").first(), `查看第 ${index + 1} 个场景`);
    const layerRows = page.locator(".live-scene-outline > section.active > div > button");
    outline.push({
      index: index + 1,
      title: (await scene.locator(":scope > button strong").innerText()).trim(),
      layers: await layerRows.allInnerTexts(),
      canvasImageCount: await page.locator(".live-phone-canvas > button img").count(),
    });
  }
  await uiClick(scenes.first().locator(":scope > button").first(), "返回第一个场景");
  await saveJson("canvas-outline.json", { capturedAt: nowIso(), planCode, scenes: outline });
}

async function verifyConsoleAfterReload(page) {
  const beforeReloadUrl = page.url();
  await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.locator(".live-editor-header strong", { hasText: ROOM_TITLE }).waitFor({ state: "visible", timeout: 30_000 });
  const scenes = page.locator(".live-scene-outline > section");
  if (await scenes.count() !== 3) throw new Error("刷新 Console 后没有保持三个场景");
  const writePanelButton = page.locator(".live-editor-properties > nav").getByRole("button", { name: "写入草稿", exact: true });
  await uiClick(writePanelButton, "刷新后重新打开写入草稿结果");
  const progress = page.locator(".live-execution-progress");
  await progress.waitFor({ state: "visible", timeout: 30_000 });
  const progressText = (await progress.innerText()).trim();
  if (!progressText.includes("执行成功") || !progressText.includes("仅完成离线测试草稿")) {
    throw new Error("刷新 Console 后没有恢复执行成功和离线测试结果");
  }
  if (page.url() !== beforeReloadUrl || !new URL(page.url()).searchParams.get("run")) {
    throw new Error("刷新 Console 后方案深链没有保持一致");
  }
  await screenshot(page, "08-console-after-refresh");
  await saveJson("console-refresh-verification.json", {
    capturedAt: nowIso(),
    url: page.url(),
    planCode,
    sceneCount: 3,
    executionSuccessVisible: true,
    offlineTestOnlyVisible: true,
  });
}

async function waitForRoomInspection(page) {
  const scope = page.locator(".live-execute-body .live-room-inspection");
  await waitUntil("麦兔房间只读检查", async () => {
    const failure = scope.locator(".live-friendly-error");
    if (await failure.count()) throw new Error((await failure.innerText()).trim());
    return (await scope.locator(".live-inspection-result").count()) > 0;
  }, 180_000, 500);
  const text = (await scope.locator(".live-inspection-result").innerText()).trim();
  if (!text.includes(ROOM_TITLE)) throw new Error("麦兔房间检查未显示预期标题 asser测试");
  if (!text.includes("离线草稿")) throw new Error("麦兔房间不是离线草稿状态");
  return text;
}

const executionStages = [
  ["preparing_materials", "准备素材"],
  ["clearing_draft", "清空草稿"],
  ["building_scenes", "搭建场景"],
  ["writing_scripts", "写入话术"],
  ["verifying_readback", "刷新核对"],
  ["succeeded", "草稿已写入"],
];

function observedExecutionStages(execution) {
  const values = new Set();
  if (execution?.stage) values.add(execution.stage);
  if (execution?.status === "succeeded") values.add("succeeded");
  for (const event of execution?.stage_events || []) {
    if (event?.stage) values.add(event.stage);
  }
  return values;
}

async function captureObservedStages(page, execution) {
  const observed = observedExecutionStages(execution);
  const currentTitle = await page.locator(".live-execution-progress > header strong").first().textContent().catch(() => "");
  for (let index = 0; index < executionStages.length; index += 1) {
    const [stage, title] = executionStages[index];
    if (!observed.has(stage) || stageScreenshots[stage]) continue;
    const timelineHasStage = (await page.locator(".live-execution-progress ol strong", { hasText: title }).count()) > 0;
    const displayMode = currentTitle?.includes(title) ? "current_stage" : timelineHasStage ? "timeline_history" : "response_evidence";
    const filename = await screenshot(page, `execution-${String(index + 1).padStart(2, "0")}-${stage}`, {
      executionStage: stage,
      displayMode,
    });
    stageScreenshots[stage] = { filename, displayMode, capturedAt: nowIso() };
  }
}

async function reopenExecutionPanel(page) {
  const progress = page.locator(".live-execution-progress");
  if (await progress.isVisible().catch(() => false)) return;
  const buttons = page.getByRole("button", { name: "写入草稿", exact: true });
  if (await buttons.count()) await buttons.last().click();
  await progress.waitFor({ state: "visible", timeout: 30_000 });
}

async function waitForExecution(page) {
  await page.locator(".live-execution-progress").waitFor({ state: "visible", timeout: 30_000 });
  const execution = await waitUntil("麦兔测试草稿执行完成", async () => {
    await Promise.allSettled(networkTasks);
    const uiExecution = latestExecutionFromUiResponse();
    let execution = uiExecution;
    try {
      execution = await readOnlyGet(
        `/api/functional-live-room-plans/${encodeURIComponent(planCode)}/execution`,
      );
    } catch {
      // The Console request remains the primary observation while the read-only
      // fallback lets the acceptance run survive a transient browser reload.
    }
    if (!execution || typeof execution !== "object") return false;
    await captureObservedStages(page, execution).catch(() => undefined);
    terminalStatus = execution.status || terminalStatus;
    if (["failed", "reconcile_required", "cancelled"].includes(execution.status)) {
      if (uiExecution?.status !== execution.status) {
        await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 }).catch(() => undefined);
        await reopenExecutionPanel(page).catch(() => undefined);
      }
      await screenshot(page, `execution-terminal-${execution.status}`);
      throw new Error(`草稿执行结束于 ${execution.status}：${JSON.stringify(execution.error || {})}`);
    }
    if (execution.status !== "succeeded") return false;
    if (uiExecution?.status !== "succeeded") {
      await new Promise((resolve) => setTimeout(resolve, 3_000));
      await Promise.allSettled(networkTasks);
      if (latestExecutionFromUiResponse()?.status !== "succeeded") {
        await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
        await reopenExecutionPanel(page);
      }
    }
    return execution;
  }, 1_200_000, 1_000);
  const missingScreenshots = executionStages
    .map(([stage]) => stage)
    .filter((stage) => !stageScreenshots[stage]);
  if (missingScreenshots.length) {
    throw new Error(`执行完成，但缺少阶段截图证据：${missingScreenshots.join(", ")}`);
  }
  return execution;
}

async function readOnlyGet(endpoint) {
  const response = await fetch(`${API_ORIGIN}${endpoint}`, { method: "GET" });
  const text = await response.text();
  const body = jsonValue(text);
  networkEvidence.push({
    at: nowIso(),
    source: "post-run-readonly-get",
    method: "GET",
    path: endpoint,
    status: response.status,
    requestBody: null,
    responseBody: body,
  });
  if (!response.ok) throw new Error(`只读采证 ${endpoint} 返回 ${response.status}`);
  return body;
}

function validateFinalEvidence(plan, execution) {
  const planValidation = validatePlan(plan);
  const result = execution?.result;
  if (plan.execution_status !== "maitu_complete") throw new Error(`方案执行状态不是 maitu_complete：${plan.execution_status}`);
  if (execution?.status !== "succeeded") throw new Error(`执行任务状态不是 succeeded：${execution?.status}`);
  if (!result || result.ready_for_go_live !== false || result.go_live_clicked !== false || result.non_releasable !== true) {
    throw new Error("最终任务证据没有同时满足不可开播、未点击开播和不可发布");
  }
  if (result.verification?.matched !== true || result.verification?.scene_count !== 3) {
    throw new Error("最终麦兔回读没有匹配恰好三个场景");
  }
  if (
    result.layer_order_validation?.passed !== true
    || result.layer_order_validation?.continuous_from_one !== true
    || result.layer_order_validation?.video_never_highest !== true
  ) {
    throw new Error("最终麦兔图层回读未通过连续顺序或视频非最高层检查");
  }
  if (!result.final_readback || typeof result.final_readback !== "object") {
    throw new Error("最终任务缺少麦兔刷新后的完整房间回读");
  }
  return {
    ...planValidation,
    contentTarget: { theme: THEME, goal: GOAL, story: STORY, detailedDesign: DETAILED_DESIGN },
    executionStatus: execution.status,
    verification: result.verification,
    layerOrderValidation: result.layer_order_validation,
    readyForGoLive: result.ready_for_go_live,
    goLiveClicked: result.go_live_clicked,
    nonReleasable: result.non_releasable,
  };
}

async function writeRunArtifacts(status, error) {
  await Promise.allSettled(networkTasks);
  const finishedAt = new Date();
  const blockingConsoleErrors = consoleErrors.filter((item) => !isIgnoredConsoleError(item));
  const errorCount = pageErrors.length + blockingConsoleErrors.length + requestFailures.length + httpErrors.length + (error ? 1 : 0);
  const report = {
    schemaVersion: "assetgraph.live-room-41172-product-e2e.v1",
    runId,
    mode: EXECUTE ? "product_e2e" : "non_destructive_preflight",
    status,
    startedAt: startedAt.toISOString(),
    finishedAt: finishedAt.toISOString(),
    elapsedMs: finishedAt.getTime() - startedAt.getTime(),
    appOrigin: APP_ORIGIN,
    apiOrigin: API_ORIGIN,
    target: { roomId: ROOM_ID, expectedTitle: ROOM_TITLE, theme: THEME, exactSceneCount: 3 },
    planCode: planCode || null,
    projectCode: projectCode || null,
    terminalStatus,
    selectedMaterials,
    clickCount,
    errorCount,
    workflowDurationsMs,
    manualInterventionCount: manualInterventionPoints.length,
    manualInterventionPoints,
    stageScreenshots,
    mutationRequests,
    pageErrors,
    consoleErrors,
    ignoredConsoleErrorCount: consoleErrors.length - blockingConsoleErrors.length,
    requestFailures,
    httpErrors,
    error: error ? String(error.stack || error.message || error) : null,
    interactionLog,
    evidenceFiles: {
      report: "run-report.json",
      network: "network-evidence.json",
      summary: "summary.md",
    },
  };
  await saveJson("network-evidence.json", networkEvidence);
  await saveJson("run-report.json", report);
  const summary = [
    "# 41172 产品端到端验收",
    "",
    `- 模式：${EXECUTE ? "真实产品端到端" : "无写入预检"}`,
    `- 状态：${status}`,
    `- 直播间：${ROOM_ID} / ${ROOM_TITLE}`,
    `- 主题：${THEME}`,
    `- 方案：${planCode || "未创建"}`,
    `- 项目：${projectCode || "未创建"}`,
    `- 耗时：${report.elapsedMs} ms`,
    `- 页面点击：${clickCount} 次`,
    `- 错误：${errorCount} 个`,
    `- 人工介入：${manualInterventionPoints.length} 个`,
    `- 非 GET 请求：${mutationRequests.length} 个，全部由 Console 页面交互触发`,
    "",
    "## 素材选择",
    "",
    ...selectedMaterials.map((item) => `- ${item.matchedLabel}：${item.title}`),
    "",
    "## 说明",
    "",
    EXECUTE
      ? "脚本未直接调用任何生成或执行 mutation API；内容创建、方案生成、房间检查和清空重建均由 Console 页面按钮触发。最终 API 调用仅为 GET 采证。"
      : "本次仅加载真实页面、填写表单并验证素材选择器，没有点击生成、房间检查或写入按钮，不会修改业务数据和麦兔草稿。",
    error ? `\n## 错误\n\n\`${String(error.message || error).replace(/`/g, "'")}\`` : "",
    "",
  ].join("\n");
  await fs.writeFile(path.join(evidenceDir, "summary.md"), summary, "utf8");
  return report;
}

async function main() {
  await fs.mkdir(evidenceDir, { recursive: true });
  const browser = await chromium.launch({
    headless: HEADLESS,
    executablePath: CHROME_PATH,
    args: ["--no-sandbox"],
  });
  const context = await browser.newContext({ viewport: VIEWPORT, ignoreHTTPSErrors: true });
  const page = await context.newPage();

  page.on("pageerror", (error) => pageErrors.push({ at: nowIso(), message: error.message }));
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push({ at: nowIso(), text: message.text(), url: message.location().url || null });
    }
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText || "unknown";
    if (failure !== "net::ERR_ABORTED") requestFailures.push({ at: nowIso(), method: request.method(), path: apiPath(request.url()), failure });
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET") {
      mutationRequests.push({
        at: nowIso(),
        source: "console-page-interaction",
        method: request.method(),
        path: apiPath(request.url()),
        requestBody: jsonValue(request.postData() || ""),
      });
    }
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      httpErrors.push({ at: nowIso(), method: response.request().method(), path: apiPath(response.url()), status: response.status() });
    }
    if (!isJsonApiResponse(response)) return;
    const task = (async () => {
      let body;
      try {
        body = jsonValue(await response.text());
      } catch (error) {
        body = { captureError: String(error.message || error) };
      }
      networkEvidence.push({
        at: nowIso(),
        source: "console-page-network",
        method: response.request().method(),
        path: apiPath(response.url()),
        status: response.status(),
        requestBody: jsonValue(response.request().postData() || ""),
        responseBody: body,
      });
    })();
    networkTasks.push(task);
  });

  let runError;
  let status = "failed";
  try {
    await timed("loadAndFill", async () => {
      const response = await page.goto(`${APP_ORIGIN}/console/production/live-rooms`, {
        waitUntil: "domcontentloaded",
        timeout: 30_000,
      });
      if (!response?.ok()) throw new Error(`直播间页面返回 ${response?.status() || "无响应"}`);
      await page.getByRole("heading", { name: "生成直播间方案", exact: true }).waitFor({ state: "visible", timeout: 30_000 });
      await fill(page.getByRole("textbox", { name: "直播间 ID", exact: true }), ROOM_ID, "直播间 ID");
      await fill(page.getByRole("textbox", { name: "麦兔当前标题", exact: true }), ROOM_TITLE, "麦兔当前标题");
      await fill(page.getByRole("textbox", { name: "生成目标", exact: true }), GOAL, "生成目标");
      await fill(page.getByRole("textbox", { name: "主题", exact: true }), THEME, "主题");
      await fill(page.getByRole("textbox", { name: "故事", exact: true }), STORY, "故事");
      await fill(page.getByRole("textbox", { name: "详细设计", exact: true }), DETAILED_DESIGN, "详细设计");
      await waitUntil("素材列表加载", async () => {
        if (await page.locator(".live-asset-choice").first().isVisible().catch(() => false)) return true;
        const apiFailure = httpErrors.find((item) => item.path.startsWith("/api/assets?limit=") && item.status >= 400);
        if (apiFailure) throw new Error(`素材列表接口返回 ${apiFailure.status}，请先完成迁移、素材引导并重启后端`);
        await Promise.allSettled(networkTasks);
        const assetResponse = latestNetworkBody((item) => item.method === "GET" && item.path.startsWith("/api/assets?limit="));
        if (Array.isArray(assetResponse) && assetResponse.length === 0) throw new Error("素材库为空，请先完成 63 份本地素材引导");
        return false;
      }, 45_000, 250);
      await selectAssetForRole(page, "background", ["背景"]);
      await selectAssetForRole(page, "set_surface", ["桌面与底图"]);
      await selectAssetForRole(page, "product", ["商品展示"]);
      await selectAssetForRole(page, "video", ["辅助视频"]);
      await selectAssetForRole(page, "digital_human", ["数字人"]);
      await selectAssetForRole(page, "top", ["品牌标题", "前景装饰", "促销文案"]);
      const submit = page.getByRole("button", { name: "生成直播间方案", exact: true });
      if (!(await submit.isEnabled())) throw new Error("输入与素材均已填写，但生成按钮仍不可用");
      await screenshot(page, "01-input-and-material-selection");
      await page.waitForTimeout(800);
      await Promise.allSettled(networkTasks);
      assertNoBrowserErrors("页面预检");
    });

    if (!EXECUTE) {
      status = "preflight_passed";
      terminalStatus = "not_requested";
      console.log(`无写入预检通过，未创建项目或修改 41172。证据：${evidenceDir}`);
    } else {
      await timed("createContentAndPlan", async () => {
        await createPlanThroughUi(page);
      });
      await Promise.allSettled(networkTasks);
      assertNoBrowserErrors("内容与方案生成后");
      await timed("inspectCanvas", async () => {
        await inspectGeneratedCanvas(page);
        await screenshot(page, "02-generated-three-scene-canvas");
      });
      await timed("inspectRoomAndConfirmReset", async () => {
        await uiClick(page.locator(".live-editor-actions").getByRole("button", { name: "写入草稿", exact: true }), "打开写入草稿面板");
        await page.locator(".live-execute-body").waitFor({ state: "visible", timeout: 15_000 });
        await screenshot(page, "03-write-panel-before-room-inspection");
        const readButton = page.locator(".live-execute-body .live-room-inspection").getByRole("button", { name: "读取房间", exact: true });
        if (await readButton.count()) await uiClick(readButton, "读取麦兔房间");
        await waitForRoomInspection(page);
        await screenshot(page, "04-room-inspection-readback");
        const deletion = page.locator(".live-delete-confirm");
        await deletion.waitFor({ state: "visible", timeout: 15_000 });
        const sceneChecks = deletion.locator("input[type=checkbox]");
        if (!(await sceneChecks.count())) throw new Error("房间检查没有列出可确认的现有场景");
        for (let index = 0; index < await sceneChecks.count(); index += 1) {
          const checkbox = sceneChecks.nth(index);
          if (!(await checkbox.isChecked())) await uiClick(checkbox, `确认删除现有场景 ${index + 1}`);
        }
        await screenshot(page, "05-delete-confirmation-all-scenes");
        const acknowledgement = page.locator(".live-test-use-ack input[type=checkbox]");
        if (!(await acknowledgement.isChecked())) await uiClick(acknowledgement, "确认仅用于离线测试草稿");
        const executeButton = page.getByRole("button", { name: "写入麦兔测试草稿", exact: true });
        if (!(await executeButton.isEnabled())) throw new Error("房间与场景均已确认，但写入麦兔测试草稿按钮仍不可用");
        await screenshot(page, "06-ready-to-replace-test-draft");
        await uiClick(executeButton, "写入麦兔测试草稿（真实清空重建）");
      });
      const execution = await timed("executeAndReadback", async () => waitForExecution(page));
      await screenshot(page, "07-product-e2e-success");
      await timed("finalReadOnlyEvidence", async () => {
        const [finalPlan, finalExecution] = await Promise.all([
          readOnlyGet(`/api/functional-live-room-plans/${encodeURIComponent(planCode)}`),
          readOnlyGet(`/api/functional-live-room-plans/${encodeURIComponent(planCode)}/execution`),
        ]);
        const validation = validateFinalEvidence(finalPlan, finalExecution);
        await saveJson("final-plan.json", finalPlan);
        await saveJson("final-execution.json", finalExecution);
        await saveJson("final-maitu-readback.json", finalExecution.result.final_readback);
        await saveJson("final-validation.json", { capturedAt: nowIso(), planCode, projectCode, validation });
      });
      await timed("consoleRefreshVerification", async () => verifyConsoleAfterReload(page));
      await Promise.allSettled(networkTasks);
      assertNoBrowserErrors("最终回读与 Console 刷新后");
      terminalStatus = execution.status;
      status = "passed";
      console.log(`41172 产品端到端验收通过。证据：${evidenceDir}`);
    }
  } catch (error) {
    runError = error;
    status = "failed";
    console.error(error);
    await screenshot(page, "failure-state").catch(() => undefined);
  } finally {
    await writeRunArtifacts(status, runError);
    await browser.close();
  }
  if (runError) throw runError;
}

await main();
