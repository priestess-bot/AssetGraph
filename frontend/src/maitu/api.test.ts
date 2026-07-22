import { beforeEach, describe, expect, it, vi } from "vitest";
import { maituApi, normalizeFactCard, normalizePlanRevision, normalizePreflight, normalizeRequirement, normalizeRun } from "./api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("maitu workbench api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("normalizes the persisted fact card, run and plan contracts", () => {
    const card = normalizeFactCard({
      fact_card_code: "FACT-001",
      product_code: "AG-PROD-001",
      title: "聚餐事实卡",
      status: "active",
      current_approved_version: 1,
      versions: [{ version_number: 1, status: "approved", content: { product_name: "品酒大师", positioning: "聚餐轻松选酒", verified_facts: ["750mL"] } }],
    });
    expect(card).toMatchObject({ product_name: "品酒大师", positioning: "聚餐轻松选酒", approved_version: 1, status: "approved" });

    const run = normalizeRun({
      run_code: "MT-RUN-001", title: "聚餐运行", status: "ready", fact_card_version_code: "FACTV-001", inventory_snapshot_code: "INV-001", target_duration_minutes: 12, build_mode: "strict", active_plan_revision: 3,
      fact_card_version: { fact_card_code: "FACT-001", version_number: 1 }, latest_preflight: { status: "passed", plan_revision_number: 3, checks: [] },
    });
    expect(run.current_plan_revision).toBe(3);
    expect(run.preflight?.expected_plan_revision).toBe(3);

    const plan = normalizePlanRevision({ revision_number: 3, status: "ready", source_build_plan_code: "MT-BUILD-003", input_fingerprint: "abc", blocked_reasons: [], pipeline_output: { scene_count: 4, selected_count: 7 }, gap_report: { missing_count: 0 } });
    expect(plan).toMatchObject({ revision: 3, can_execute: true, build_plan_code: "MT-BUILD-003", scene_count: 4 });
  });

  it("sends strict fact content and uses material requirement routes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ fact_card_code: "FACT-001", title: "聚餐事实卡", status: "active", current_approved_version: null, versions: [{ version_number: 1, status: "draft", content: { product_name: "品酒大师", positioning: "聚餐选酒", verified_facts: ["750mL"] } }] }, 201))
      .mockResolvedValueOnce(response([]));
    vi.stubGlobal("fetch", fetchMock);

    await maituApi.createFactCard({ title: "聚餐事实卡", product_name: "品酒大师", positioning: "聚餐选酒", verified_facts: ["750mL"] });
    await maituApi.listRequirements("MT-RUN-001");

    const firstBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(firstBody).toMatchObject({ title: "聚餐事实卡", content: { product_name: "品酒大师", positioning: "聚餐选酒", verified_facts: ["750mL"] } });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/maitu/workbench/runs/MT-RUN-001/material-requirements");
  });

  it("queues inventory sync without calling worker claim endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ sync_job_code: "SYNC-001", status: "queued", source_system: "maitu", sync_mode: "full", result_summary: {} }, 202));
    vi.stubGlobal("fetch", fetchMock);
    await maituApi.createInventoryJob();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/maitu/workbench/inventory-sync-jobs");
    expect(String(fetchMock.mock.calls[0]?.[0])).not.toContain("claim");
  });

  it("keeps topic separate from the run title", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ run_code: "MT-RUN-001", title: "聚餐运行", topic: "朋友聚餐如何轻松选酒", status: "draft", fact_card_version_code: "FACTV-001", inventory_snapshot_code: "INV-001", target_duration_minutes: 12, build_mode: "strict", active_plan_revision: 0 }, 201));
    vi.stubGlobal("fetch", fetchMock);
    const run = await maituApi.createRun({ title: "聚餐运行", topic: "朋友聚餐如何轻松选酒", fact_card_code: "FACT-001", inventory_snapshot_code: "INV-001", target_duration_minutes: 12, build_mode: "strict" });
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body).toMatchObject({ title: "聚餐运行", topic: "朋友聚餐如何轻松选酒" });
    expect(run.topic).toBe("朋友聚餐如何轻松选酒");
  });

  it("sends a newly selected inventory snapshot when replanning", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ revision_number: 2, status: "blocked", blocked_reasons: [] }, 201));
    vi.stubGlobal("fetch", fetchMock);

    await maituApi.replan("MT-RUN-001", {
      reason: "使用最新同步素材重新匹配",
      expected_plan_revision: 1,
      inventory_snapshot_code: "INV-002",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/maitu/workbench/runs/MT-RUN-001/replan");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      reason: "使用最新同步素材重新匹配",
      expected_plan_revision: 1,
      inventory_snapshot_code: "INV-002",
    });
  });

  it("binds a fresh draft room through the run target endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ run_code: "MT-RUN-001", title: "聚餐运行", topic: "朋友聚餐如何轻松选酒", status: "replan_required", fact_card_version_code: "FACTV-001", fact_card_version_number: 1, fact_card_code: "FACT-001", inventory_snapshot_code: "INV-001", target_live_room_id: "39827", target_duration_minutes: 12, build_mode: "strict", include_default_host: true, max_candidates_per_need: 1, canvas_width: 1080, canvas_height: 1920, active_plan_revision: 1, created_at: "2026-07-20T00:00:00Z", updated_at: "2026-07-20T00:00:00Z" }));
    vi.stubGlobal("fetch", fetchMock);

    const run = await maituApi.updateRunTargetRoom("MT-RUN-001", "39827");

    expect(run.target_live_room_id).toBe("39827");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/maitu/workbench/runs/MT-RUN-001/target-live-room");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ target_live_room_id: "39827" });
  });

  it("adapts descending fact versions and persisted pipeline details", () => {
    const card = normalizeFactCard({
      fact_card_code: "FACT-001",
      title: "聚餐事实卡",
      current_approved_version: 1,
      versions: [
        { version_number: 2, status: "draft", content: { product_name: "品酒大师", positioning: "新版定位", verified_facts: ["新版事实"] } },
        { version_number: 1, status: "approved", content: { product_name: "品酒大师", positioning: "旧版定位", verified_facts: ["旧版事实"] } },
      ],
    });
    expect(card).toMatchObject({ current_version: 2, approved_version: 1, status: "draft", positioning: "新版定位" });

    const requirement = normalizeRequirement({
      requirement_code: "REQ-001",
      scene_name: "商品讲解",
      need_type: "product_video",
      required_category: "product_video",
      priority: "high",
      status: "selected",
      pipeline_selection: {
        status: "selected",
        selected_asset_code: "AG-VID-001",
        selected_asset_title: "商品旋转展示",
        selected_asset_source_material_type: "video",
        match_score: 0.93,
      },
    });
    expect(requirement.candidates).toEqual([
      expect.objectContaining({ asset_code: "AG-VID-001", title: "商品旋转展示", match_score: 0.93 }),
    ]);

    const plan = normalizePlanRevision({
      revision_number: 1,
      status: "blocked",
      gap_report: {
        gaps: [{
          need_type: "product_video",
          required_category: "product_video",
          blocks_auto_build: true,
          fallback_strategy: "请补充商品视频后重新规划。",
        }],
      },
    });
    expect(plan.gaps[0]).toMatchObject({ severity: "critical", message: "请补充商品视频后重新规划。" });

    const preflight = normalizePreflight({
      status: "blocked",
      expected_plan_revision: 1,
      checks: [{ code: "target_room", passed: false, detail: "需要空白草稿房间" }],
    });
    expect(preflight.checks[0]).toMatchObject({ check_code: "target_room", label: "空白草稿房间", status: "blocked" });
  });
});
