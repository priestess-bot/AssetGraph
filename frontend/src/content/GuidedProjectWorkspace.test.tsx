import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GuidedProjectWorkspace } from "./GuidedProjectWorkspace";


const projectCode = "CONTENT-GUIDED-TEST";

function workflow(overrides: Record<string, unknown> = {}) {
  return {
    workflow_version: "guided-live.v1",
    project: { project_code: projectCode, title: "测试直播项目", revision_number: 2, status: "confirmed", target_live_room_id: "39826", theme: "夏季新品", updated_at: "2026-08-06T02:00:00Z" },
    material_pool: { pool_revision_code: "POOL-001", revision_number: 1, selected_asset_codes: [], fingerprint_sha256: "a".repeat(64) },
    outline: { story_brief_code: "STORY-001", revision_number: 1, status: "draft", sections: [{ section_key: "section-1", title: "开场", objective: "建立主题", key_points: ["欢迎"] }], created_at: "2026-08-06T02:01:00Z" },
    jobs: {},
    history: [],
    gates: { setup_editable: true, outline_current: true, outline_confirmed: false, script_current: false, script_confirmed: false, storyboard_current: false, storyboard_confirmed: false },
    ...overrides,
  };
}

const summary = {
  project_code: projectCode,
  title: "测试直播项目",
  status: "confirmed",
  revision_number: 2,
  generation_goal: "夏季新品",
  brief: {}, script: {}, live_room: {}, video: {}, delivery: {}, operations: {}, activity: [],
  updated_at: "2026-08-06T02:00:00Z",
};

function renderWorkspace(tab: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><GuidedProjectWorkspace projectCode={projectCode} tab={tab} /></QueryClientProvider>);
}

