import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ConsoleApp, { Workspace } from "./ConsoleApp";
import { ConsoleErrorBoundary } from "./ErrorBoundary";


function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ConsoleApp /></QueryClientProvider>);
}


describe("AssetGraph Console", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/console/?demo=1");
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  });

  it("starts from tasks and exceptions with shared navigation, search, and centers", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(screen.getByRole("heading", { name: "我的任务与异常" })).toBeInTheDocument();
    expect(await screen.findByText("模板发布复核")).toBeInTheDocument();
    expect(await screen.findByText("RELEASE_RECONCILE_REQUIRED")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "一级产品导航" })).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "全局搜索" }), "龙谕");
    expect(await screen.findByText("龙谕龙8商品主图")).toBeInTheDocument();
    await user.click(screen.getByText("龙谕龙8商品主图"));
    expect(window.location.pathname).toBe("/assets/library");
    expect(window.location.search).toBe("?asset=AG-IMG-20260710-000101");
    const inspector = await screen.findByRole("complementary", { name: "实体版本详情" });
    expect(within(inspector).getByRole("button", { name: /^r3 ready/ })).toBeInTheDocument();
    expect(within(inspector).getByRole("button", { name: /^r2 ready/ })).toBeInTheDocument();
    expect(within(inspector).getByText("$.placement.region")).toBeInTheDocument();
    expect(within(inspector).getByText("maitu")).toBeInTheDocument();
    expect(within(inspector).getByText("RUN-MAITU-0387")).toBeInTheDocument();
    expect(within(inspector).getByText("RELEASE-20260722-008")).toBeInTheDocument();
    await user.click(within(inspector).getByTitle("关闭实体详情"));
    expect(new URLSearchParams(window.location.search).has("asset")).toBe(false);

    await user.click(screen.getByTitle("任务中心"));
    expect(screen.getByRole("complementary", { name: "任务中心" })).toBeInTheDocument();
    await user.click(screen.getByTitle("关闭"));
    await user.click(screen.getByTitle("通知"));
    expect(screen.getByRole("complementary", { name: "通知中心" })).toBeInTheDocument();
  });

  it("keeps stable research routes inside the same Console", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole("link", { name: "直播研究" }));
    expect(window.location.pathname).toBe("/research/live-sources");
    expect(await screen.findByText("葡萄酒品牌自播间")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "录屏场次" }));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("sessions");
    expect(new URLSearchParams(window.location.search).get("session")).toBe("DY-CAP-DEMO-001");
    expect(await screen.findByText("设置永久片段范围")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "内容策略" }));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("strategies");
    expect(await screen.findByText("创建内容策略模板")).toBeInTheDocument();
  });

  it("remounts the live-room workspace when an internal deep link changes run", async () => {
    const plans = {
      "RUN-A": { plan_code: "RUN-A", expected_title: "深链计划 A", status: "ready", execution_status: "not_requested", blueprint: { scenes: [] }, build_plan: { operations: [] }, gate_results: [], quality_report: {}, execution_evidence: {} },
      "RUN-B": { plan_code: "RUN-B", expected_title: "深链计划 B", status: "ready", execution_status: "not_requested", blueprint: { scenes: [] }, build_plan: { operations: [] }, gate_results: [], quality_report: {}, execution_evidence: {} },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const planCode = url.match(/functional-live-room-plans\/(RUN-[AB])/)?.[1];
      const body = planCode ? plans[planCode as keyof typeof plans] : url.endsWith("/functional-live-room-plans") ? Object.values(plans) : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    window.history.replaceState(null, "", "/production/live-rooms?demo=1&run=UNKNOWN-RUN");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <Workspace pathname="/production/live-rooms" search="?demo=1&run=UNKNOWN-RUN" tasks={[]} notifications={[]} loading={false} />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "深链计划 A" })).toBeInTheDocument();
    window.history.replaceState(null, "", "/production/live-rooms?demo=1&run=RUN-B");
    rerender(
      <QueryClientProvider client={client}>
        <Workspace pathname="/production/live-rooms" search="?demo=1&run=RUN-B" tasks={[]} notifications={[]} loading={false} />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "深链计划 B" })).toBeInTheDocument();
  });

  it("autosaves a content-project draft before opening the explicit confirm command", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.type(screen.getByRole("textbox", { name: "全局搜索" }), "贺兰");
    await user.click(await screen.findByText("贺兰山东麓品鉴直播"));
    const inspector = await screen.findByRole("complementary", { name: "实体版本详情" });
    await within(inspector).findByText("尚未修改");
    const goal = within(inspector).getByRole("textbox", { name: "生成目标" });
    await user.clear(goal);
    await user.type(goal, "固定产区事实并完成入门品鉴引导");

    expect(await within(inspector).findByText("已保存 · d1", {}, { timeout: 2500 })).toBeInTheDocument();
    const commandButton = within(inspector).getByRole("button", { name: "确认输入" });
    expect(commandButton).toBeEnabled();
    await user.click(commandButton);
    const dialog = screen.getByRole("dialog", { name: "确认输入" });
    expect(within(dialog).getByText("CONTENT-20260722-004 · r1")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "确认输入" }));
    expect(await within(dialog).findByText("命令已记录")).toBeInTheDocument();
    expect(within(dialog).getByText("COMMAND-DEMO-CONFIRM")).toBeInTheDocument();
  });
});


describe("Console error boundary", () => {
  it("stops rendering and exposes a stable rule without stack details", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function BrokenWorkspace(): never {
      throw new Error("credential-value-must-not-render");
    }

    render(<ConsoleErrorBoundary><BrokenWorkspace /></ConsoleErrorBoundary>);

    expect(screen.getByText("ERROR_BOUNDARY_CAPTURED")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("未自动重放任何命令");
    expect(screen.queryByText("credential-value-must-not-render")).not.toBeInTheDocument();
  });
});
