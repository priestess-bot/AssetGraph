import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LiveResearchApp from "./LiveResearchApp";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><LiveResearchApp /></QueryClientProvider>);
}

describe("live template research workbench", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/live-research/");
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  });

  it("navigates watch, capture and template review workflows", async () => {
    const user = userEvent.setup();
    renderApp();
    expect(screen.queryByRole("link", { name: /视频工坊/ })).not.toBeInTheDocument();
    expect(await screen.findByText("葡萄酒品牌自播间")).toBeInTheDocument();
    expect(screen.getByText("完整原始事件永久保存但不直接暴露")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "采集场次" }));
    expect(await screen.findByText("设置永久片段范围")).toBeInTheDocument();
    const inField = screen.getByLabelText("IN（秒）");
    const outField = screen.getByLabelText("OUT（秒）");
    await user.clear(inField); await user.type(inField, "10");
    await user.clear(outField); await user.type(outField, "20");
    expect(screen.getByText("10.0 秒")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "模板草稿" }));
    expect((await screen.findAllByText("问题钩子到餐桌场景转换")).length).toBeGreaterThan(0);
    expect(screen.getByText("外部平面视频不能恢复真实图层")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发布参考模板" })).toBeDisabled();

    await user.click(screen.getByRole("tab", { name: "已发布模板" }));
    expect(await screen.findByText("发布版本只读")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存新修订" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "发布参考模板" })).not.toBeInTheDocument();
  });
});
