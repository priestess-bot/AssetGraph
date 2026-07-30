import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

const root = resolve(import.meta.dirname, "..");
const formalPages = [
  "src/console/ConsoleApp.tsx",
  "src/console/ErrorBoundary.tsx",
  "src/console/BusinessOverviewPage.tsx",
  "src/assets/AssetLibraryProductPage.tsx",
  "src/live-research/TemplateLibraryProductPage.tsx",
  "src/knowledge/KnowledgeProductPage.tsx",
  "src/content/ProjectHubPage.tsx",
  "src/live-rooms/LiveRoomEditorProductPage.tsx",
  "src/videos/VideoEditorProductPage.tsx",
  "src/releases/DeliveryProductPanel.tsx",
  "src/operations/OperationsProductPage.tsx",
  "src/learning/LearningProductPage.tsx",
];

const internalToken = /\b[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+\b/;
const forbiddenVisibleTerms = /\b(?:fingerprint|schema(?:Version)?|errorCode|traceId|JSON\.stringify)\b/i;
const forbiddenElements = new Set(["pre", "code"]);
const failures = [];

function report(source, node, message) {
  const position = source.getLineAndCharacterOfPosition(node.getStart(source));
  failures.push(`${source.fileName}:${position.line + 1}:${position.character + 1} ${message}`);
}

function inspectVisibleExpression(source, expression) {
  const text = expression.getText(source);
  if (forbiddenVisibleTerms.test(text)) report(source, expression, `用户可见表达式包含技术字段: ${text.slice(0, 100)}`);
  if ((ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) && internalToken.test(expression.text)) {
    report(source, expression, `用户可见文案包含内部编号: ${expression.text}`);
  }
}

for (const relativePath of formalPages) {
  const absolutePath = resolve(root, relativePath);
  const sourceText = readFileSync(absolutePath, "utf8");
  const source = ts.createSourceFile(relativePath, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

  function visit(node) {
    if (ts.isJsxElement(node)) {
      const tag = node.openingElement.tagName.getText(source).toLowerCase();
      if (forbiddenElements.has(tag)) report(source, node.openingElement, `正式页面禁止使用 <${tag}>`);
    }
    if (ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(source).toLowerCase();
      if (forbiddenElements.has(tag)) report(source, node, `正式页面禁止使用 <${tag}>`);
    }
    if (ts.isJsxText(node)) {
      const visible = node.getText(source).trim();
      if (internalToken.test(visible) || forbiddenVisibleTerms.test(visible)) report(source, node, `用户可见文案包含技术值: ${visible}`);
    }
    if (ts.isJsxExpression(node) && node.expression && ts.isJsxElement(node.parent)) inspectVisibleExpression(source, node.expression);
    ts.forEachChild(node, visit);
  }
  visit(source);
}

if (failures.length) {
  process.stderr.write(`产品文案门禁未通过:\n${failures.join("\n")}\n`);
  process.exit(1);
}

process.stdout.write(`产品文案门禁通过，共检查 ${formalPages.length} 个正式页面。\n`);
