import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_ORIGIN = process.env.ASSETGRAPH_APP_ORIGIN || "http://127.0.0.1:5190";
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const screenshotPath = path.join(
  repoRoot,
  "docs/evidence/screenshots/customer-v1-v1-0524-material-bootstrap-page.png",
);
const evidencePath = path.join(
  repoRoot,
  "docs/evidence/customer-v1-v1-0524-material-bootstrap-page.json",
);
const viewport = { width: 1600, height: 1000 };
const expectedRoleLabels = [
  "背景",
  "桌面与底图",
  "商品展示",
  "数字人",
  "品牌标题",
  "促销文案",
  "前景装饰",
  "辅助视频",
  "音色",
];
const expectedConstraintCopy = [
  "位置与大小",
  "保持原始宽高比",
  "图层关系",
  "禁止成为最上层图层",
  "位于这些素材上方",
  "位于这些素材下方",
  "商品需摆放在背景桌面上，并位于背景上方",
  "保存约束",
];
const rawRoleTokens = [
  "set_surface",
  "product_display",
  "digital_human",
  "brand_title",
  "promotion_text",
  "decoration_foreground",
  "supporting_video",
];

function intersection(left, right) {
  if (!left || !right) return null;
  const width = Math.max(0, Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x));
  const height = Math.max(0, Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y));
  return { width, height, area: width * height };
}

async function box(locator) {
  const value = await locator.boundingBox();
  return value && Object.fromEntries(Object.entries(value).map(([key, item]) => [key, Math.round(item * 100) / 100]));
}