describe("guided project workspace", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", `/console/projects?project=${projectCode}&tab=outline`);
  });

  it("saves dirty outline edits before confirming the returned revision", async () => {
    let current = workflow();
    const writes: Array<{ url: string; method?: string; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      if (init?.method && init.method !== "GET") writes.push({ url, method: init.method, body });
      if (url.includes("/api/assets?")) return Response.json([]);
      if (url.endsWith(`/api/content-projects/${projectCode}/workspace-summary`)) return Response.json(summary);
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow/outline`) && init?.method === "PUT") {
        current = workflow({
          outline: { ...(current.outline as Record<string, unknown>), revision_number: 2, sections: body?.sections },
        });
        return Response.json(current);
      }
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow/outline/confirm`) && init?.method === "POST") {
        current = workflow({
          outline: { ...(current.outline as Record<string, unknown>), status: "confirmed", confirmed_at: "2026-08-06T02:03:00Z" },
          gates: { ...(current.gates as Record<string, unknown>), outline_confirmed: true, setup_editable: false },
        });
        return Response.json(current);
      }
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow`)) return Response.json(current);
      return new Response("not found", { status: 404 });
    }));
    const user = userEvent.setup();
    renderWorkspace("outline");

    const title = await screen.findByLabelText("第 1 段标题");
    await user.clear(title);
    await user.type(title, "人工修正开场");
    await user.click(screen.getByRole("button", { name: "确认大纲" }));

    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[0]).toMatchObject({ method: "PUT", body: { expected_revision: 1 } });
    expect((writes[0].body?.sections as Array<Record<string, unknown>>)[0].title).toBe("人工修正开场");
    expect(writes[1]).toMatchObject({ method: "POST", body: { expected_revision: 2 } });
  });

  it("offers regeneration instead of editable dead controls for a stale draft script", async () => {
    const current = workflow({
      outline: { story_brief_code: "STORY-001", revision_number: 2, status: "confirmed", sections: [{ section_key: "section-1", title: "开场", objective: "建立主题", key_points: ["欢迎"] }], created_at: "2026-08-06T02:01:00Z" },
      script: { script_revision_code: "SCRIPT-001", revision_number: 1, status: "draft", title: "测试脚本", source_outline_revision: 1, source_material_pool_revision: 1, blocks: [{ block_code: "BLOCK-001", sort_order: 0, section_key: "section-1", content: "旧脚本" }], requirements: [], created_at: "2026-08-06T02:02:00Z" },
      gates: { setup_editable: false, outline_current: true, outline_confirmed: true, script_current: false, script_confirmed: false, storyboard_current: false, storyboard_confirmed: false },
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/assets?")) return Response.json([]);
      if (url.endsWith(`/workspace-summary`)) return Response.json(summary);
      return Response.json(current);
    }));
    renderWorkspace("script");

    expect(await screen.findByRole("button", { name: "基于当前大纲重新生成" })).toBeEnabled();
    expect(screen.getByLabelText("第 1 段直播话术")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "确认脚本" })).not.toBeInTheDocument();
  });

  it("keeps the video stage locked until the current storyboard is confirmed", async () => {
    const current = workflow();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/assets?")) return Response.json([]);
      if (url.endsWith(`/workspace-summary`)) return Response.json(summary);
      return Response.json(current);
    }));
    renderWorkspace("video");

    expect(await screen.findByText("成片尚未解锁")).toBeInTheDocument();
  });

  it("applies an optimized theme only after the operator chooses the candidate and then saves it", async () => {
    let current = workflow();
    const writes: Array<{ url: string; method?: string; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      if (init?.method && init.method !== "GET") writes.push({ url, method: init.method, body });
      if (url.includes("/api/assets?")) return Response.json([{ asset_code: "AG-001", title: "商品主图", original_filename: "product.png", asset_type: "image", material_roles: ["product_display"], execution_capability: "maitu_bound", rights_status: "pending" }]);
      if (url.endsWith(`/api/content-projects/${projectCode}/workspace-summary`)) return Response.json(summary);
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow/maitu-room-configuration`)) return Response.json({ status: "ready", configured: true, digital_human_name: "数字人 A", voice_name: "音色 A" });
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow/setup/theme-optimize`) && init?.method === "POST") return Response.json({ theme_candidate: { theme: "夏季新品清凉专场", rationale: "突出季节卖点" } }, { status: 202 });
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow/setup`) && init?.method === "PATCH") {
        current = workflow({ project: { ...(current.project as Record<string, unknown>), theme: body?.theme, revision_number: 3 } });
        return Response.json(current);
      }
      if (url.endsWith(`/api/content-projects/${projectCode}/guided-workflow`)) return Response.json(current);
      return new Response("not found", { status: 404 });
    }));
    const user = userEvent.setup();
    renderWorkspace("setup");

    expect(await screen.findByRole("button", { name: "全部素材（1）" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "优化主题" }));
    expect(await screen.findByText("AI 主题候选")).toBeInTheDocument();
    expect(screen.getByLabelText("直播主题")).toHaveValue("夏季新品");
    expect(writes.some((item) => item.url.endsWith("theme-optimize"))).toBe(true);
    expect(writes.some((item) => item.url.endsWith("/setup"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "应用到编辑框" }));
    expect(screen.getByLabelText("直播主题")).toHaveValue("夏季新品清凉专场");
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(writes.some((item) => item.url.endsWith("/setup") && item.method === "PATCH")).toBe(true));
  });

  it("shows key-point citations and starts a direct section regeneration job", async () => {
    const current = workflow({
      outline: { story_brief_code: "STORY-001", revision_number: 1, status: "draft", sections: [{ section_key: "section-1", title: "开场", objective: "建立主题", key_points: [{ text: "介绍常温保存", citations: [{ citation_code: "FACT-001", title: "商品卖点", excerpt: "常温保存。" }] }] }], created_at: "2026-08-06T02:01:00Z" },
    });
    const writes: Array<{ url: string; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") writes.push({ url, body: typeof init.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined });
      if (url.includes("/api/assets?")) return Response.json([]);
      if (url.endsWith(`/workspace-summary`)) return Response.json(summary);
      if (url.endsWith(`/outline/sections/section-1/regenerate`)) return Response.json({ job_code: "CGEN-SECTION", stage: "outline", operation: "outline_section_regenerate", target_section_key: "section-1", status: "queued", total_items: 1, completed_items: 0, attempts: 0, max_attempts: 3, updated_at: "2026-08-06T02:03:00Z" }, { status: 202 });
      return Response.json(current);
    }));
    const user = userEvent.setup();
    renderWorkspace("outline");

    expect(await screen.findByText("商品卖点")).toBeInTheDocument();
    expect(screen.getByText("常温保存。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "引导重生成" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "重新生成此段" }));
    await waitFor(() => expect(writes).toContainEqual({ url: expect.stringContaining("/outline/sections/section-1/regenerate"), body: { expected_revision: 1 } }));
    expect(await screen.findByText("等待重生成")).toBeInTheDocument();
  });

  it("hides the archived script immediately while regeneration is running", async () => {
    const current = workflow({
      outline: { story_brief_code: "STORY-001", revision_number: 2, status: "confirmed", sections: [{ section_key: "section-1", title: "开场", objective: "建立主题", key_points: ["欢迎"] }], created_at: "2026-08-06T02:01:00Z" },
      script: { script_revision_code: "SCRIPT-001", revision_number: 1, status: "draft", title: "测试脚本", source_outline_revision: 1, source_material_pool_revision: 1, blocks: [{ block_code: "BLOCK-001", sort_order: 0, section_key: "section-1", content: "旧脚本内容" }], requirements: [], created_at: "2026-08-06T02:02:00Z" },
      gates: { setup_editable: false, outline_current: true, outline_confirmed: true, script_current: false, script_confirmed: false, storyboard_current: false, storyboard_confirmed: false },
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/assets?")) return Response.json([]);
      if (url.endsWith(`/workspace-summary`)) return Response.json(summary);
      if (url.endsWith(`/guided-workflow/script/generate`)) return Response.json({ job_code: "CGEN-SCRIPT", stage: "script", status: "queued", total_items: 1, completed_items: 0, attempts: 0, max_attempts: 3, updated_at: "2026-08-06T02:03:00Z" }, { status: 202 });
      return Response.json(current);
    }));
    const user = userEvent.setup();
    renderWorkspace("script");

    expect(await screen.findByDisplayValue("旧脚本内容")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "基于当前大纲重新生成" }));
    expect(await screen.findByText("旧脚本已存档")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("旧脚本内容")).not.toBeInTheDocument();
  });
});
