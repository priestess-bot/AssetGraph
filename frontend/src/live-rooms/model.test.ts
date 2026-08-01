import { describe, expect, it } from "vitest";
import type { LibraryAsset } from "../assets/api";
import {
  assetSelectionStatus,
  designBriefInput,
  executionStageCopy,
  generatedProjectTitle,
  geometryRange,
  isAllowedTestRoom,
  materialRolesForScene,
  materialUsageLabel,
  moveLayer,
  normalizeLayerOrder,
  pendingRightsAreOnlyBlocker,
  reconciliationWasRecorded,
  roomInspectionFailureMessage,
  stableIdempotencyKey,
  updateGeometry,
} from "./model";

function asset(overrides: Partial<LibraryAsset> = {}): LibraryAsset {
  return {
    assetCode: "AG-IMG-001",
    title: "商品主图",
    originalFilename: "product.png",
    assetType: "IMG",
    mediaKind: "image",
    materialRoles: ["product_display"],
    executionCapability: "maitu_bound",
    status: "stored",
    rightsStatus: "approved",
    classificationReviewStatus: "confirmed",
    classificationEvidence: {},
    ...overrides,
  };
}

describe("live room presentation model", () => {
  it("compiles hard layer bands into a unique bottom-to-top order", () => {
    const layers = normalizeLayerOrder([
      { key: "video", role: "supporting_video", zOrder: 99 },
      { key: "foreground", role: "decoration_foreground", zOrder: 1 },
      { key: "background", role: "background", zOrder: 40 },
      { key: "host", role: "digital_human", zOrder: 2 },
      { key: "table", role: "set_surface", zOrder: 30 },
    ]);

    expect(layers.map((item) => item.key)).toEqual(["background", "table", "video", "host", "foreground"]);
    expect(layers.map((item) => item.zOrder)).toEqual([1, 2, 3, 4, 5]);
  });

  it("moves a layer only inside its constrained band", () => {
    const layers = normalizeLayerOrder([
      { key: "background", role: "background", zOrder: 1 },
      { key: "product", role: "product_display", zOrder: 2 },
      { key: "video", role: "supporting_video", zOrder: 3 },
      { key: "host", role: "digital_human", zOrder: 4 },
    ]);

    expect(moveLayer(layers, "video", -1).map((item) => item.key)).toEqual(["background", "video", "product", "host"]);
    expect(moveLayer(layers, "video", 1).map((item) => item.key)).toEqual(["background", "product", "video", "host"]);
  });

  it("keeps material roles visible in the intended three-scene projection", () => {
    const available = ["background", "set_surface", "supporting_video", "product_display", "digital_human", "brand_title", "promotion_text", "decoration_foreground"];
    const scenes = [0, 1, 2].map((index) => materialRolesForScene([], available, index));
    const covered = new Set(scenes.flat());

    expect(scenes[0]).toEqual(expect.arrayContaining(["background", "digital_human", "brand_title", "decoration_foreground"]));
    expect(scenes[1]).toEqual(expect.arrayContaining(["supporting_video", "product_display"]));
    expect(scenes[2]).toEqual(expect.arrayContaining(["product_display", "promotion_text"]));
    expect([...covered]).toEqual(expect.arrayContaining(available));
    expect(materialUsageLabel(["supporting_video"])).toBe("商品介绍段");
  });

  it("explains unavailable material states in Chinese without hiding candidates", () => {
    expect(assetSelectionStatus(asset({ executionCapability: "local_only" }))).toMatchObject({ selectable: true, readyForDraft: false, label: "待绑定麦兔" });
    expect(assetSelectionStatus(asset({ rightsStatus: "revoked" }))).toMatchObject({ selectable: false, label: "不可使用" });
    expect(assetSelectionStatus(asset({ rightsStatus: "pending" }))).toMatchObject({ selectable: true, readyForDraft: true, label: "仅限测试草稿" });
  });

  it("keeps the content project title separate from the Maitu room title", () => {
    expect(generatedProjectTitle("介绍张裕品酒大师PRO", "讲清产品", new Date(2026, 6, 31, 9, 8))).toBe("介绍张裕品酒大师PRO - 直播间方案 - 202607310908");
    expect(designBriefInput({ goal: "讲清产品价值", theme: "品酒大师", story: "从聚会开始", detailedDesign: "三段内容" })).toContain("详细设计：三段内容");
    expect(executionStageCopy("clearing_draft").title).toBe("清空草稿");
  });

  it("permits only pending-rights blockers in the allowlisted offline test room", () => {
    expect(pendingRightsAreOnlyBlocker(["asset_rights_not_approved:AG-1:pending", "GATE_ASSET_RIGHTS_BLOCKED"])).toBe(true);
    expect(pendingRightsAreOnlyBlocker(["GATE_ASSET_RIGHTS_BLOCKED"])).toBe(false);
    expect(pendingRightsAreOnlyBlocker(["asset_rights_not_approved:AG-1:restricted", "GATE_ASSET_RIGHTS_BLOCKED"])).toBe(false);
    expect(pendingRightsAreOnlyBlocker(["asset_rights_not_approved:AG-1:pending", "missing_required_role:title"])).toBe(false);
    expect(isAllowedTestRoom("41172", "asser测试")).toBe(true);
    expect(isAllowedTestRoom("41172", "其他标题")).toBe(false);
  });

  it("keeps geometry inside the 9:16 canvas while moving or resizing", () => {
    const geometry = { x: 0.6, y: 0.5, width: 0.4, height: 0.5 };
    expect(geometryRange(geometry, "x").max).toBeCloseTo(0.6);
    expect(geometryRange(geometry, "width").max).toBeCloseTo(0.4);
    expect(updateGeometry(geometry, "x", 0.9).x).toBeCloseTo(0.6);
    expect(updateGeometry(geometry, "height", 0.9).height).toBeCloseTo(0.5);
  });

  it("reuses an idempotency key for the same request and rotates only when inputs change", () => {
    const state = { key: "request-1", fingerprint: "" };
    expect(stableIdempotencyKey(state, "same", () => "request-2")).toBe("request-1");
    expect(stableIdempotencyKey(state, "same", () => "request-2")).toBe("request-1");
    expect(stableIdempotencyKey(state, "changed", () => "request-2")).toBe("request-2");
  });

  it("turns room-inspection failures into readable Chinese guidance", () => {
    expect(roomInspectionFailureMessage("worker browser unavailable")).toBe("本地执行器暂时无法读取麦兔页面。");
    expect(roomInspectionFailureMessage("麦兔页面暂时没有响应")).toBe("麦兔页面暂时没有响应");
  });

  it("restores reconciliation recovery after the page is remounted", () => {
    expect(reconciliationWasRecorded({ status: "cancelled", stage: "reconciled", stageEvents: [] })).toBe(true);
    expect(reconciliationWasRecorded({ status: "cancelled", stage: "failed", stageEvents: [{ stage: "reconciled" }] })).toBe(true);
    expect(reconciliationWasRecorded({ status: "reconcile_required", stage: "reconciled", stageEvents: [] })).toBe(false);
    expect(reconciliationWasRecorded({ status: "failed", stage: "failed", stageEvents: [] })).toBe(false);
  });
});