async function main() {
  await fs.mkdir(path.dirname(screenshotPath), { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const context = await browser.newContext({ viewport, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const nonGetRequests = [];
  const failedRequests = [];
  const apiErrors = [];
  const httpErrors = [];
  const ignoredHttpErrors = [];
  const pageErrors = [];
  const consoleErrors = [];
  let apiAssetCount;

  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET") {
      nonGetRequests.push({ method: request.method(), url: request.url() });
    }
  });
  page.on("requestfailed", (request) => {
    const error = request.failure()?.errorText || "unknown";
    if (error !== "net::ERR_ABORTED") failedRequests.push({ method: request.method(), url: request.url(), error });
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      const item = { method: response.request().method(), url: response.url(), status: response.status() };
      const pathname = new URL(response.url()).pathname;
      if (response.status() === 404 && pathname.endsWith("/favicon.ico")) {
        ignoredHttpErrors.push({ ...item, reason: "浏览器默认站点图标请求，不影响业务页面" });
      } else {
        httpErrors.push(item);
      }
    }
    if (response.url().includes("/api/") && response.status() >= 400) {
      apiErrors.push({ method: response.request().method(), url: response.url(), status: response.status() });
    }
    if (response.url().includes("/api/assets?limit=") && response.ok()) {
      void response.json().then((body) => { apiAssetCount = Array.isArray(body) ? body.length : undefined; });
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push({ text: message.text(), location: message.location() });
  });

  let evidence;
  try {
    const response = await page.goto(`${APP_ORIGIN}/console/assets`, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    if (!response?.ok()) throw new Error(`素材页面返回 ${response?.status() || "无响应"}`);
    await page.locator(".asset-product-page").getByRole("heading", { name: "素材库", exact: true }).waitFor({ state: "visible", timeout: 20_000 });
    const cards = page.locator(".asset-product-grid > button");
    await cards.first().waitFor({ state: "visible", timeout: 30_000 });
    await page.getByText("64 份素材", { exact: true }).waitFor({ state: "visible", timeout: 20_000 });
    const cardCount = await cards.count();
    if (cardCount !== 64) throw new Error(`页面显示 ${cardCount} 份素材，不是预期的 64 份`);

    const cardSubtitles = await page.locator(".asset-card-copy > small").allInnerTexts();
    const roleLabelsFound = expectedRoleLabels.filter((label) => cardSubtitles.some((text) => text.includes(label)));
    const missingRoleLabels = expectedRoleLabels.filter((label) => !roleLabelsFound.includes(label));
    const rawRoleTokensVisible = rawRoleTokens.filter((token) => cardSubtitles.some((text) => text.includes(token)));
    if (missingRoleLabels.length) throw new Error(`素材卡缺少中文用途：${missingRoleLabels.join("、")}`);
    if (rawRoleTokensVisible.length) throw new Error(`素材卡暴露内部用途变量：${rawRoleTokensVisible.join("、")}`);

    let selectedCard;
    for (let index = 0; index < cardCount; index += 1) {
      const card = cards.nth(index);
      const subtitle = await card.locator(".asset-card-copy > small").innerText();
      const image = card.locator(".asset-thumb img");
      if (subtitle.includes("图片") && subtitle.includes("背景") && await image.count()) {
        await image.waitFor({ state: "visible", timeout: 10_000 });
        await image.scrollIntoViewIfNeeded();
        const loaded = await image.evaluate((node) => {
          if (node.complete) return node.naturalWidth > 0 && node.naturalHeight > 0;
          return new Promise((resolve) => {
            node.addEventListener("load", () => resolve(node.naturalWidth > 0 && node.naturalHeight > 0), { once: true });
            node.addEventListener("error", () => resolve(false), { once: true });
          });
        });
        if (loaded) {
          selectedCard = card;
          break;
        }
      }
    }
    if (!selectedCard) throw new Error("没有找到已成功加载预览的背景图片素材");
    const selectedTitle = (await selectedCard.locator(".asset-card-copy > strong").innerText()).trim();
    await selectedCard.click();

    const inspector = page.locator(".asset-product-inspector");
    await inspector.waitFor({ state: "visible", timeout: 15_000 });
    const initialInfoText = await inspector.locator(".asset-inspector-content").innerText();
    const requiredInfoLabels = ["媒体类型", "可用于", "素材用途"];
    const missingInfoLabels = requiredInfoLabels.filter((label) => !initialInfoText.includes(label));
    if (missingInfoLabels.length) throw new Error(`素材详情缺少中文字段：${missingInfoLabels.join("、")}`);

    await inspector.getByRole("button", { name: "布局约束", exact: true }).click();
    const constraintPanel = inspector.locator(".asset-constraint-product");
    await constraintPanel.waitFor({ state: "visible", timeout: 20_000 });
    const constraintText = await constraintPanel.innerText();
    const constraintCopyFound = expectedConstraintCopy.filter((text) => constraintText.includes(text));
    const missingConstraintCopy = expectedConstraintCopy.filter((text) => !constraintCopyFound.includes(text));
    const rawConstraintTokensVisible = rawRoleTokens.filter((token) => constraintText.includes(token));
    if (missingConstraintCopy.length) throw new Error(`布局约束缺少中文文案：${missingConstraintCopy.join("、")}`);
    if (rawConstraintTokensVisible.length) throw new Error(`布局约束暴露内部变量：${rawConstraintTokensVisible.join("、")}`);

    const grid = page.locator(".asset-product-grid");
    const preview = inspector.locator(".asset-inspector-preview");
    const previewImage = preview.locator("img").first();
    await previewImage.waitFor({ state: "visible", timeout: 10_000 });
    const inspectorPreviewLoaded = await previewImage.evaluate((node) => node.complete && node.naturalWidth > 0 && node.naturalHeight > 0);
    if (!inspectorPreviewLoaded) throw new Error("素材详情没有加载真实图片预览");
    const inspectorContent = inspector.locator(".asset-inspector-content");
    const constraintControls = inspector.locator(".asset-constraint-controls");
    const rectangles = {
      grid: await box(grid),
      inspector: await box(inspector),
      preview: await box(preview),
      previewImage: await box(previewImage),
      inspectorContent: await box(inspectorContent),
      constraintControls: await box(constraintControls),
    };
    const overlaps = {
      gridAndInspector: intersection(rectangles.grid, rectangles.inspector),
      previewAndInspectorContent: intersection(rectangles.preview, rectangles.inspectorContent),
      imageAndConstraintControls: intersection(rectangles.previewImage, rectangles.constraintControls),
    };
    const inspectorRect = rectangles.inspector;
    const overflowElements = await inspector.locator("input, select, textarea, button").evaluateAll((nodes, bounds) => nodes.flatMap((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return [];
      const horizontalOverflow = rect.left < bounds.x - 0.5 || rect.right > bounds.x + bounds.width + 0.5;
      return horizontalOverflow ? [{ tag: node.tagName, text: (node.textContent || "").trim().slice(0, 80), left: rect.left, right: rect.right }] : [];
    }), inspectorRect);
    const noOverlap = Object.values(overlaps).every((value) => value?.area === 0);
    if (!noOverlap) throw new Error(`素材预览、表单或主网格发生重叠：${JSON.stringify(overlaps)}`);
    if (overflowElements.length) throw new Error(`详情控件横向溢出：${JSON.stringify(overflowElements)}`);
    if (nonGetRequests.length) throw new Error(`只读验收触发了修改请求：${JSON.stringify(nonGetRequests)}`);
    if (failedRequests.length) throw new Error(`素材页面存在网络失败：${JSON.stringify(failedRequests)}`);
    if (apiErrors.length) throw new Error(`素材页面存在 API 错误：${JSON.stringify(apiErrors)}`);
    if (httpErrors.length) throw new Error(`素材页面存在资源错误：${JSON.stringify(httpErrors)}`);
    if (pageErrors.length) throw new Error(`素材页面存在脚本错误：${JSON.stringify(pageErrors)}`);
    const ignoredConsoleErrors = consoleErrors.filter((item) => {
      if (!/Failed to load resource.*404/u.test(item.text)) return false;
      try {
        return new URL(item.location.url).pathname.endsWith("/favicon.ico");
      } catch {
        return false;
      }
    });
    const blockingConsoleErrors = [...consoleErrors];
    for (const ignored of ignoredConsoleErrors) {
      const index = blockingConsoleErrors.indexOf(ignored);
      if (index >= 0) blockingConsoleErrors.splice(index, 1);
    }
    if (blockingConsoleErrors.length) throw new Error(`素材页面存在控制台错误：${JSON.stringify(blockingConsoleErrors)}`);

    await page.screenshot({ path: screenshotPath, fullPage: false });
    evidence = {
      schemaVersion: "assetgraph.material-bootstrap-page-acceptance.v1",
      status: "passed",
      capturedAt: new Date().toISOString(),
      url: page.url(),
      viewport,
      screenshot: path.relative(repoRoot, screenshotPath),
      readOnly: {
        passed: nonGetRequests.length === 0,
        nonGetRequests,
      },
      assets: {
        expectedCount: 64,
        apiCount: apiAssetCount,
        domCardCount: cardCount,
        toolbarCountText: "64 份素材",
        selectedForInspection: selectedTitle,
        selectedPreviewLoaded: true,
        inspectorPreviewLoaded,
      },
      localization: {
        passed: missingRoleLabels.length === 0 && missingInfoLabels.length === 0 && missingConstraintCopy.length === 0 && rawRoleTokensVisible.length === 0 && rawConstraintTokensVisible.length === 0,
        roleLabelsFound,
        missingRoleLabels,
        infoLabelsFound: requiredInfoLabels,
        constraintCopyFound,
        rawRoleTokensVisible,
        rawConstraintTokensVisible,
      },
      layout: {
        passed: noOverlap && overflowElements.length === 0,
        rectangles,
        overlaps,
        overflowElements,
        previewObjectFit: await previewImage.evaluate((node) => getComputedStyle(node).objectFit),
      },
      runtime: {
        failedRequests,
        apiErrors,
        httpErrors,
        ignoredHttpErrors,
        pageErrors,
        consoleErrors,
        ignoredConsoleErrors,
      },
    };
  } catch (error) {
    evidence = {
      schemaVersion: "assetgraph.material-bootstrap-page-acceptance.v1",
      status: "failed",
      capturedAt: new Date().toISOString(),
      url: page.url(),
      viewport,
      screenshot: path.relative(repoRoot, screenshotPath),
      readOnly: { passed: nonGetRequests.length === 0, nonGetRequests },
      runtime: { failedRequests, apiErrors, httpErrors, ignoredHttpErrors, pageErrors, consoleErrors },
      error: String(error.stack || error.message || error),
    };
    await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => undefined);
    throw error;
  } finally {
    await fs.writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
    await browser.close();
  }
  console.log(JSON.stringify({ status: evidence.status, screenshot: screenshotPath, evidence: evidencePath }, null, 2));
}

await main();
