import type { ProductFactCard } from "../knowledge/api";
import type { RoomTemplate } from "../live-research/types";
import { WorkbenchApiError } from "../workbench/api";

export interface ContentTemplateRecommendation {
  templateCode: string;
  score: number;
  signals: string[];
}

export function contentRecoveryStep(error: unknown): string {
  if (!(error instanceof WorkbenchApiError)) return "检查当前输入后重试。";
  const detail = typeof error.detail === "object" && error.detail !== null ? error.detail as Record<string, unknown> : {};
  const nested = typeof detail.detail === "object" && detail.detail !== null ? detail.detail as Record<string, unknown> : detail;
  const code = error.problem?.code ?? (typeof nested.code === "string" ? nested.code : "");
  if (code.includes("FACT_CARD")) return "请先到知识库批准新的事实版本，再返回项目继续生成。";
  if (code.includes("TEMPLATE")) return "请检查所选模板是否已发布并可用于当前项目。";
  return "刷新项目内容，确认最新版本后重试。";
}

export function recommendContentTemplates(templates: RoomTemplate[], input: string): ContentTemplateRecommendation[] {
  const normalized = input.trim().toLocaleLowerCase();
  if (!normalized) return [];
  return templates.map((template) => {
    const signals: string[] = [];
    let score = 0;
    const category = template.contentStrategy.targetCategory.trim();
    if (category && normalized.includes(category.toLocaleLowerCase())) {
      score += 100;
      signals.push(`品类：${category}`);
    }
    for (const module of template.contentStrategy.programOutline) {
      if ([module.title, module.purpose].some((value) => value.trim().length >= 2 && normalized.includes(value.trim().toLocaleLowerCase()))) {
        score += 20;
        signals.push(`模块：${module.title || module.moduleKey}`);
      }
    }
    for (const tag of template.contentStrategy.compatibilityTags) {
      if (tag.trim().length >= 2 && normalized.includes(tag.trim().toLocaleLowerCase())) {
        score += 12;
        signals.push(`标签：${tag.trim()}`);
      }
    }
    return { templateCode: template.template_code, score, signals: Array.from(new Set(signals)) };
  }).filter((item) => item.score > 0).sort((left, right) => right.score - left.score || left.templateCode.localeCompare(right.templateCode));
}

function approvedContent(fact: ProductFactCard): Record<string, unknown> {
  return fact.versions.find((version) => version.versionNumber === fact.currentApprovedVersion && version.status === "approved")?.content ?? {};
}

function contentText(fact: ProductFactCard, key: string): string {
  const value = approvedContent(fact)[key];
  return typeof value === "string" ? value.trim() : "";
}

function contentList(fact: ProductFactCard, key: string): string[] {
  const value = approvedContent(fact)[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function findFactCardConflicts(facts: ProductFactCard[], selectedCodes: string[], platform = ""): string[] {
  const selected = facts.filter((fact) => selectedCodes.includes(fact.factCardCode));
  const conflicts: string[] = [];
  const byProduct = new Map<string, ProductFactCard[]>();
  for (const fact of selected) {
    const productCode = fact.productCode || contentText(fact, "product_code");
    if (productCode) byProduct.set(productCode, [...(byProduct.get(productCode) ?? []), fact]);
    const platforms = contentList(fact, "applicable_platforms").map((item) => item.toLowerCase());
    if (platform && platforms.length && !platforms.includes("all") && !platforms.includes(platform.toLowerCase())) conflicts.push(`${fact.factCardCode} 不适用于 ${platform}`);
  }
  for (const [productCode, productFacts] of byProduct) {
    if (productFacts.length < 2) continue;
    for (const key of ["product_name", "brand", "category", "positioning"]) {
      const values = new Set(productFacts.map((fact) => contentText(fact, key)).filter(Boolean));
      if (values.size > 1) conflicts.push(`${productCode} 的 ${key} 在 ${productFacts.map((fact) => fact.factCardCode).join("/")} 中不一致`);
    }
  }
  return Array.from(new Set(conflicts));
}
