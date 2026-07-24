import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchApiError } from "../workbench/api";
import { consoleApi } from "./api";
import { DEMO_CONTENT_ENTITY } from "./demoData";
import { EntityDraftEditor } from "./EntityDraftEditor";


describe("Entity draft autosave", () => {
  it("keeps local edits and exposes a reload action on a stale revision conflict", async () => {
    vi.spyOn(consoleApi, "draft").mockResolvedValue(undefined);
    vi.spyOn(consoleApi, "saveDraft").mockRejectedValue(new WorkbenchApiError(
      "Console draft changed since it was loaded",
      409,
      {},
      {
        code: "STALE_REVISION",
        state: "stale",
        message: "Console draft changed since it was loaded",
        impact: "No change was committed from the stale request.",
        evidence: [],
        nextStep: "Reload the latest revision.",
        retryable: false,
      },
    ));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><EntityDraftEditor detail={DEMO_CONTENT_ENTITY} demoMode={false} onDraftChange={() => undefined} /></QueryClientProvider>);

    await screen.findByText("尚未修改");
    const goal = screen.getByRole("textbox", { name: "生成目标" });
    await user.clear(goal);
    await user.type(goal, "冲突时保留的本地编辑");

    expect(await screen.findByText("版本冲突", {}, { timeout: 2500 })).toBeInTheDocument();
    expect(goal).toHaveValue("冲突时保留的本地编辑");
    expect(screen.getByRole("button", { name: "载入服务器草稿" })).toBeInTheDocument();
    expect(screen.queryByText("已保存 · d1")).not.toBeInTheDocument();
  });
});
