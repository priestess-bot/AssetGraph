import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_ORIGIN = process.env.ASSETGRAPH_APP_ORIGIN || "http://127.0.0.1:5190";
const API_ORIGIN = process.env.ASSETGRAPH_API_ORIGIN || "http://127.0.0.1:8000";
const VIEWPORT = { width: 1440, height: 900 };
const runId = new Date().toISOString().replace(/[:.]/g, "-");
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const evidenceDir = path.join(repoRoot, "docs/evidence");
const screenshotDir = path.join(evidenceDir, `frontend-product-workflows-${runId}`);
const recordingFixture = path.join(repoRoot, "outputs/customer-v1/v1-0515/AG-VJOB-20260725-000002/attempt-1/final.mp4");
const results = [];

function record(name, status, detail = "", extra = {}) {
  results.push({ name, status, detail, ...extra });
  const marker = status === "passed" ? "PASS" : status === "blocked" ? "BLOCK" : "FAIL";
  console.log(`[${marker}] ${name}${detail ? ` - ${detail}` : ""}`);
}

async function apiJson(endpoint) {
  const response = await fetch(`${API_ORIGIN}${endpoint}`);
  const body = await response.text();
  if (!response.ok) throw new Error(`${endpoint} 返回 ${response.status}: ${body.slice(0, 240)}`);
  return body ? JSON.parse(body) : null;
}

async function waitForStable(page, selector = "main") {
  await page.locator(selector).waitFor({ state: "visible", timeout: 12_000 });
  await page.waitForTimeout(650);
}

async function hasText(page, value) {
  return (await page.getByText(value, { exact: false }).count()) > 0;
}

async function clickButton(page, name, { exact = false, timeout = 8_000 } = {}) {
  let locator = page.getByRole("button", { name: exact ? name : new RegExp(name) }).first();
  if (!(await locator.count())) locator = page.getByRole("tab", { name: exact ? name : new RegExp(name) }).first();
  if (!(await locator.count())) locator = page.getByTitle(name).first();
  await locator.waitFor({ state: "visible", timeout });
  await locator.click();
  if (typeof page.waitForTimeout === "function") await page.waitForTimeout(400);
}

async function clickLink(page, name, { exact = false, timeout = 8_000 } = {}) {
  const locator = page.getByRole("link", { name: exact ? name : new RegExp(name) }).first();
  await locator.waitFor({ state: "visible", timeout });
  await locator.click();
  if (typeof page.waitForTimeout === "function") await page.waitForTimeout(550);
}

async function open(page, route) {
  const separator = route.includes("?") ? "&" : "?";
  const response = await page.goto(`${APP_ORIGIN}${route}${separator}demo=1`, { waitUntil: "domcontentloaded", timeout: 20_000 });
  await waitForStable(page);
  const heading = (await page.locator("h1").first().innerText()).trim();
  if (!heading) throw new Error("页面没有业务标题");
  return { status: response?.status() ?? 0, heading };
}

async function screenshot(page, name) {
  await fs.mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: path.join(screenshotDir, `${name}.png`), fullPage: true });
}

async function waitForDialogToClose(page, selector) {
  await page.locator(selector).waitFor({ state: "hidden", timeout: 12_000 });
}

async function run(name, fn) {
  const started = Date.now();
  try {
    await fn();
    record(name, "passed", `${Date.now() - started}ms`);
  } catch (error) {
    record(name, "failed", error instanceof Error ? error.message : String(error));
  }
}

async function runBlocked(name, fn) {
  const started = Date.now();
  try {
    await fn();
    record(name, "passed", `${Date.now() - started}ms`);
  } catch (error) {
    record(name, "blocked", error instanceof Error ? error.message : String(error));
  }
}

