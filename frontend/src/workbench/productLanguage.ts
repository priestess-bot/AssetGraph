const PRODUCT_LABELS: Record<string, string> = {
  active: "进行中",
  approved: "已批准",
  archived: "已停用",
  associational: "相关性证据",
  available: "可用",
  blocked: "已阻断",
  cancelling: "正在取消",
  claimed: "处理中",
  completed: "已完成",
  confirmed: "已确认",
  consumed: "已使用",
  delivered: "已交付",
  delivery_failed: "交付失败",
  descriptive: "描述性证据",
  draft: "草稿",
  error: "需要处理",
  escalated: "需要协助",
  executable: "可直接构建",
  expired: "已过期",
  failed: "未完成",
  inactive: "已停用",
  insufficient_data: "数据不足",
  local_only: "仅用于本地成片",
  manual_only: "需人工完成",
  maitu_bound: "可用于麦兔",
  matched: "一致",
  mismatch: "存在差异",
  none: "暂无",
  open: "待处理",
  operator: "运营人员",
  administrator: "管理员",
  reviewer: "审核人员",
  pending: "待确认",
  processing: "处理中",
  published: "已发布",
  qc_failed: "质检未通过",
  qc_passed: "质检通过",
  queued: "等待开始",
  ready: "可使用",
  reconcile_required: "需要核对",
  reference_only: "仅供参考",
  rejected: "已驳回",
  rendered: "已生成",
  restricted: "限制使用",
  revoked: "已撤销",
  running: "处理中",
  stale: "内容已更新",
  stored: "已入库",
  succeeded: "已完成",
  success: "已完成",
  template_preview: "模板预览",
  unclassified: "待分类",
  unknown: "待确认",
  unsupported: "暂不支持",
  verified: "已验证",
  verified_layout: "布局已验证",
  approximate: "近似布局",
  waiting_human: "等待人工处理",
  warning: "需要关注",
  asset: "素材",
  capture_session: "录屏",
  content_project: "内容项目",
  effect_estimate: "效果规律",
  fact_card: "事实卡",
  live_room_template: "直播模板",
  legacy_workbench_run: "直播间方案",
  release: "交付",
  workflow_run: "后台任务",
  background: "背景",
  background_music: "背景音乐",
  brand_title: "品牌标题",
  decoration_foreground: "前景装饰",
  digital_human: "数字人",
  foreground_overlay: "前景贴片",
  decoration: "装饰",
  product_image: "商品图",
  product_display: "商品展示",
  product_video: "商品视频",
  promotion_text: "促销文案",
  sound_effect: "音效",
  supporting_video: "辅助视频",
  avatar: "数字人",
  voice: "音色",
  music: "音乐",
  font: "字体",
  sticker: "贴片",
  script_snippet: "话术片段",
  image: "图片",
  img: "图片",
  video: "视频",
  vid: "视频",
  audio: "音频",
  aud: "音频",
  document: "文档",
  doc: "文档",
  webpage: "网页",
  export: "平台导出",
  human: "人工确认",
  internal: "内部使用",
  font_file: "字体文件",
  other: "其他",
  topmost: "始终置顶",
  bottommost: "始终置底",
  preserve_aspect: "保持比例",
  region: "位置范围",
  size: "尺寸",
  scale: "缩放",
  relative: "相对位置",
  superseded: "已被新版本替代",
};

const PROBLEM_COPY: Record<string, { title: string; impact: string; nextStep: string }> = {
  CONSOLE_REQUEST_FAILED: {
    title: "暂时无法加载页面数据",
    impact: "当前页面的信息可能不完整，尚未执行任何操作。",
    nextStep: "请检查网络连接后重试。",
  },
  REQUEST_VALIDATION_FAILED: {
    title: "有些内容需要补充或修改",
    impact: "本次提交尚未保存。",
    nextStep: "请检查标出的字段后再次提交。",
  },
  LINEAGE_INPUT_STALE: {
    title: "项目使用的内容已有更新",
    impact: "继续操作可能会使用旧版本素材或内容。",
    nextStep: "请查看最新内容并确认是否更新当前项目。",
  },
  RELEASE_RECONCILE_REQUIRED: {
    title: "交付结果需要核对",
    impact: "目前无法确认目标平台是否已完整接收内容。",
    nextStep: "请打开项目的交付页核对结果。",
  },
};

