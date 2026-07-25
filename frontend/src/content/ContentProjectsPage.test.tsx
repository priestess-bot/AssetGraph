import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContentProjectsPage } from "./ContentProjectsPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const detail = {
  project_code: "CONTENT-001",
  title: "夏日晚场",
  revision_number: 1,
  status: "confirmed",
  generation_goal: "完成商品讲解与互动转化",
  updated_at: "2026-07-25T00:00:00Z",
  content: {
    template_contribution_decisions: [
      {
        template_code: "TPL-STRATEGY-001",
        revision: 2,
        selection_role: "primary",
        available_modules: ["opening", "conversion"],
        accepted_modules: ["opening", "conversion"],
        rejected_modules: [],
        material_cues: ["background"],
        program_outline: [
          {
            module_key: "opening",
            title: "开场",
            purpose: "建立选择目标",
            source_session_code: "CAPTURE-001",
            start_ms: 0,
            end_ms: 30_000,
          },
        ],
        reviewed_examples: [
          {
            module_key: "opening",
            example_text: "先用选择问题建立代入。",
            source_session_code: "CAPTURE-001",
            start_ms: 1_000,
            end_ms: 8_000,
          },
        ],
        content_strategy_policy: {
          duration_policy: { target_duration_seconds: 1800 },
        },
      },
    ],
  },
  generated: true,
  design_brief: {
    design_brief_code: "DBR-001",
    revision_number: 1,
    status: "confirmed",
    raw_input: "夏日晚场",
    parsed_brief: {},
    user_overrides: {},
    open_questions: [],
  },
  script: {
    script_revision_code: "SCRIPT-001",
    revision_number: 1,
    title: "夏日晚场脚本",
    blocks: [
      {
        block_code: "BLOCK-001",
        module_type: "opening",
        content: "先说明夏日晚场的选择场景。",
        fact_citations: [],
        template_sources: [
          {
            template_code: "TPL-STRATEGY-001",
            revision: 2,
            strategy_stage: {
              module_key: "opening",
              title: "开场",
              purpose: "建立选择目标",
              source_session_code: "CAPTURE-001",
              start_ms: 0,
              end_ms: 30_000,
            },
            reference_examples: [
              {
                module_key: "opening",
                example_text: "先用选择问题建立代入。",
                source_session_code: "CAPTURE-001",
                start_ms: 1_000,
                end_ms: 8_000,
              },
            ],
          },
        ],
      },
      {
        block_code: "BLOCK-002",
        module_type: "conversion",
        content: "邀请观众留言说明使用需求。",
        fact_citations: [],
        template_sources: [],
      },
    ],
  },
  program: {
    program_revision_code: "PROGRAM-001",
    revision_number: 1,
    segments: [
      {
        segment_code: "SEGMENT-001",
        semantic_goal: "建立选择场景",
        program_phase: "opening",
        estimated_duration_ms: 30000,
        product_refs: [],
        interaction_actions: [],
        cta_actions: [],
        branch_applicability: ["live_room"],
        metadata: {},
        script_block_codes: ["BLOCK-001"],
      },
      {
        segment_code: "SEGMENT-002",
        semantic_goal: "引导互动",
        program_phase: "conversion",
        estimated_duration_ms: 30000,
        product_refs: [],
        interaction_actions: [],
        cta_actions: [],
        branch_applicability: ["live_room"],
        metadata: {},
        script_block_codes: ["BLOCK-002"],
      },
    ],
  },
  shot_list: {
    shot_list_revision_code: "SHOTLIST-001",
    revision_number: 1,
    shots: [
      {
        shot_code: "SHOT-001",
        shot_goal: "建立选择场景",
        program_segment_code: "SEGMENT-001",
        composition_intent: {},
        material_role_requirements: ["digital_human"],
        audio_actions: [],
        continuity: {},
        acceptance_criteria: [],
        estimated_duration_ms: 30000,
        branch_applicability: ["live_room"],
        must_include: [],
        must_avoid: [],
        script_block_codes: ["BLOCK-001"],
      },
      {
        shot_code: "SHOT-002",
        shot_goal: "引导互动",
        program_segment_code: "SEGMENT-002",
        composition_intent: {},
        material_role_requirements: ["digital_human"],
        audio_actions: [],
        continuity: {},
        acceptance_criteria: [],
        estimated_duration_ms: 30000,
        branch_applicability: ["live_room"],
        must_include: [],
        must_avoid: [],
        script_block_codes: ["BLOCK-002"],
      },
    ],
  },
};