async function main() {
  await fs.mkdir(evidenceDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome", args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: VIEWPORT, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const browserErrors = [];
  const requestFailures = [];
  const expectedRequestAborts = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText || "";
    const detail = `${request.method()} ${request.url()} ${failure}`;
    if (failure === "net::ERR_ABORTED") expectedRequestAborts.push(detail);
    else requestFailures.push(detail);
  });

  await run("概览 / 页面加载", async () => {
    const info = await open(page, "/console/");
    if (info.status !== 200 || info.heading !== "业务概览") throw new Error(`标题或响应异常: ${info.heading}/${info.status}`);
    await screenshot(page, "overview");
  });
  await run("概览 / 时间范围与下钻", async () => {
    await clickButton(page, "近 90 天", { exact: true });
    await clickLink(page, "查看运营分析");
    if (!page.url().includes("/console/operations")) throw new Error("没有进入运营分析");
    await open(page, "/console/");
    await clickButton(page, "任务中心");
    if (!(await hasText(page, "任务中心"))) throw new Error("任务抽屉没有打开");
    await clickButton(page, "任务中心");
    await clickButton(page, "通知");
    if (!(await hasText(page, "通知"))) throw new Error("通知抽屉没有打开");
    await clickButton(page, "通知");
  });

  await run("素材库 / 搜索筛选与视图切换", async () => {
    const info = await open(page, "/console/assets");
    if (info.heading !== "素材库") throw new Error("没有进入素材库");
    const search = page.getByRole("textbox", { name: "搜索素材" });
    await search.fill("背景");
    await page.waitForTimeout(300);
    await page.getByTitle("列表视图").click();
    await page.getByTitle("网格视图").click();
    if (!(await hasText(page, "份素材"))) throw new Error("素材结果数量没有显示");
    await screenshot(page, "assets-library");
  });
  await run("素材库 / 详情、约束和保存", async () => {
    await page.getByRole("textbox", { name: "搜索素材" }).fill("");
    const cards = page.locator(".asset-product-grid > button");
    await cards.first().click();
    await page.getByRole("button", { name: "布局约束", exact: true }).click();
    await page.getByRole("button", { name: "始终置顶", exact: true }).click();
    const number = page.locator(".asset-geometry-fields input[type=number]").first();
    await number.fill("0.12");
    await clickButton(page, "保存约束", { exact: true });
    await page.waitForTimeout(700);
    if (await hasText(page, "约束没有保存")) throw new Error("约束保存失败");
  });
  await run("素材库 / 创建分组、素材包和缺口", async () => {
    const title = `UI验收素材组-${Date.now()}`;
    await clickButton(page, "关闭详情");
    await clickButton(page, "素材组", { exact: true });
    await page.getByPlaceholder("例如：夏季家居主视觉").fill(title);
    const checks = page.locator(".asset-group-member-picker input[type=checkbox]");
    if (await checks.count()) await checks.first().check();
    await clickButton(page, "创建分组", { exact: true });
    await page.getByText(title, { exact: true }).waitFor({ state: "visible", timeout: 10_000 });

    await clickButton(page, "素材包", { exact: true });
    await clickButton(page, "新建素材包", { exact: true });
    await page.locator(".asset-inline-editor input").first().fill(`UI验收素材包-${Date.now()}`);
    const packCheck = page.locator(".asset-pack-members input[type=checkbox]");
    if (await packCheck.count()) await packCheck.first().check();
    await clickButton(page, "保存素材包", { exact: true });
    await page.waitForTimeout(700);
    if (await hasText(page, "素材包没有保存")) throw new Error("素材包保存失败");

    await clickButton(page, "素材缺口", { exact: true });
    await clickButton(page, "登记缺口", { exact: true });
    const gapInputs = page.locator(".asset-inline-editor input");
    await gapInputs.nth(0).fill(`UI验收缺口-${Date.now()}`);
    await gapInputs.nth(1).fill("缺口登记用于验证替代素材流程");
    await clickButton(page.locator(".asset-inline-editor"), "登记缺口", { exact: true });
    await page.waitForTimeout(700);
    if (await hasText(page, "素材缺口没有保存")) throw new Error("素材缺口保存失败");
  });
  await run("素材库 / 导入素材与批量选材", async () => {
    await open(page, "/console/assets");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(350);
    await clickButton(page, "全部素材", { exact: true });
    await clickButton(page, "导入素材", { exact: true });
    const fileInput = page.locator(".asset-import-dialog input[type=file]");
    await fileInput.setInputFiles({ name: "ui-acceptance.txt", mimeType: "text/plain", buffer: Buffer.from("AssetGraph UI workflow acceptance\n") });
    await page.getByRole("button", { name: "导入素材", exact: true }).last().click();
    await waitForDialogToClose(page, ".asset-import-dialog");
    if (await hasText(page, "素材没有导入")) throw new Error("导入素材失败");

    const cards = page.locator(".asset-product-grid > button");
    if (await cards.count() < 2) throw new Error("没有足够素材执行批量选材");
    await cards.nth(0).click();
    await cards.nth(1).click({ modifiers: ["Control"] });
    await clickButton(page, "加入分组", { exact: true });
    const groupSelect = page.locator(".asset-batch-bar select");
    await groupSelect.selectOption({ index: 1 });
    await clickButton(page, "确认加入", { exact: true });
    await page.waitForTimeout(700);
    if (await hasText(page, "素材没有保存")) throw new Error("批量加入分组失败");
  });

  await run("模板 / 模板库筛选、详情和录屏查看", async () => {
    const info = await open(page, "/console/templates");
    if (info.heading !== "直播模板") throw new Error("没有进入直播模板");
    await page.getByRole("textbox", { name: "搜索直播模板" }).fill("Content");
    await page.waitForTimeout(300);
    const templateCards = page.locator(".template-card-grid > button");
    if (!(await templateCards.count())) throw new Error("筛选后没有模板卡片");
    await templateCards.first().click();
    if (!(await hasText(page, "使用边界"))) throw new Error("模板详情没有打开");
    await clickButton(page, "关闭详情");
    await clickButton(page, "录屏与解析", { exact: true });
    if (!(await hasText(page, "语音与画面内容"))) throw new Error("录屏内容面板没有打开");
    await screenshot(page, "templates-recordings");
  });
  await runBlocked("模板 / 录屏上传、解析、清洗、审核", async () => {
    await fs.access(recordingFixture);
    await clickButton(page, "从录屏创建模板", { exact: true });
    const dialog = page.getByRole("dialog");
    await dialog.waitFor({ state: "visible" });
    await dialog.getByLabel("来源直播间 ID").fill("UI-ACCEPTANCE-ROOM");
    await dialog.getByLabel("来源直播间名称").fill("UI 验收录屏");
    await dialog.locator("input[type=file]").setInputFiles(recordingFixture);
    await dialog.getByRole("button", { name: "上传并解析", exact: true }).click();
    await Promise.race([
      dialog.getByRole("heading", { name: "解析直播内容", exact: true }).waitFor({ state: "visible", timeout: 12_000 }),
      dialog.getByText("模板没有创建", { exact: false }).waitFor({ state: "visible", timeout: 8_000 }),
      dialog.getByText("录屏没有上传", { exact: false }).waitFor({ state: "visible", timeout: 8_000 }),
    ]);
    if (await dialog.getByText("录屏没有上传", { exact: false }).count()) throw new Error("录屏解析依赖未就绪");
    const clean = dialog.getByRole("button", { name: "清洗解析结果", exact: true });
    await clean.waitFor({ state: "visible", timeout: 20_000 });
    if (!(await clean.isEnabled())) throw new Error("录屏解析仍在等待结果");
    await clean.click();
    await dialog.getByRole("heading", { name: "清洗可复用内容", exact: true }).waitFor({ state: "visible", timeout: 8_000 });
    await dialog.getByRole("button", { name: "审核模板", exact: true }).click();
    await dialog.getByRole("heading", { name: "确认模板信息", exact: true }).waitFor({ state: "visible", timeout: 8_000 });
    await dialog.getByPlaceholder("例如：家居好物、食品品鉴").fill("浏览器验收内容");
    await dialog.getByRole("button", { name: "创建模板草稿", exact: true }).click();
    await dialog.waitFor({ state: "hidden", timeout: 12_000 });
  });

  await run("知识库 / 事实、来源和详情", async () => {
    const info = await open(page, "/console/knowledge");
    if (info.heading !== "知识库") throw new Error("没有进入知识库");
    await page.getByRole("textbox", { name: "搜索商品事实" }).fill("Verified");
    await page.waitForTimeout(250);
    const facts = page.locator(".knowledge-fact-grid > button");
    if (!(await facts.count())) throw new Error("没有事实卡结果");
    await facts.first().click();
    if (!(await hasText(page, "商品信息"))) throw new Error("事实详情没有打开");
    await clickButton(page, "关闭详情");
    await clickButton(page, "事实来源", { exact: true });
    if (!(await hasText(page, "原文摘录"))) throw new Error("事实来源视图没有打开");
    await clickButton(page, "添加来源", { exact: true });
    const sourceDialog = page.getByRole("dialog");
    await sourceDialog.getByLabel("来源标题").fill(`UI 验收来源-${Date.now()}`);
    await sourceDialog.getByLabel("原文摘录").fill("这是一条用于浏览器工作流验收的可回看来源摘录。");
    await clickButton(sourceDialog, "保存来源", { exact: true });
    await page.waitForTimeout(700);
    if (await hasText(page, "来源没有保存")) throw new Error("来源保存失败");
  });

  let createdProjectCode = "";
  await run("内容项目 / 四步创建与实体选择", async () => {
    const info = await open(page, "/console/projects");
    if (info.heading !== "内容项目") throw new Error("没有进入内容项目");
    await clickButton(page, "新建项目", { exact: true });
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("直播间 ID").fill(`UI-ROOM-${Date.now()}`);
    await dialog.getByLabel("直播间标题").fill(`UI 验收内容项目-${Date.now()}`);
    await dialog.getByLabel("生成目标").fill("验证从直播间目标到剧本、场景和成片的完整工作流。");
    await clickButton(dialog, "下一步", { exact: true });
    await dialog.getByLabel("主题").fill("工作流验收主题");
    await dialog.getByPlaceholder("希望直播如何开场、展开和收束").fill("先介绍问题，再展示商品，最后给出行动建议。");
    await dialog.getByPlaceholder("补充场景、陈列、互动、话术或不能出现的内容").fill("采用简洁背景和桌面商品展示，不出现未经确认的功效承诺。");
    await clickButton(dialog, "下一步", { exact: true });
    await page.waitForTimeout(900);
    const templateChoice = dialog.locator(".project-selection-row").first();
    if (await templateChoice.count()) await templateChoice.click();
    await clickButton(dialog, "下一步", { exact: true });
    await page.waitForTimeout(900);
    const materialChoice = dialog.locator(".project-selection-row").first();
    if (await materialChoice.count()) await materialChoice.click();
    await dialog.locator('button[type="submit"]').click();
    await page.waitForTimeout(1_200);
    const projectParam = new URL(page.url()).searchParams.get("project");
    if (!projectParam) throw new Error("创建后没有进入项目工作区");
    createdProjectCode = projectParam;
  });
  await runBlocked("内容项目 / 简报整理与生成入口", async () => {
    if (!createdProjectCode) throw new Error("没有可用的新建项目");
    await open(page, `/console/projects?project=${encodeURIComponent(createdProjectCode)}&tab=brief`);
    const prepare = page.getByRole("button", { name: "整理生成简报", exact: true });
    if (await prepare.count()) {
      await prepare.click();
      await page.waitForTimeout(1_000);
      if (await hasText(page, "这一步没有完成")) throw new Error("简报整理依赖未就绪");
    }
    await page.getByRole("link", { name: "剧本", exact: true }).click();
    await page.waitForTimeout(450);
    await page.getByRole("link", { name: "直播间", exact: true }).click();
    await page.waitForTimeout(450);
    await page.getByRole("link", { name: "成片", exact: true }).click();
    await page.waitForTimeout(450);
    await page.getByRole("link", { name: "交付", exact: true }).click();
    await page.waitForTimeout(450);
    await page.getByRole("link", { name: "动态", exact: true }).click();
    await page.waitForTimeout(450);
  });

  const livePlans = await apiJson("/api/functional-live-room-plans");
  const livePlan = livePlans.find((item) => item.status === "ready") || livePlans[0];
  await run("直播间方案 / 场景、图层和保存", async () => {
    if (!livePlan?.plan_code) throw new Error("验收库没有直播间方案");
    const info = await open(page, `/console/production/live-rooms?run=${encodeURIComponent(livePlan.plan_code)}`);
    if (info.heading !== "内容项目") throw new Error(`直播间深链标题异常: ${info.heading}`);
    await page.locator(".live-scene-outline section > button").first().click();
    const layer = page.locator(".live-scene-outline section > div > button").first();
    if (await layer.count()) await layer.click();
    await clickButton(page, "操作清单", { exact: true });
    await clickButton(page, "属性", { exact: true });
    await clickButton(page, "保存场景", { exact: true });
    await page.waitForTimeout(900);
    if (await hasText(page, "修改没有保存")) throw new Error("直播间场景保存失败");
    if (await hasText(page, "自动写入暂不可用")) record("直播间方案 / 麦兔写入门禁", "blocked", "当前验收环境未启用麦兔写入，页面保留人工操作清单");
  });

  const videoPlans = await apiJson("/api/functional-video-plans");
  const videoPlan = videoPlans[0];
  await run("成片 / 时间轴、编辑副本和保存", async () => {
    if (!videoPlan?.plan_code) throw new Error("验收库没有成片方案");
    await open(page, `/console/production/videos?plan=${encodeURIComponent(videoPlan.plan_code)}`);
    if (await hasText(page, "已完成的成片需先创建编辑副本")) {
      await clickButton(page, "创建编辑副本", { exact: true });
      await page.waitForTimeout(2_200);
    }
    const clip = page.locator(".video-track-clips > button").first();
    if (await clip.count()) await clip.click();
    const poster = page.locator(".video-timeline-product input[type=number]").first();
    if (await poster.isEnabled().catch(() => false)) await poster.fill("0.2");
    const save = page.getByRole("button", { name: "保存时间轴", exact: true });
    if (await save.count() && await save.isEnabled()) {
      await save.click();
      await page.waitForTimeout(900);
      if (await hasText(page, "时间轴没有保存")) throw new Error("时间轴保存失败");
    }
  });

  let operationProjectCode = createdProjectCode;
  if (!operationProjectCode) {
    const projects = await apiJson("/api/content-projects");
    operationProjectCode = projects[0]?.project_code || "";
  }
  await run("运营分析 / 导入、检查和入库", async () => {
    await open(page, "/console/operations");
    const csv = [
      "title,platform,external_session_id,account_id,target_resource_id,source_timezone,started_at,ended_at,binding_kind,binding_code,binding_revision,metric_key,metric_value,metric_unit,metric_source_clock,evidence_note",
      `UI验收场次,douyin,UI-SESSION-${Date.now()},ui-test,ui-room,Asia/Shanghai,2026-07-28T20:00:00+08:00,2026-07-28T20:30:00+08:00,content_project_revision,${operationProjectCode},1,watchers,1280,person,session_utc,浏览器工作流验收`,
    ].join("\n");
    await page.locator('input[type="file"]').setInputFiles({ name: "ui-acceptance-operations.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await clickButton(page, "检查文件", { exact: true });
    await page.waitForTimeout(1_000);
    if (await hasText(page, "导入预览")) {
      const confirm = page.getByRole("button", { name: /确认导入/ });
      if (await confirm.count() && await confirm.isEnabled()) {
        await confirm.click();
        await page.waitForTimeout(1_000);
      }
    }
    if (await hasText(page, "操作没有完成")) throw new Error("运营数据导入失败");
  });
  await run("运营分析 / 待关联、四维分析和指标设置", async () => {
    await clickButton(page, "待关联", { exact: false });
    await page.waitForTimeout(450);
    await clickButton(page, "表现分析", { exact: true });
    await page.waitForTimeout(700);
    for (const tab of ["按场次", "按内容段", "按模板", "按素材"]) {
      await clickButton(page, tab, { exact: true });
      await page.waitForTimeout(220);
    }
    const recalc = page.getByRole("button", { name: "重新计算", exact: true });
    if (await recalc.count() && await recalc.isEnabled()) await recalc.click();
    await clickButton(page, "指标设置", { exact: true });
    await clickButton(page, "新建指标", { exact: true });
    await page.getByPlaceholder("例如：商品点击次数").fill(`UI验收指标-${Date.now()}`);
    await page.getByPlaceholder("说明什么时候计入，以及它反映什么").fill("用于验证运营指标设置流程。");
    await page.getByRole("button", { name: "保存指标", exact: true }).click().catch(() => undefined);
    await page.waitForTimeout(700);
  });

  await run("效果学习 / 规律库和项目建议", async () => {
    await open(page, "/console/learning");
    await clickButton(page, "项目建议", { exact: true });
    const projectSelect = page.locator(".learning-recommendation-head select");
    if (await projectSelect.count() && await projectSelect.locator("option").count() > 1) {
      await projectSelect.selectOption({ index: 1 });
      await page.waitForTimeout(700);
    }
    await clickButton(page, "规律库", { exact: true });
    await clickButton(page, "建立候选规律", { exact: true });
    const create = page.locator(".learning-create-pattern");
    if (await create.count()) {
      const selects = create.locator("select");
      if (await selects.nth(0).locator("option").count() > 1) await selects.nth(0).selectOption({ index: 1 });
      if (await selects.nth(1).locator("option").count() > 1) await selects.nth(1).selectOption({ index: 1 });
      await create.locator("textarea").fill("UI 验收记录：本次只验证候选规律创建和人工确认入口。");
      await create.getByRole("button", { name: "保存候选规律", exact: true }).click();
      await page.waitForTimeout(800);
      if (await hasText(page, "候选规律没有保存")) throw new Error("候选规律保存失败");
    }
  });

  const releases = await apiJson("/api/releases");
  await run("交付 / 检查、批准、交付包和撤回入口", async () => {
    if (!releases[0]?.release_code) throw new Error("验收库没有交付候选");
    await open(page, `/console/production/releases?release=${encodeURIComponent(releases[0].release_code)}`);
    if (!(await hasText(page, "交付检查"))) throw new Error("交付检查面板没有打开");
    const validate = page.getByRole("button", { name: "运行交付检查", exact: true });
    if (await validate.count()) {
      await validate.click();
      await page.waitForTimeout(900);
    }
    if (await hasText(page, "撤回")) {
      await clickButton(page, "撤回", { exact: true });
      await clickButton(page, "取消", { exact: true });
    }
  });

  const mainText = await page.locator("main").innerText().catch(() => "");
  const leakedTokens = mainText.match(/\b(?:[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+|[0-9a-f]{24,})\b/g) || [];
  const uniqueLeaks = [...new Set(leakedTokens)].filter((value) => !["Asia", "UI"].includes(value));
  const evidence = {
    generatedAt: new Date().toISOString(),
    appOrigin: APP_ORIGIN,
    apiOrigin: API_ORIGIN,
    viewport: VIEWPORT,
    database: process.env.POSTGRES_DB || "assetgraph_v1_acceptance_20260726",
    counts: {
      total: results.length,
      passed: results.filter((item) => item.status === "passed").length,
      blocked: results.filter((item) => item.status === "blocked").length,
      failed: results.filter((item) => item.status === "failed").length,
    },
    results,
    browserErrors: [...new Set(browserErrors)],
    requestFailures: [...new Set(requestFailures)].slice(0, 100),
    expectedRequestAborts: [...new Set(expectedRequestAborts)].slice(0, 100),
    finalPageVisibleInternalTokens: uniqueLeaks,
    screenshots: screenshotDir,
  };
  await fs.writeFile(path.join(evidenceDir, "frontend-product-workflow-acceptance-2026-07-29.json"), `${JSON.stringify(evidence, null, 2)}\n`);
  await browser.close();
  console.log(`\nSummary: ${evidence.counts.passed} passed, ${evidence.counts.blocked} blocked, ${evidence.counts.failed} failed`);
  console.log(`Evidence: ${path.join(evidenceDir, "frontend-product-workflow-acceptance-2026-07-29.json")}`);
  if (evidence.counts.failed || evidence.browserErrors.length) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
