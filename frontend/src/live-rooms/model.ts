import type { LibraryAsset } from "../assets/api";
import { WorkbenchApiError } from "../workbench/api";

export type LayerBand = "bottom" | "surface" | "content" | "host" | "top";

export interface OrderableLayer {
  key: string;
  role: string;
  zOrder: number;
}

export interface NormalizedGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const LIVE_ROOM_ROLE_OPTIONS = [
  "background",
  "set_surface",
  "supporting_video",
  "product_display",
  "digital_human",
  "promotion_text",
  "brand_title",
  "decoration_foreground",
] as const;

const BAND_ORDER: Record<LayerBand, number> = {
  bottom: 0,
  surface: 1,
  content: 2,
  host: 3,
  top: 4,
};

export function layerBand(role: string): LayerBand {
  if (role === "background") return "bottom";
  if (role === "set_surface") return "surface";
  if (["brand_title", "promotion_text", "decoration_foreground"].includes(role)) return "top";
  if (role === "digital_human") return "host";
  return "content";
}

export function layerBandLabel(role: string): string {
  const band = layerBand(role);
  if (band === "bottom") return "固定底层";
  if (band === "surface") return "桌面与底图";
  if (band === "content") return "商品与视频";
  if (band === "host") return "主播层";
  return "固定高层";
}

export function normalizeLayerOrder<T extends OrderableLayer>(layers: T[]): T[] {
  return [...layers]
    .sort((left, right) => {
      const bandDifference = BAND_ORDER[layerBand(left.role)] - BAND_ORDER[layerBand(right.role)];
      if (bandDifference) return bandDifference;
      const orderDifference = left.zOrder - right.zOrder;
      return orderDifference || left.key.localeCompare(right.key);
    })
    .map((layer, index) => ({ ...layer, zOrder: index + 1 }));
}

export function moveLayer<T extends OrderableLayer>(layers: T[], key: string, direction: -1 | 1): T[] {
  const normalized = normalizeLayerOrder(layers);
  const index = normalized.findIndex((layer) => layer.key === key);
  if (index < 0) return normalized;
  const band = layerBand(normalized[index].role);
  const candidateIndexes = normalized.flatMap((layer, position) => layerBand(layer.role) === band ? [position] : []);
  const positionInBand = candidateIndexes.indexOf(index);
  const target = candidateIndexes[positionInBand + direction];
  if (target === undefined) return normalized;
  const next = [...normalized];
  [next[index], next[target]] = [next[target], next[index]];
  return next.map((layer, position) => ({ ...layer, zOrder: position + 1 }));
}

export function canMoveLayer<T extends OrderableLayer>(layers: T[], key: string, direction: -1 | 1): boolean {
  const normalized = normalizeLayerOrder(layers);
  const index = normalized.findIndex((layer) => layer.key === key);
  if (index < 0) return false;
  const selectedBand = layerBand(normalized[index].role);
  const candidateIndexes = normalized.flatMap((layer, position) => layerBand(layer.role) === selectedBand ? [position] : []);
  const positionInBand = candidateIndexes.indexOf(index);
  return candidateIndexes[positionInBand + direction] !== undefined;
}

export function materialRolesForScene(existingRoles: string[], availableRoles: string[], sceneIndex: number): string[] {
  const available = new Set(availableRoles.map((role) => role === "product_image" ? "product_display" : role));
  const persistent = ["background", "set_surface", "digital_human", "brand_title", "decoration_foreground"];
  const sceneSpecific = sceneIndex === 0
    ? []
    : sceneIndex === 1
      ? ["supporting_video", "product_display"]
      : ["product_display", "promotion_text"];
  const existing = existingRoles.map((role) => role === "product_image" ? "product_display" : role);
  return [...new Set([...persistent, ...sceneSpecific, ...existing])].filter((role) => available.has(role));
}

export function pendingRightsAreOnlyBlocker(blockedReasons: string[]): boolean {
  const pending = blockedReasons.filter((reason) => /^asset_rights_not_approved:[^:]+:pending$/u.test(reason));
  return pending.length > 0 && blockedReasons.every((reason) => reason === "GATE_ASSET_RIGHTS_BLOCKED" || pending.includes(reason));
}

