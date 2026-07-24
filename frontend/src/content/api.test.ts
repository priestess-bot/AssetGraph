import { beforeEach, describe, expect, it, vi } from "vitest";
import { contentProjectsApi } from "./api";
import { findFactCardConflicts, recommendContentTemplates } from "./ContentProjectsPage";
import type { RoomTemplate } from "../live-research/types";
import type { ProductFactCard } from "../knowledge/api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("content projects api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("creates an expected-revision input patch instead of mutating a project in place", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "修订后的直播", revision_number: 2, status: "draft", generation_goal: "更新后的目标",
      updated_at: "2026-07-25T00:00:00Z", content: { theme: "夏日聚会", must_include: ["真实场景"] }, generated: false,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.update("CONTENT-001", {
      expected_revision: 1, title: "修订后的直播", generation_goal: "更新后的目标", must_include: ["真实场景"], visual_requirements: ["产品置于桌面"],
    });

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/content-projects/CONTENT-001");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 1, title: "修订后的直播", generation_goal: "更新后的目标", must_include: ["真实场景"], visual_requirements: ["产品置于桌面"] });
    expect(detail).toMatchObject({ revisionNumber: 2, status: "draft", generationGoal: "更新后的目标" });
  });

  it("updates fact card selections in their own revision patch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 3, status: "draft", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: { fact_card_codes: ["FACT-WINE"] }, generated: false,
      fact_cards: [{ fact_card_code: "FACT-WINE", version_number: 4, version_code: "FACT-WINE-V4", content_sha256: "sha256" }],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.update("CONTENT-001", { expected_revision: 2, fact_card_codes: ["FACT-WINE"] });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 2, fact_card_codes: ["FACT-WINE"] });
    expect(detail.factCards).toEqual([{ fact_card_code: "FACT-WINE", version_number: 4, version_code: "FACT-WINE-V4", content_sha256: "sha256" }]);
  });

  it("updates template references with explicit module contribution decisions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 4, status: "draft", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: { primary_template_code: "TPL-WINE", secondary_template_codes: ["TPL-HOST"] }, generated: false,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await contentProjectsApi.update("CONTENT-001", {
      expected_revision: 3, primary_template_code: "TPL-WINE", secondary_template_codes: ["TPL-HOST"],
      template_contribution_decisions: [{ template_code: "TPL-WINE", accepted_modules: ["opening"] }, { template_code: "TPL-HOST", accepted_modules: ["close"] }],
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_revision: 3, primary_template_code: "TPL-WINE", secondary_template_codes: ["TPL-HOST"],
      template_contribution_decisions: [{ template_code: "TPL-WINE", accepted_modules: ["opening"] }, { template_code: "TPL-HOST", accepted_modules: ["close"] }],
    });
  });

  it("revises parsed DesignBrief fields without changing the source content project", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 4, status: "confirmed", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: {}, generated: false,
      design_brief: { design_brief_code: "DBR-002", revision_number: 2, status: "draft", raw_input: "聚会场景", parsed_brief: { audience: "聚会组织者" }, user_overrides: { audience: "聚会组织者" }, open_questions: [] },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.reviseBrief("CONTENT-001", 4, { audience: "聚会组织者" });

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/content-projects/CONTENT-001/design-brief");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 4, overrides: { audience: "聚会组织者" } });
    expect(detail.designBrief).toMatchObject({ revision_number: 2, user_overrides: { audience: "聚会组织者" } });
  });

  it("reads immutable content-chain revision lineage", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response([{
      object_type: "script", object_code: "SCRIPT-001", revision_number: 2, status: "confirmed",
      created_at: "2026-07-25T00:00:00Z", created_by: "writer", fingerprint_sha256: "abcdef0123456789",
      sources: ["STORY STORY-001 r2"],
    }]));
    vi.stubGlobal("fetch", fetchMock);

    const revisions = await contentProjectsApi.listChainRevisions("CONTENT-001");

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/content-projects/CONTENT-001/content-chain-revisions");
    expect(revisions).toEqual([expect.objectContaining({ objectType: "script", objectCode: "SCRIPT-001", revisionNumber: 2, sources: ["STORY STORY-001 r2"] })]);
  });

  it("submits a human script revision as structured blocks", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 1, status: "confirmed", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: {}, generated: true,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await contentProjectsApi.reviseScript("CONTENT-001", 1, [
      { module_type: "story", content: "先补充场景化建议。", estimated_duration_ms: 25_000, fact_citations: [], template_sources: [] },
      { module_type: "opening", content: "再说明选择场景。", estimated_duration_ms: 30_000, fact_citations: [], template_sources: [] },
    ]);

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/content-projects/CONTENT-001/script-revision");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 1, blocks: [
      { module_type: "story", content: "先补充场景化建议。", estimated_duration_ms: 25_000, fact_citations: [], template_sources: [] },
      { module_type: "opening", content: "再说明选择场景。", estimated_duration_ms: 30_000, fact_citations: [], template_sources: [] },
    ] });
  });

  it("submits a coupled Program and ShotList revision with explicit block mappings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 1, status: "confirmed", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: {}, generated: true,
    }));
    vi.stubGlobal("fetch", fetchMock);
    const segments = [{ semantic_goal: "说明选择依据", program_phase: "body", script_block_codes: ["BLOCK-001"] }];
    const shots = [{ program_segment_index: 0, shot_goal: "主播解释选择依据", material_role_requirements: ["digital_human", "background"], script_block_codes: ["BLOCK-001"] }];

    await contentProjectsApi.reviseProgramAndShots("CONTENT-001", 1, segments, shots);

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/content-projects/CONTENT-001/program-shot-revision");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 1, segments, shots });
  });

  it("retains fact citation character ranges while reading script blocks", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 1, status: "confirmed", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: {}, generated: true,
      script: { script_revision_code: "SCRIPT-001", revision_number: 1, title: "脚本", blocks: [{ block_code: "BLOCK-1", module_type: "product_fact", content: "库存充足。", fact_citations: [{ fact_card_code: "FACT-001", version_number: 1, claim_text: "库存充足", start_offset: 0, end_offset: 4 }], template_sources: [] }] },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.get("CONTENT-001");

    expect(detail.script?.blocks[0]?.fact_citations[0]).toMatchObject({ start_offset: 0, end_offset: 4 });
  });

  it("explains mismatched fact-card scope and product metadata before confirmation", () => {
    const fact = (code: string, positioning: string, platforms: string[]): ProductFactCard => ({
      factCardCode: code, title: code, productCode: "WINE-001", status: "active", currentApprovedVersion: 1,
      versions: [{ versionCode: `${code}-V001`, versionNumber: 1, status: "approved", content: { product_name: "演示酒", positioning, applicable_platforms: platforms, source_references: [{ kind: "url", url: "https://example.test/fact" }] } }],
    });

    expect(findFactCardConflicts([fact("FACT-A", "聚餐场景", ["douyin"]), fact("FACT-B", "礼赠场景", ["kuaishou"])], ["FACT-A", "FACT-B"], "douyin")).toEqual([
      "FACT-B 不适用于 douyin",
      "WINE-001 的 positioning 在 FACT-A/FACT-B 中不一致",
    ]);
  });

  it("ranks content strategies only from explicit category, module, and compatibility matches", () => {
    const template = (code: string, category: string, title: string, compatibilityTags: string[]): RoomTemplate => ({
      template_code: code, title: code, source_session_code: "CAP-001", source_type: "external_flat_video", templateKind: "content_strategy", latest_revision: 1, published_revision: 1, status: "published", layout_fidelity: "none", buildability: "reference_only", contentReadiness: "ready", scenes: [],
      contentStrategy: { targetCategory: category, compatibilityTags, programOutline: [{ moduleKey: "opening", title, purpose: "建立选择目标", startMs: 0, endMs: 30_000 }], materialCues: [], reviewedExamples: [] },
    });

    const recommendations = recommendContentTemplates([template("TPL-WINE", "葡萄酒", "聚会开场", ["聚会"]), template("TPL-CARE", "护肤", "日常护理", ["护肤"])], "为聚会挑选葡萄酒，并用聚会开场建立目标");

    expect(recommendations[0]).toMatchObject({ templateCode: "TPL-WINE", score: 132, signals: ["品类：葡萄酒", "模块：聚会开场", "标签：聚会"] });
    expect(recommendations).toHaveLength(1);
  });
});
