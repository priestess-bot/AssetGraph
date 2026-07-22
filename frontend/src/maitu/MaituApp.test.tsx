import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MaituApp from "./MaituApp";
import { initialReferenceTemplatePin } from "./ProductionPage";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MaituApp /></QueryClientProvider>);
}

describe("maitu production workbench", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/maitu/");
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  });

  it("accepts only a complete immutable reference template pin", () => {
    const fingerprint = "a".repeat(64);
    expect(initialReferenceTemplatePin(`?reference_template_code=LR-TPL-001&reference_template_revision_number=2&reference_template_projection_fingerprint=${fingerprint}`)).toEqual({
      reference_template_code: "LR-TPL-001",
      reference_template_revision_number: 2,
      reference_template_projection_fingerprint: fingerprint,
    });
    expect(initialReferenceTemplatePin("?reference_template_code=LR-TPL-001")).toBeUndefined();
    expect(initialReferenceTemplatePin("?reference_template_code=LR-TPL-001&reference_template_revision_number=2")).toBeUndefined();
  });

  it("keeps the complete production workflow available in demo fallback", async () => {
    const user = userEvent.setup();
    renderApp();
    expect(screen.queryByRole("link", { name: /视频工坊/ })).not.toBeInTheDocument();
    expect((await screen.findAllByText("夏日朋友聚餐选酒")).length).toBeGreaterThan(0);
    expect(screen.getByText("需求决策 · 3 项")).toBeInTheDocument();
    expect(screen.getByLabelText("Replan 素材快照")).toHaveValue("INV-DEMO-20260720-001");
    expect(screen.getByRole("button", { name: "执行预检" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "写入草稿" })).toBeDisabled();

    await user.click(screen.getByRole("tab", { name: "资源与事实" }));
    expect(await screen.findByText("麦兔资源同步")).toBeInTheDocument();
    expect(screen.getByText("INV-DEMO-20260720-001")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Gemini 回填" }));
    expect(await screen.findByText("视频分析与回填")).toBeInTheDocument();
    expect(screen.getByText("人工网页 JSON 回填")).toBeInTheDocument();
  });
});
