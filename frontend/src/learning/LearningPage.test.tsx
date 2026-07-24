import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LearningPage } from "./LearningPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("LearningPage", () => {
  it("links an operator decision to an existing descriptive attribution report", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-learning/decisions") {
        if (init?.method === "POST") return response({ decision_code: "DEC-001", observation: "Opening held attention", recommendation: "Keep the opening", attribution_report_code: "ATTR-001" });
        return response([]);
      }
      if (url === "/api/functional-learning/experiments") return response([]);
      if (url === "/api/functional-learning/effects") return response([]);
      if (url === "/api/functional-operations/attribution-reports") return response([{ report_code: "ATTR-001", metric_key: "watchers", evidence_level: "descriptive", session_codes: ["OPS-001"] }]);
      if (url === "/api/content-projects") return response([{ project_code: "CONTENT-001", title: "Product launch" }]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><LearningPage /></QueryClientProvider>);

    await screen.findByRole("heading", { name: "学习与实验" });
    await user.type(screen.getByLabelText("观察"), "Opening held attention");
    await user.type(screen.getByLabelText("再生产建议"), "Keep the opening");
    await user.selectOptions(screen.getByLabelText("归因报告"), "ATTR-001");
    await user.click(screen.getByRole("button", { name: "记录决策" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-learning/decisions" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-learning/decisions" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ observation: "Opening held attention", recommendation: "Keep the opening", attribution_report_code: "ATTR-001" });
  });

  it("creates a frozen effect candidate from a report and content project", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-learning/decisions") return response([]);
      if (url === "/api/functional-learning/experiments") return response([]);
      if (url === "/api/functional-learning/effects") {
        if (init?.method === "POST") return response({ effect_code: "EFFECT-001", status: "candidate" });
        return response([]);
      }
      if (url === "/api/functional-operations/attribution-reports") return response([{ report_code: "ATTR-001", metric_key: "watchers", evidence_level: "descriptive", session_codes: ["OPS-001"] }]);
      if (url === "/api/content-projects") return response([{ project_code: "CONTENT-001", title: "Product launch" }]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><LearningPage /></QueryClientProvider>);

    await screen.findByRole("heading", { name: "效果证据" });
    await user.selectOptions(screen.getByLabelText("效果归因报告"), "ATTR-001");
    await user.selectOptions(screen.getByLabelText("再生产源项目"), "CONTENT-001");
    await user.type(screen.getByLabelText("人工判断"), "Keep the opening rhythm.");
    await user.click(screen.getByRole("button", { name: "建立效果证据" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-learning/effects" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-learning/effects" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      attribution_report_code: "ATTR-001",
      subject_type: "content_project",
      subject_code: "CONTENT-001",
      note: "Keep the opening rhythm.",
    });
  });
});
