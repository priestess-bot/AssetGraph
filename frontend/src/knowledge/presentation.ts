import { productTitle } from "../workbench/productLanguage";

const KNOWLEDGE_TEXT: Record<string, string> = {
  "compatibility fact": "基础商品事实",
  "searchable verified product facts": "已核验商品信息",
  "lineage fact": "可追溯商品事实",
  "citation fact": "有来源的商品事实",
  fact: "商品事实",
  "legacy fact": "历史商品事实",
  "searchable product": "可搜索商品",
  "lineage product": "可追溯商品",
  "verified product": "已核验商品",
  "verified daily product": "已核验的日常商品",
  "for a traceable demonstration": "用于来源追溯演示",
  "for a hosted gathering": "适合聚会场景",
  "the replacement fact.": "这是更新后的已核验事实。",
  "the original verified fact.": "这是原始的已核验事实。",
  "a newer fact": "这是更新后的商品事实。",
  "a verified fact": "这是已核验的商品事实。",
  "reviewable product specification": "待审核商品说明",
  "incomplete product specification": "信息不完整的商品说明",
  "replacement product specification": "更新版商品说明",
  "corrected product specification": "修订版商品说明",
  "lineage source": "商品事实来源",
  "search validation source": "商品信息核验来源",
  "controlled source export": "商品资料导出",
  "approved spec": "已批准商品说明",
  "content rule source": "内容规则依据",
  "source-backed fact": "商品事实依据",
  "product sheet": "商品说明书",
  "the product includes a verified 12-month warranty.": "该商品包含已核验的 12 个月质保服务。",
  "the product warranty wording is incomplete.": "该商品的质保说明信息不完整。",
  "the product has a verified 24-month warranty.": "该商品已核验的质保期为 24 个月。",
  "the product has a verified 12-month warranty.": "该商品已核验的质保期为 12 个月。",
  "the product warranty is verified for the supported market.": "该商品的质保信息已在适用市场完成核验。",
  "the source export states an approved warranty boundary.": "来源资料明确了已经批准的质保范围。",
  "the device includes a verified 12-month warranty.": "该设备包含已核验的 12 个月质保服务。",
  "do not promise a price unless it has been approved.": "未经批准，不得承诺商品价格。",
  "verified warranty is 12 months.": "已核验的质保期为 12 个月。",
  "warranty is 12 months.": "质保期为 12 个月。",
  "the document is incomplete.": "文档信息不完整。",
  "the source specification was superseded.": "该来源说明已被更新版本替代。",
};

function translated(value: string): string | undefined {
  return KNOWLEDGE_TEXT[value.trim().toLowerCase()];
}

/** Localizes known legacy/demo records without changing their persisted evidence. */
export function knowledgeTitle(value: string | null | undefined, fallback = "未命名内容"): string {
  const normalized = productTitle(value, fallback);
  if (/^ui\s*验收来源(?:-\d+)?$/i.test(normalized)) return "界面验收来源";
  return translated(normalized) ?? normalized;
}

export function knowledgeText(value: string | null | undefined, fallback = "未填写"): string {
  const normalized = value?.trim();
  if (!normalized) return fallback;
  return translated(normalized) ?? normalized;
}

export function knowledgeTextList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string").map((item) => knowledgeText(item));
}
