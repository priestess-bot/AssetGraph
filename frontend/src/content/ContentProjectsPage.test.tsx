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
  content: {},
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
        template_sources: [],
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
        branch_applicability: ["live_room"],
        must_include: [],
        must_avoid: [],
        script_block_codes: ["BLOCK-002"],
      },
    ],
  },
};

describe("ContentProjectsPage", () => {
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
          url === "/api/maitu/workbench/product-fact-cards"
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
    fireEvent.change(screen.getAllByLabelText("镜头目标")[2], {
      target: { value: "收束互动镜头" },
    });
    fireEvent.change(screen.getAllByLabelText("必须包含")[2], {
      target: { value: "商品正面, CTA 文案" },
    });
    fireEvent.change(screen.getAllByLabelText("必须避免")[2], {
      target: { value: "遮挡商品" },
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
    });
    expect(payload.shots[1]).toMatchObject(
      expect.objectContaining({
        shot_goal: "收束互动镜头",
        program_segment_index: 1,
        script_block_codes: ["BLOCK-001"],
        must_include: ["商品正面", "CTA 文案"],
        must_avoid: ["遮挡商品"],
      }),
    );
  });
});