describe("ContentProjectsPage", () => {
  it("creates a content project with complete production constraints", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/content-projects") {
          if (init?.method === "POST")
            return response({
              project_code: "CONTENT-NEW",
              title: "新品讲解",
              revision_number: 1,
              status: "draft",
              generation_goal: "完成新品讲解",
              updated_at: "2026-07-25T00:00:00Z",
            });
          return response([detail]);
        }
        if (url === "/api/content-projects/CONTENT-001")
          return response(detail);
        if (url === "/api/content-projects/CONTENT-001/content-chain-revisions")
          return response([]);
        if (
          url === "/api/live-research/room-templates" ||
          url === "/api/maitu/workbench/product-fact-cards" ||
          url === "/api/functional-knowledge/fact-claims"
        )
          return response([]);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <ContentProjectsPage />
      </QueryClientProvider>,
    );

    await screen.findByRole("heading", { name: "人工编排节目段与镜头" });
    expect(screen.getByText("固定阶段")).toBeInTheDocument();
    expect(screen.getByText("开场 (opening)")).toBeInTheDocument();
    expect(screen.getByText(/阶段：开场 \(CAPTURE-001 0-30000ms\)/)).toBeInTheDocument();
    expect(screen.getByText("清洗例证")).toBeInTheDocument();
    expect(screen.getByText(/例证：先用选择问题建立代入。 \(CAPTURE-001 1000-8000ms\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "阶段证据：开场" })).toHaveAttribute(
      "href",
      "/research/live-sources?view=sessions&session=CAPTURE-001&in=0&out=30",
    );
    expect(screen.getByRole("link", { name: "例证：先用选择问题建立代入。" })).toHaveAttribute(
      "href",
      "/research/live-sources?view=sessions&session=CAPTURE-001&in=1&out=8",
    );
    await user.click(screen.getByRole("button", { name: "新建" }));
    fireEvent.change(screen.getAllByLabelText("内容项目名称")[0], {
      target: { value: "新品讲解" },
    });
    fireEvent.change(screen.getAllByLabelText("生成目标")[0], {
      target: { value: "完成新品讲解" },
    });
    fireEvent.change(screen.getAllByLabelText("商品讲解顺序")[0], {
      target: { value: "PRODUCT-001\nPRODUCT-002" },
    });
    fireEvent.change(screen.getAllByLabelText("促单要求")[0], {
      target: { value: "引导加入购物车" },
    });
    fireEvent.change(screen.getAllByLabelText("舞台要求")[0], {
      target: { value: "商品置于桌面" },
    });
    fireEvent.change(screen.getAllByLabelText("视觉要求")[0], {
      target: { value: "保持商品完整可见" },
    });
    fireEvent.change(screen.getAllByLabelText("音频要求")[0], {
      target: { value: "降低背景音乐" },
    });
    await user.click(screen.getByRole("button", { name: "创建内容项目" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url === "/api/content-projects" &&
            request.init?.method === "POST",
        ),
      ).toBe(true),
    );
    const request = requests.find(
      (item) =>
        item.url === "/api/content-projects" && item.init?.method === "POST",
    );
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({
      title: "新品讲解",
      generation_goal: "完成新品讲解",
      product_order: ["PRODUCT-001", "PRODUCT-002"],
      conversion_requirements: ["引导加入购物车"],
      staging_requirements: ["商品置于桌面"],
      visual_requirements: ["保持商品完整可见"],
      audio_requirements: ["降低背景音乐"],
    });
  });

  it("keeps Shot mappings valid when adding and reordering program segments", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/content-projects") return response([detail]);
        if (url === "/api/content-projects/CONTENT-001")
          return response(detail);
        if (url === "/api/content-projects/CONTENT-001/content-chain-revisions")
          return response([]);
        if (
          url === "/api/live-research/room-templates" ||
          url === "/api/maitu/workbench/product-fact-cards" ||
          url === "/api/functional-knowledge/fact-claims"
        )
          return response([]);
        if (
          url === "/api/content-projects/CONTENT-001/program-shot-revision" &&
          init?.method === "POST"
        )
          return response(detail);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <ContentProjectsPage />
      </QueryClientProvider>,
    );

    await screen.findByRole("heading", { name: "人工编排节目段与镜头" });
    expect(screen.getByText("编排时间线")).toBeInTheDocument();
    expect(screen.getByText("1:00 · 2 段 · 2 镜头")).toBeInTheDocument();
    fireEvent.change(screen.getAllByLabelText("预计时长（毫秒）")[2], {
      target: { value: "20000" },
    });
    expect(screen.getByText("段 1 的段落时长与镜头合计不一致")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "添加节目段" }));
    fireEvent.change(screen.getByLabelText("节目段 3 目标"), {
      target: { value: "收束互动行动" },
    });
    fireEvent.change(screen.getAllByLabelText("进入条件")[2], {
      target: { value: "完成产品讲解" },
    });
    fireEvent.change(screen.getAllByLabelText("退出条件")[2], {
      target: { value: "完成留言引导" },
    });
    fireEvent.change(screen.getAllByLabelText("关联商品")[2], {
      target: { value: "PRODUCT-001, PRODUCT-002" },
    });
    fireEvent.change(screen.getAllByLabelText("互动动作")[2], {
      target: { value: "邀请留言 | 说明使用场景" },
    });
    fireEvent.change(screen.getAllByLabelText("CTA 动作")[2], {
      target: { value: "展示商品卡 | 引导点击" },
    });
    fireEvent.click(screen.getAllByLabelText("成片")[2]);
    fireEvent.change(screen.getAllByLabelText("镜头目标")[2], {
      target: { value: "收束互动镜头" },
    });
    fireEvent.change(screen.getAllByLabelText("必须包含")[2], {
      target: { value: "商品正面, CTA 文案" },
    });
    fireEvent.change(screen.getAllByLabelText("必须避免")[2], {
      target: { value: "遮挡商品" },
    });
    fireEvent.change(screen.getAllByLabelText("构图风格")[2], {
      target: { value: "product_close_up" },
    });
    fireEvent.change(screen.getAllByLabelText("画面焦点")[2], {
      target: { value: "product" },
    });
    fireEvent.change(screen.getAllByLabelText("音频动作")[2], {
      target: { value: "降低背景音乐 | 商品讲解" },
    });
    fireEvent.change(screen.getAllByLabelText("验收条件")[2], {
      target: { value: "商品完整可见\nCTA 可读" },
    });
    fireEvent.click(screen.getAllByLabelText("与前一镜头连续")[2]);
    fireEvent.change(screen.getAllByLabelText("转场提示")[2], {
      target: { value: "保持商品位置" },
    });
    await user.click(screen.getByRole("button", { name: "上移节目段 3" }));
    await user.click(screen.getByRole("button", { name: "上移镜头 3" }));
    await user.click(screen.getByRole("button", { name: "删除节目段 3" }));
    await user.click(
      screen.getByRole("button", { name: "保存节目段与镜头修订" }),
    );

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url.endsWith("/program-shot-revision") &&
            request.init?.method === "POST",
        ),
      ).toBe(true),
    );
    const request = requests.find((item) =>
      item.url.endsWith("/program-shot-revision"),
    );
    const payload = JSON.parse(String(request?.init?.body));
    expect(payload.segments).toHaveLength(2);
    expect(payload.segments[1]).toMatchObject({
      semantic_goal: "收束互动行动",
      script_block_codes: ["BLOCK-001"],
      entry_condition: "完成产品讲解",
      exit_condition: "完成留言引导",
      product_refs: ["PRODUCT-001", "PRODUCT-002"],
      interaction_actions: [{ action: "邀请留言", detail: "说明使用场景" }],
      cta_actions: [{ action: "展示商品卡", detail: "引导点击" }],
      branch_applicability: ["live_room"],
    });
    expect(payload.shots[1]).toMatchObject(
      expect.objectContaining({
        shot_goal: "收束互动镜头",
        program_segment_index: 1,
        script_block_codes: ["BLOCK-001"],
        must_include: ["商品正面", "CTA 文案"],
        must_avoid: ["遮挡商品"],
        composition_intent: { style: "product_close_up", focus: "product" },
        audio_actions: [{ action: "降低背景音乐", detail: "商品讲解" }],
        continuity: { from_previous: true, transition_cue: "保持商品位置" },
        acceptance_criteria: ["商品完整可见", "CTA 可读"],
        branch_applicability: ["live_room", "rendered_video"],
      }),
    );
  });

  it("pins an approved source-backed fact claim with a content revision", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const claim = {
      claim_code: "CLAIM-001",
      fact_code: "FACT-001",
      fact_title: "保修承诺",
      source_evidence_code: "EVIDENCE-001",
      source_title: "产品规格书",
      source_status: "approved",
      claim: "该产品提供 12 个月保修。",
      citation_excerpt: "规格书载明 12 个月保修。",
      status: "approved",
      fingerprint_sha256: "a".repeat(64),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/content-projects") return response([detail]);
        if (url === "/api/content-projects/CONTENT-001") {
          if (init?.method === "PATCH")
            return response({
              ...detail,
              revision_number: 2,
              fact_claims: [
                {
                  claim_code: claim.claim_code,
                  fact_code: claim.fact_code,
                  source_evidence_code: claim.source_evidence_code,
                  claim: claim.claim,
                  citation_excerpt: claim.citation_excerpt,
                  fingerprint_sha256: claim.fingerprint_sha256,
                },
              ],
            });
          return response(detail);
        }
        if (url === "/api/content-projects/CONTENT-001/content-chain-revisions")
          return response([]);
        if (
          url === "/api/live-research/room-templates" ||
          url === "/api/maitu/workbench/product-fact-cards"
        )
          return response([]);
        if (url === "/api/functional-knowledge/fact-claims")
          return response([claim]);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <ContentProjectsPage />
      </QueryClientProvider>,
    );

    const claimOption = await screen.findByRole("checkbox", {
      name: /保修承诺 CLAIM-001/,
    });
    await user.click(claimOption);
    await user.click(screen.getByRole("button", { name: "更新事实输入" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url === "/api/content-projects/CONTENT-001" &&
            request.init?.method === "PATCH",
        ),
      ).toBe(true),
    );
    const request = requests.find(
      (item) =>
        item.url === "/api/content-projects/CONTENT-001" &&
        item.init?.method === "PATCH",
    );
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      expected_revision: 1,
      fact_card_codes: [],
      fact_claim_codes: ["CLAIM-001"],
    });
  });
});
