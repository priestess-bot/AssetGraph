import { afterEach, describe, expect, it, vi } from "vitest";
import { guidedContentApi, normalizeConfirmationPreview, normalizeGuidedItemVersions, normalizeGuidedRevisions, normalizeGuidedWorkflow, normalizeMaituRoomConfiguration } from "./workflowApi";


const rawWorkflow = {
  workflow_version: "guided-live.v1",
  project: {
    project_code: "CONTENT-001",
    title: "新品直播",
    revision_number: 2,
    status: "confirmed",
    target_live_room_id: "39826",
    theme: "夏季新品",
    updated_at: "2026-08-06T02:00:00Z",
  },
  material_pool: {
    pool_revision_code: "POOL-001",
    revision_number: 3,
    selected_asset_codes: ["AG-001"],
    fingerprint_sha256: "a".repeat(64),
  },
  setup: {
    selected_knowledge_codes: ["FACT-001"],
    knowledge_references: [{ knowledge_code: "FACT-001", title: "商品卖点", excerpt: "常温保存。", version: "v3" }],
    theme_candidate: { theme: "夏季新品专场", rationale: "突出季节场景" },
    recommendations: {
      knowledge_candidates: [{ knowledge_code: "FACT-002", title: "优惠规则" }],
      material_candidates: [{ asset_code: "AG-002", title: "主推商品图", rationale: "和主题匹配", material_roles: ["product_display"] }],
    },
  },
  outline: {
    story_brief_code: "STORY-001",
    revision_number: 4,
    status: "confirmed",
    sections: [{ section_key: "section-1", title: "开场", objective: "建立主题", key_points: [{ text: "欢迎", citations: [{ citation_code: "FACT-001", title: "商品卖点", excerpt: "常温保存。" }] }] }],
    created_at: "2026-08-06T02:01:00Z",
  },
  script: {
    script_revision_code: "SCRIPT-001",
    revision_number: 2,
    status: "draft",
    title: "新品直播脚本",
    source_outline_revision: 4,
    source_material_pool_revision: 3,
    blocks: [{ block_code: "BLOCK-001", sort_order: 0, section_key: "section-1", content: "欢迎来到直播间。" }],
    requirements: [{ requirement_code: "REQ-001", block_sort_order: 0, section_key: "section-1", material_role: "background", description: "直播背景", priority: "required", keywords: ["夏季"], matched_asset_code: "AG-001", status: "matched" }],
    created_at: "2026-08-06T02:02:00Z",
  },
  storyboard: {
    plan_code: "LIVEPLAN-001",
    review_status: "draft",
    status: "ready",
    blocked_reasons: [],
    template_code: "ROOMTPL-001",
    revision_context: { workflow_version: "guided-live.v1", manual_only: false },
    blueprint: {
      scenes: [{
        shot_code: "SHOT-001",
        title: "开场分镜",
        script: "欢迎来到直播间。",
        layers: [{ role: "background", asset_code: "AG-001", normalized_geometry: { x: 0, y: 0, width: 1, height: 1 }, z_order: 0 }],
      }],
    },
    created_at: "2026-08-06T02:04:00Z",
    updated_at: "2026-08-06T02:04:00Z",
  },
  history: [{ event_code: "outline:STORY-001", stage: "outline", kind: "outline_revision", reference_code: "STORY-001", revision_number: 4, status: "confirmed", actor: "operator", occurred_at: "2026-08-06T02:01:00Z", details: {} }],
  jobs: {
    script: { job_code: "CGEN-001", stage: "script", status: "running", total_items: 2, completed_items: 1, attempts: 1, max_attempts: 3, updated_at: "2026-08-06T02:03:00Z" },
    section: { job_code: "CGEN-002", stage: "outline", operation: "outline_section_regenerate", target_section_key: "section-1", status: "queued", total_items: 1, completed_items: 0, attempts: 0, max_attempts: 3, updated_at: "2026-08-06T02:03:00Z" },
  },
  gates: { outline_current: true, outline_confirmed: true, script_current: true, required_material_missing_count: 0 },
};