const INTERNAL_TOKEN = /\b[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+\b/g;
const TECHNICAL_VALUE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;
const INTERNAL_ID = /^(?:AG|ALERT|APPROVAL|AUTH|BUILD|CAP|CONTENT|DRAFT|EFFECT|FACT|INV|MT|OPS|PACK|RELEASE|RUN|TASK|TPL)-[A-Z0-9-]+$/i;
const EMBEDDED_INTERNAL_ID = /\b(?:AG|ALERT|APPROVAL|AUTH|BUILD|CAP|CONTENT|DRAFT|EFFECT|FACT|INV|MT|OPS|PACK|RELEASE|RUN|TASK|TPL)-[A-Z0-9-]+\b/gi;
const LONG_HEX_ID = /\b[0-9a-f]{24,}\b/gi;

/** Cleans entity names at the presentation boundary without changing API identifiers. */
export function productTitle(value: string | null | undefined, fallback = "未命名内容"): string {
  const normalized = value?.trim();
  if (!normalized) return fallback;
  const cleaned = normalized
    .replace(EMBEDDED_INTERNAL_ID, "")
    .replace(LONG_HEX_ID, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!cleaned) return fallback;
  const mapped = PRODUCT_LABELS[cleaned.toLowerCase()];
  if (mapped) return mapped;
  if (TECHNICAL_VALUE.test(cleaned)) return productLabel(cleaned, fallback);
  return cleaned;
}

export function productLabel(value: string | null | undefined, fallback = "待确认"): string {
  const normalized = value?.trim();
  if (!normalized) return fallback;
  const mapped = PRODUCT_LABELS[normalized.toLowerCase()];
  if (mapped) return mapped;
  if (/[^\x00-\x7F]/.test(normalized)) return normalized;
  INTERNAL_TOKEN.lastIndex = 0;
  const isInternal = TECHNICAL_VALUE.test(normalized) || INTERNAL_ID.test(normalized) || INTERNAL_TOKEN.test(normalized);
  INTERNAL_TOKEN.lastIndex = 0;
  if (isInternal) return fallback;
  return normalized;
}

export function productCopy(value: string | null | undefined, fallback: string): string {
  const normalized = value?.trim();
  if (!normalized) return fallback;
  const withoutCodes = normalized.replace(INTERNAL_TOKEN, "").replace(/[（(]\s*[）)]/g, "").replace(/\s{2,}/g, " ").trim();
  if (!withoutCodes || (!/[^\x00-\x7F]/.test(withoutCodes) && TECHNICAL_VALUE.test(withoutCodes))) return fallback;
  return withoutCodes;
}

export function entityLabel(value: string | null | undefined): string {
  return productLabel(value, "业务内容");
}

export function problemPresentation(problem: {
  code?: string;
  state?: string;
  impact?: string;
  nextStep?: string;
}): { title: string; impact: string; nextStep: string } {
  const registered = problem.code ? PROBLEM_COPY[problem.code] : undefined;
  if (registered) return registered;
  const title = problem.state === "insufficient_data"
    ? "现有信息不足以继续"
    : problem.state === "stale"
      ? "页面内容已有更新"
      : problem.state === "reconcile_required"
        ? "结果需要人工核对"
        : "这一步暂时没有完成";
  return {
    title,
    impact: productCopy(problem.impact, "当前操作没有生效，已有内容保持不变。"),
    nextStep: productCopy(problem.nextStep, "请检查页面中的输入后重试。"),
  };
}

export function containsInternalToken(value: string): boolean {
  INTERNAL_TOKEN.lastIndex = 0;
  const found = INTERNAL_TOKEN.test(value) || TECHNICAL_VALUE.test(value.trim());
  INTERNAL_TOKEN.lastIndex = 0;
  return found;
}

export const productLabels = PRODUCT_LABELS;