export function isAllowedTestRoom(roomId: string, expectedTitle: string): boolean {
  return roomId === "41172" && expectedTitle === "asser测试";
}

export interface StableIdempotencyState {
  key: string;
  fingerprint: string;
}

export function stableIdempotencyKey(
  state: StableIdempotencyState,
  fingerprint: string,
  createKey: () => string = () => crypto.randomUUID(),
): string {
  if (state.fingerprint && state.fingerprint !== fingerprint) state.key = createKey();
  state.fingerprint = fingerprint;
  return state.key;
}

export function roomInspectionFailureMessage(message?: string): string {
  if (message && /[\u3400-\u9fff]/u.test(message)) return message;
  const normalized = (message ?? "").toLowerCase();
  if (normalized.includes("title")) return "读取到的直播间标题与页面填写不一致。";
  if (normalized.includes("login") || normalized.includes("auth")) return "麦兔登录状态已失效，暂时无法读取直播间。";
  if (normalized.includes("worker") || normalized.includes("browser")) return "本地执行器暂时无法读取麦兔页面。";
  return "本地执行器没有完成本次房间读取。";
}

export function reconciliationWasRecorded(execution?: {
  status: string;
  stage: string;
  stageEvents: Array<{ stage: string }>;
}): boolean {
  return Boolean(
    execution
    && execution.status === "cancelled"
    && (execution.stage === "reconciled" || execution.stageEvents.some((event) => event.stage === "reconciled")),
  );
}

export function geometryRange(geometry: NormalizedGeometry, key: keyof NormalizedGeometry): { min: number; max: number } {
  if (key === "x") return { min: 0, max: Math.max(0, 1 - geometry.width) };
  if (key === "y") return { min: 0, max: Math.max(0, 1 - geometry.height) };
  if (key === "width") return { min: 0.01, max: Math.max(0.01, 1 - geometry.x) };
  return { min: 0.01, max: Math.max(0.01, 1 - geometry.y) };
}

export function updateGeometry(geometry: NormalizedGeometry, key: keyof NormalizedGeometry, value: number): NormalizedGeometry {
  const range = geometryRange(geometry, key);
  return { ...geometry, [key]: Math.min(range.max, Math.max(range.min, value)) };
}

export interface AssetSelectionStatus {
  selectable: boolean;
  readyForDraft: boolean;
  label: string;
  reason: string;
  tone: "success" | "warning" | "neutral" | "danger";
}

export function assetSelectionStatus(asset: LibraryAsset): AssetSelectionStatus {
  if (["archived", "deleted"].includes(asset.status)) {
    return { selectable: false, readyForDraft: false, label: "已停用", reason: "素材已停用，不能加入新方案。", tone: "neutral" };
  }
  if (["restricted", "revoked"].includes(asset.rightsStatus)) {
    return { selectable: false, readyForDraft: false, label: "不可使用", reason: "素材使用范围受限，不能加入当前方案。", tone: "danger" };
  }
  if (["unavailable", "unclassified"].includes(asset.executionCapability)) {
    return { selectable: false, readyForDraft: false, label: "待整理", reason: "素材尚未完成用途和执行方式整理。", tone: "neutral" };
  }
  if (asset.classificationReviewStatus === "review_required") {
    return { selectable: true, readyForDraft: false, label: "待复核", reason: "可以参与方案比较，写入前需要人工确认素材用途和约束。", tone: "warning" };
  }
  if (asset.executionCapability === "reference_only") {
    return { selectable: true, readyForDraft: false, label: "仅供参考", reason: "可以参与画面设计，但不能直接写入麦兔。", tone: "warning" };
  }
  if (asset.executionCapability === "local_only") {
    return { selectable: true, readyForDraft: false, label: "待绑定麦兔", reason: "可以参与方案生成，写入草稿前需要绑定麦兔素材。", tone: "warning" };
  }
  if (asset.rightsStatus === "pending") {
    return { selectable: true, readyForDraft: true, label: "仅限测试草稿", reason: "使用状态仍待确认，只能写入离线测试房，不能发布。", tone: "warning" };
  }
  return { selectable: true, readyForDraft: true, label: "可写入草稿", reason: "已具备当前草稿所需的素材绑定。", tone: "success" };
}