describe("guided content workflow api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("normalizes versioned outline, script, requirements and job progress", () => {
    const workflow = normalizeGuidedWorkflow(rawWorkflow);
    expect(workflow.project.targetLiveRoomId).toBe("39826");
    expect(workflow.outline?.sections[0].sectionKey).toBe("section-1");
    expect(workflow.outline?.sections[0].keyPoints[0]).toMatchObject({ text: "欢迎", citations: [{ citationCode: "FACT-001", title: "商品卖点" }] });
    expect(workflow.setup).toMatchObject({ selectedKnowledgeCodes: ["FACT-001"], themeCandidate: { theme: "夏季新品专场" } });
    expect(workflow.setup.recommendations?.materials[0]).toMatchObject({ assetCode: "AG-002", rationale: "和主题匹配" });
    expect(workflow.script?.requirements[0]).toMatchObject({ status: "matched", matchedAssetCode: "AG-001" });
    expect(workflow.jobs.script).toMatchObject({ status: "running", completedItems: 1, totalItems: 2 });
    expect(workflow.jobs.section).toMatchObject({ targetSectionKey: "section-1", operation: "outline_section_regenerate" });
    expect(workflow.gates.outlineConfirmed).toBe(true);
    expect(workflow.storyboard?.scenes[0].layers[0]).toMatchObject({ role: "background", assetCode: "AG-001" });
    expect(workflow.history[0]).toMatchObject({ kind: "outline_revision", revisionNumber: 4 });
  });

  it("updates the script-stage material pool without sending script content", async () => {
    const calls: Array<{ method?: string; body?: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ method: init?.method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      return new Response(JSON.stringify(rawWorkflow), { status: 200, headers: { "Content-Type": "application/json" } });
    }));

    await guidedContentApi.updateMaterialPool("CONTENT-001", { expected_revision: 3, selected_asset_codes: ["AG-001", "AG-002"] });

    expect(calls[0]).toEqual({ method: "PUT", body: { expected_revision: 3, selected_asset_codes: ["AG-001", "AG-002"] } });
  });

  it("uses the additive setup endpoints and keeps old string key points writable", async () => {
    const calls: Array<{ path: string; method?: string; body?: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ path: String(input), method: init?.method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      return new Response(JSON.stringify({ job_code: "CGEN-003", stage: "setup", status: "queued", total_items: 1, completed_items: 0, attempts: 0, max_attempts: 3, updated_at: "2026-08-06T02:03:00Z" }), { status: 202, headers: { "Content-Type": "application/json" } });
    }));

    await guidedContentApi.optimizeTheme("CONTENT-001", { theme: "夏季新品" });
    await guidedContentApi.recommendSetup("CONTENT-001", { theme: "夏季新品", selected_asset_codes: ["AG-001"], selected_knowledge_codes: ["FACT-001"] });
    await guidedContentApi.regenerateOutlineSection("CONTENT-001", "section-1", 4, "突出优惠");

    expect(calls).toEqual([
      { path: "/api/content-projects/CONTENT-001/guided-workflow/setup/theme-optimize", method: "POST", body: { theme: "夏季新品" } },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/setup/recommendations", method: "POST", body: { theme: "夏季新品", selected_asset_codes: ["AG-001"], selected_knowledge_codes: ["FACT-001"] } },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/outline/sections/section-1/regenerate", method: "POST", body: { expected_revision: 4, guidance: "突出优惠" } },
    ]);

    const oldWorkflow = normalizeGuidedWorkflow({ ...rawWorkflow, outline: { ...rawWorkflow.outline, sections: [{ section_key: "section-1", title: "开场", objective: "建立主题", key_points: ["旧格式要点"] }] } });
    expect(oldWorkflow.outline?.sections[0].keyPoints).toEqual([{ text: "旧格式要点", citations: [] }]);
  });

  it("normalizes the current setup-assistance, room-host and archive response shapes", () => {
    const workflow = normalizeGuidedWorkflow({
      ...rawWorkflow,
      setup: undefined,
      project: { ...rawWorkflow.project, selected_knowledge_refs: [{ kind: "fact_card", code: "FACT-003", version_number: 2 }] },
      recommendations: {
        optimize_theme: { theme_candidate: "夏日清凉专场" },
        recommend_knowledge: { recommendations: [{ source_id: "fact_card:FACT-004:v3", kind: "fact_card", code: "FACT-004", version_number: 3, title: "适用人群", summary: "适合夏季送礼", reason: "主题相关" }] },
        recommend_materials: { recommendations: [{ source_id: "asset:AG-003", asset_code: "AG-003", title: "夏日主图", material_roles: ["product_display"], reason: "画面匹配" }] },
      },
      script_archives: [{ script_revision_code: "SCRIPT-OLD", revision_number: 1, status: "superseded", title: "旧脚本", created_at: "2026-08-06T02:00:00Z" }],
    });

    expect(workflow.setup.selectedKnowledgeCodes).toContain("FACT-003");
    expect(workflow.setup.themeCandidate?.theme).toBe("夏日清凉专场");
    expect(workflow.setup.recommendations?.knowledge[0]).toMatchObject({ knowledgeCode: "FACT-004", kind: "fact_card", versionNumber: 3 });
    expect(workflow.setup.recommendations?.materials[0]).toMatchObject({ assetCode: "AG-003", rationale: "画面匹配" });
    expect(workflow.revisions.script[0]).toMatchObject({ revisionCode: "SCRIPT-OLD", revisionNumber: 1, restorable: true });
    expect(normalizeGuidedRevisions({ script: [{ script_revision_code: "SCRIPT-OLD", revision_number: 1, status: "superseded" }] }).script[0].restorable).toBe(true);
    expect(normalizeMaituRoomConfiguration({ has_ready_host: true, hosts: [{ clip_name: "默认场景", speaker_id: "voice-001", digital_human_image_id: "human-001", ready: true }] })).toMatchObject({ ready: true, hostName: "默认场景", voiceName: "voice-001", sceneName: "默认场景" });
  });

  it("preserves generated storyboard layers when saving an edited version", async () => {
    const calls: Array<{ method?: string; body?: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ method: init?.method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      return new Response(JSON.stringify(rawWorkflow), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const scene = normalizeGuidedWorkflow(rawWorkflow).storyboard?.scenes[0];
    expect(scene).toBeDefined();

    await guidedContentApi.reviseStoryboard("CONTENT-001", "LIVEPLAN-001", [{ ...scene!, title: "人工修正标题" }]);

    expect(calls[0]).toEqual({
      method: "PUT",
      body: {
        expected_plan_code: "LIVEPLAN-001",
        scenes: [{
          shot_code: "SHOT-001",
          sort_order: 0,
          title: "人工修正标题",
          script: "欢迎来到直播间。",
          layers: [{ role: "background", asset_code: "AG-001", geometry: { x: 0, y: 0, width: 1, height: 1 }, z_order: 0 }],
        }],
      },
    });
  });

  it("normalizes the branch tree, item metadata, versions and confirmation preview", () => {
    const workflow = normalizeGuidedWorkflow({
      ...rawWorkflow,
      tree: {
        head_revision: 9,
        active_path: ["SETUP-A", "OUTLINE-A"],
        nodes: [{ node_code: "OUTLINE-A", parent_node_code: "SETUP-A", stage: "outline", label: "方案 A", status: "confirmed", current_revision_number: 3, confirmed_revision_number: 2, has_draft: true }],
      },
      outline: { ...rawWorkflow.outline, sections: [{ ...rawWorkflow.outline.sections[0], item_version_id: "VERSION-2", version_number: 2, stale: true }] },
    });
    expect(workflow.tree).toMatchObject({ headRevision: 9, activePath: ["SETUP-A", "OUTLINE-A"] });
    expect(workflow.tree.nodes[0]).toMatchObject({ nodeCode: "OUTLINE-A", parentNodeCode: "SETUP-A", hasDraft: true });
    expect(workflow.outline?.sections[0]).toMatchObject({ itemVersionId: "VERSION-2", versionNumber: 2, stale: true });
    expect(normalizeGuidedItemVersions([{ id: "VERSION-1", version_number: 1, content: { title: "开场" }, producer_kind: "manual", producer_ref: "operator", guidance: "更精简", created_at: "2026-08-06T02:00:00Z" }])[0]).toMatchObject({ id: "VERSION-1", versionNumber: 1, producerKind: "manual", guidance: "更精简" });
    expect(normalizeConfirmationPreview({ stage: "outline", expected_revision: 3, changed: false, preview_fingerprint: "fp", diff: { initial: false, added: [], removed: [], changed: [], reordered: false, content_changed: false } }, "outline")).toMatchObject({ changed: false, previewFingerprint: "fp", expectedRevision: 3 });
  });

  it("uses only the documented tree, item-version and confirmation endpoints", async () => {
    const calls: Array<{ path: string; method?: string; body?: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, method: init?.method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      if (path.endsWith("/versions") && !path.endsWith("/versions/select")) return Response.json([{ id: "VERSION-1", version_number: 1, content: {}, producer_kind: "manual", created_at: "2026-08-06T02:00:00Z" }]);
      if (path.endsWith("/confirm-preview")) return Response.json({ stage: "outline", expected_revision: 4, changed: false, preview_fingerprint: "fp", diff: {} });
      if (path.endsWith("/tree/select") || path.includes("/tree/nodes/")) return Response.json({ head_revision: 3, active_path: ["OUTLINE-A"], nodes: [] });
      return Response.json(rawWorkflow);
    }));

    await guidedContentApi.selectTreeNode("CONTENT-001", "OUTLINE-A", 3);
    await guidedContentApi.updateTreeNode("CONTENT-001", "OUTLINE-A", { label: "大纲 A", archived: false });
    await guidedContentApi.getItemVersions("CONTENT-001", "outline", "section-1");
    await guidedContentApi.selectItemVersion("CONTENT-001", "outline", "section-1", 2, 4);
    await guidedContentApi.getConfirmationPreview("CONTENT-001", "outline");
    await guidedContentApi.confirmSetup("CONTENT-001", 2, "setup-fp");

    expect(calls).toEqual([
      { path: "/api/content-projects/CONTENT-001/guided-workflow/tree/select", method: "POST", body: { node_code: "OUTLINE-A", expected_head_revision: 3 } },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/tree/nodes/OUTLINE-A", method: "PATCH", body: { label: "大纲 A", archived: false } },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/outline/items/section-1/versions", method: undefined, body: undefined },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/outline/items/section-1/versions/select", method: "POST", body: { version_number: 2, expected_revision: 4 } },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/outline/confirm-preview", method: undefined, body: undefined },
      { path: "/api/content-projects/CONTENT-001/guided-workflow/setup/confirm", method: "POST", body: { expected_revision: 2, preview_fingerprint: "setup-fp" } },
    ]);
  });
});
