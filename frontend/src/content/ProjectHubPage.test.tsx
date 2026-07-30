import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectHubPage } from "./ProjectHubPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ProjectHubPage search="" /></QueryClientProvider>);
}

describe("project creation wizard", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/console/projects");
    vi.restoreAllMocks();
  });

  it("collects business intent through four steps and generates identifiers itself", async () => {
    const requests: Array<{ url: string; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      requests.push({ url, body });
      if (url.endsWith("/api/content-projects") && init?.method === "POST") {
        return new Response(JSON.stringify({ project_code: "CONTENT-GENERATED-001", title: body?.title, revision_number: 1, status: "draft", generation_goal: body?.generation_goal, updated_at: "2026-07-28T00:00:00Z" }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "新建项目" }));
    await user.click(screen.getByRole("button", { name: /下一步/ }));
    expect(await screen.findByText("请填写直播间 ID")).toBeInTheDocument();
    expect(screen.getByText("请填写直播间标题")).toBeInTheDocument();

    await user.type(screen.getByLabelText("直播间 ID"), "39826");
    await user.type(screen.getByLabelText("直播间标题"), "盛夏新品直播");
    await user.type(screen.getByLabelText("生成目标"), "面向新用户讲清新品价值并引导查看商品详情");
    await user.click(screen.getByRole("button", { name: /下一步/ }));
    expect(screen.getByRole("heading", { name: "补充创意方向" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("主题"), "夏日轻食");
    await user.click(screen.getByRole("button", { name: /下一步/ }));
    expect(screen.getByRole("heading", { name: "选择参考模板" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /下一步/ }));
    expect(screen.getByRole("heading", { name: "选择项目素材" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/项目.*code/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "创建项目" }));

    const create = requests.find((item) => item.url.endsWith("/api/content-projects") && item.body);
    expect(create?.body).toMatchObject({ target_live_room_id: "39826", title: "盛夏新品直播", theme: "夏日轻食" });
    expect(create?.body).not.toHaveProperty("project_code");
    expect(window.location.search).toContain("project=CONTENT-GENERATED-001");
  });
});
