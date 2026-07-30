import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ConsoleApp from "./ConsoleApp";
import { ConsoleErrorBoundary } from "./ErrorBoundary";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ConsoleApp /></QueryClientProvider>);
}

describe("unified product console", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/console/?demo=1");
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  });

  it("presents the seven business workspaces in one navigation", () => {
    renderApp();
    const navigation = screen.getByRole("navigation", { name: "一级产品导航" });
    for (const label of ["业务概览", "素材库", "直播模板", "知识库", "内容项目", "运营分析", "效果学习"]) {
      expect(within(navigation).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByText("排播")).not.toBeInTheDocument();
    expect(screen.queryByText("数据治理")).not.toBeInTheDocument();
  });

  it("shows business notification copy without backend codes", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getByTitle("通知"));
    const drawer = screen.getByRole("complementary", { name: "通知中心" });
    expect(within(drawer).getByText("项目使用的内容已有更新")).toBeInTheDocument();
    expect(within(drawer).getByText("交付结果需要核对")).toBeInTheDocument();
    expect(within(drawer).queryByText("LINEAGE_INPUT_STALE")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("ALERT-LINEAGE-009")).not.toBeInTheDocument();
  });

  it("opens global search results in the canonical product route", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByRole("textbox", { name: "全局搜索" }), "龙谕");
    await user.click(await screen.findByText("龙谕龙8商品主图"));
    expect(window.location.pathname).toBe("/console/assets");
    expect(new URLSearchParams(window.location.search).has("asset")).toBe(true);
  });

  it("opens the workbench without requiring a control-plane credential", () => {
    window.history.replaceState(null, "", "/console/");
    renderApp();
    expect(screen.getByRole("navigation", { name: "一级产品导航" })).toBeInTheDocument();
    expect(screen.getByText("浏览工作区")).toBeInTheDocument();
    expect(screen.queryByText("运营控制台登录")).not.toBeInTheDocument();
    expect(screen.queryByText("访问凭据")).not.toBeInTheDocument();
  });
});

describe("Console error boundary", () => {
  it("offers recovery actions without a stack or internal code", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function BrokenWorkspace(): never {
      throw new Error("credential-value-must-not-render");
    }
    render(<ConsoleErrorBoundary><BrokenWorkspace /></ConsoleErrorBoundary>);
    expect(screen.getByText("当前工作区无法显示")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("未自动重放任何命令");
    expect(screen.queryByText("ERROR_BOUNDARY_CAPTURED")).not.toBeInTheDocument();
    expect(screen.queryByText("credential-value-must-not-render")).not.toBeInTheDocument();
  });
});
