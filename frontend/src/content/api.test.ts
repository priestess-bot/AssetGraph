import { beforeEach, describe, expect, it, vi } from "vitest";
import { contentProjectsApi } from "./api";
import { contentRecoveryStep, findFactCardConflicts, recommendContentTemplates } from "./selectionRules";
import type { RoomTemplate } from "../live-research/types";
import type { ProductFactCard } from "../knowledge/api";
import { WorkbenchApiError } from "../workbench/api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("content projects api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uses the caller's stable idempotency key when creating a project", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-NEW", title: "张裕直播方案", revision_number: 1, status: "draft", generation_goal: "介绍产品", updated_at: "2026-07-31T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await contentProjectsApi.create({ title: "张裕直播方案", generation_goal: "介绍产品" }, { idempotencyKey: "project-create-001" });

    expect(fetchMock).toHaveBeenCalledWith("/api/content-projects", expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "project-create-001" }),
    }));
  });

  it("gives an actionable recovery step for stale or unapproved facts", () => {
    const error = new WorkbenchApiError("Fact card is unavailable", 422, {
      detail: { code: "FACT_CARD_NOT_APPROVED", message: "Fact card is unavailable", details: {} },
    });

    expect(contentRecoveryStep(error)).toContain("知识库批准新的事实版本");
  });

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

  it("reads pinned source-backed fact claims and their script citations", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "保修说明", revision_number: 1, status: "confirmed", generation_goal: "说明保修承诺",
      updated_at: "2026-07-25T00:00:00Z", content: {}, generated: true,
      fact_claims: [{ claim_code: "CLAIM-001", fact_code: "FACT-001", source_evidence_code: "EVIDENCE-001", claim: "提供 12 个月保修。", citation_excerpt: "规格书载明 12 个月保修。", fingerprint_sha256: "a".repeat(64) }],
      script: { script_revision_code: "SCRIPT-001", revision_number: 1, title: "脚本", blocks: [{ block_code: "BLOCK-1", module_type: "product_fact", content: "提供 12 个月保修。", fact_citations: [{ claim_code: "CLAIM-001", fact_code: "FACT-001", source_evidence_code: "EVIDENCE-001", claim_text: "提供 12 个月保修", start_offset: 0, end_offset: 10 }], template_sources: [] }] },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.get("CONTENT-001");

    expect(detail.factClaims).toEqual([expect.objectContaining({ claim_code: "CLAIM-001", source_evidence_code: "EVIDENCE-001" })]);
    expect(detail.script?.blocks[0]?.fact_citations[0]).toMatchObject({ claim_code: "CLAIM-001", source_evidence_code: "EVIDENCE-001" });
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

  it("reads the frozen content-strategy policy attached to a template contribution", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 4, status: "confirmed", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", generated: false,
      content: {
        template_contribution_decisions: [{
          template_code: "TPL-WINE", revision: 2, selection_role: "primary", available_modules: ["opening"], accepted_modules: ["opening"], rejected_modules: [], material_cues: ["background"],
          program_outline: [{ module_key: "opening", title: "开场", purpose: "建立选择目标", source_session_code: "CAPTURE-001", start_ms: 0, end_ms: 30_000 }],
          reviewed_examples: [{ module_key: "opening", example_text: "先用选择问题建立代入。", source_session_code: "CAPTURE-001", start_ms: 1_000, end_ms: 8_000 }],
          content_strategy_policy: { duration_policy: { target_duration_seconds: 1800 }, interaction_policy: { cadence: "module_end" } },
        }],
      },
      script: { script_revision_code: "SCRIPT-001", revision_number: 1, title: "脚本", blocks: [{ block_code: "BLOCK-001", module_type: "opening", content: "从选择问题开始。", fact_citations: [], interaction_intent: { type: "template_interaction", policy: { cadence: "module_end" } }, template_sources: [{ template_code: "TPL-WINE", revision: 2, module_guidance: ["先建立选择问题"], content_strategy_policy: { interaction_policy: { cadence: "module_end" } }, strategy_stage: { module_key: "opening", title: "开场", purpose: "建立选择目标", source_session_code: "CAPTURE-001", start_ms: 0, end_ms: 30_000 }, reference_examples: [{ module_key: "opening", example_text: "先用选择问题建立代入。", source_session_code: "CAPTURE-001", start_ms: 1_000, end_ms: 8_000 }] }] }] },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.get("CONTENT-001");

    expect(detail.templateContributionDecisions[0]).toMatchObject({
      templateCode: "TPL-WINE",
      programOutline: [{ moduleKey: "opening", title: "开场", purpose: "建立选择目标", sourceSessionCode: "CAPTURE-001", startMs: 0, endMs: 30_000 }],
      reviewedExamples: [{ moduleKey: "opening", exampleText: "先用选择问题建立代入。", sourceSessionCode: "CAPTURE-001", startMs: 1_000, endMs: 8_000 }],
      contentStrategyPolicy: { duration_policy: { target_duration_seconds: 1800 }, interaction_policy: { cadence: "module_end" } },
    });
    expect(detail.script?.blocks[0]?.template_sources[0]).toMatchObject({
      moduleGuidance: ["先建立选择问题"],
      contentStrategyPolicy: { interaction_policy: { cadence: "module_end" } },
      strategyStage: { moduleKey: "opening", title: "开场", sourceSessionCode: "CAPTURE-001", startMs: 0, endMs: 30_000 },
      referenceExamples: [{ moduleKey: "opening", exampleText: "先用选择问题建立代入。", sourceSessionCode: "CAPTURE-001", startMs: 1_000, endMs: 8_000 }],
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
      script: { script_revision_code: "SCRIPT-001", revision_number: 1, title: "脚本", blocks: [{ block_code: "BLOCK-1", module_type: "product_fact", content: "库存充足。", fact_citations: [{ fact_card_code: "FACT-001", version_number: 1, claim_text: "库存充足", start_offset: 0, end_offset: 4 }], template_sources: [], content_rule_refs: [{ rule_code: "RULE-001", rule_kind: "compliance_rule", directive: "must_include", rule_text: "请说明适用范围。", fingerprint_sha256: "b".repeat(64) }] }] },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.get("CONTENT-001");

    expect(detail.script?.blocks[0]?.fact_citations[0]).toMatchObject({ start_offset: 0, end_offset: 4 });
    expect(detail.script?.blocks[0]?.contentRuleRefs).toEqual([{ ruleCode: "RULE-001", ruleKind: "compliance_rule", directive: "must_include", ruleText: "请说明适用范围。", fingerprintSha256: "b".repeat(64) }]);
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
      contentStrategy: { targetCategory: category, compatibilityTags, programOutline: [{ moduleKey: "opening", title, purpose: "建立选择目标", startMs: 0, endMs: 30_000 }], durationPolicy: {}, moduleRecipes: [], productRotationPolicy: {}, interactionPolicy: {}, conversionPolicy: {}, hostStyle: {}, materialCues: [], reviewedExamples: [], removedSourceFactCategories: [] },
    });

    const recommendations = recommendContentTemplates([template("TPL-WINE", "葡萄酒", "聚会开场", ["聚会"]), template("TPL-CARE", "护肤", "日常护理", ["护肤"])], "为聚会挑选葡萄酒，并用聚会开场建立目标");

    expect(recommendations[0]).toMatchObject({ templateCode: "TPL-WINE", score: 132, signals: ["品类：葡萄酒", "模块：聚会开场", "标签：聚会"] });
    expect(recommendations).toHaveLength(1);
  });
});