export function materialUsageLabel(roles: string[]): string {
  const values: string[] = [];
  if (roles.some((role) => ["background", "set_surface", "digital_human", "brand_title", "decoration_foreground"].includes(role))) values.push("全场");
  if (roles.some((role) => ["supporting_video", "product_display"].includes(role))) values.push("商品介绍段");
  if (roles.some((role) => ["product_display", "promotion_text"].includes(role))) values.push("总结互动段");
  return [...new Set(values)].join("、") || "按场景需求选用";
}

export const EXECUTION_STAGE_COPY: Record<string, { title: string; detail: string }> = {
  queued: { title: "等待执行器", detail: "任务已经进入本地执行队列。" },
  preparing_materials: { title: "准备素材", detail: "正在核对所有素材都能在麦兔中使用。" },
  verifying_room: { title: "核对房间", detail: "正在重新确认房间标题、直播状态和场景清单。" },
  inspecting_room: { title: "读取房间", detail: "正在读取麦兔中的当前草稿。" },
  clearing_draft: { title: "清空草稿", detail: "正在按确认清单移除旧场景和旧素材。" },
  building_scenes: { title: "搭建场景", detail: "正在创建场景并按约束放置图层。" },
  writing_scripts: { title: "写入话术", detail: "正在把三段内容写入对应场景。" },
  verifying_readback: { title: "刷新核对", detail: "正在刷新麦兔并逐层核对最终结果。" },
  succeeded: { title: "草稿已写入", detail: "麦兔刷新后的场景、图层和话术均已核对。" },
  failed: { title: "草稿写入未完成", detail: "任务已停止，没有继续执行后续步骤。" },
  reconcile_required: { title: "需要核对现场", detail: "麦兔现场与任务记录不一致，需要先核对再继续。" },
  reconciled: { title: "旧任务已核对并关闭", detail: "旧任务不会重放，请按最新房间现场创建新任务。" },
  cancelled: { title: "旧任务已关闭", detail: "任务已安全终止，不会继续修改草稿。" },
};

export function executionStageCopy(stage: string, status?: string): { title: string; detail: string } {
  return EXECUTION_STAGE_COPY[stage] ?? EXECUTION_STAGE_COPY[status ?? ""] ?? { title: "正在处理草稿", detail: "执行器正在完成当前步骤。" };
}

export function generatedProjectTitle(theme: string, goal: string, now = new Date()): string {
  const subject = theme.trim() || goal.trim().replace(/[。！？\n].*$/u, "").slice(0, 30) || "直播内容";
  const stamp = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0"), String(now.getHours()).padStart(2, "0"), String(now.getMinutes()).padStart(2, "0")].join("");
  return `${subject} - 直播间方案 - ${stamp}`;
}

export function designBriefInput(input: { goal: string; theme: string; story: string; detailedDesign: string }): string {
  return [
    `生成目标：${input.goal.trim()}`,
    input.theme.trim() ? `主题：${input.theme.trim()}` : "",
    input.story.trim() ? `故事：${input.story.trim()}` : "",
    input.detailedDesign.trim() ? `详细设计：${input.detailedDesign.trim()}` : "",
  ].filter(Boolean).join("\n");
}

function chineseText(value: unknown): string | undefined {
  return typeof value === "string" && /[\u3400-\u9fff]/u.test(value) ? value : undefined;
}

export function friendlyRequestError(error: unknown, fallback: string): { title: string; detail: string; nextStep: string; retryable: boolean } {
  if (error instanceof WorkbenchApiError) {
    return {
      title: chineseText(error.problem?.message) ?? fallback,
      detail: chineseText(error.problem?.impact) ?? (error.status === 409 ? "页面中的信息已经变化，本次操作没有继续。" : "当前步骤没有完成，已保留此前成功的结果。"),
      nextStep: chineseText(error.problem?.nextStep) ?? (error.status === 409 ? "刷新当前状态后重新提交。" : "检查页面提示后重试当前步骤。"),
      retryable: error.problem?.retryable ?? error.status >= 500,
    };
  }
  return { title: fallback, detail: "当前步骤没有完成，已保留此前成功的结果。", nextStep: "检查服务连接后重试当前步骤。", retryable: true };
}
