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

  it("records an explicit reason when an approved effect is revoked", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-learning/decisions") return response([]);
      if (url === "/api/functional-learning/experiments") return response([]);
      if (url === "/api/functional-learning/effects") {
        if (init?.method === "POST") return response({ effect_code: "EFFECT-001", status: "revoked", revoked_reason: "Metric input was corrected." });
        return response([{
          effect_code: "EFFECT-001", attribution_report_code: "ATTR-001", subject_code: "CONTENT-001",
          metric_key: "watchers", evidence_level: "descriptive", status: "approved", note: "Keep the opening.",
          eligibility_snapshot: { qualification: "descriptive_only", selected_session_count: 2 },
        }]);
      }
      if (url === "/api/functional-operations/attribution-reports") return response([]);
      if (url === "/api/content-projects") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><LearningPage /></QueryClientProvider>);

    await screen.findByRole("button", { name: "撤销效果" });
    await user.type(screen.getByLabelText("撤销原因 EFFECT-001"), "Metric input was corrected.");
    await user.click(screen.getByRole("button", { name: "撤销效果" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-learning/effects/EFFECT-001/revoke" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-learning/effects/EFFECT-001/revoke" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ actor: "functional-operator", reason: "Metric input was corrected." });
  });

  it("shows the stable assignment before an operator records an experiment outcome", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-learning/decisions") return response([]);
      if (url === "/api/functional-learning/effects") return response([]);
      if (url === "/api/functional-learning/experiments") return response([{
        experiment_code: "EXP-001", title: "Opening", metric_key: "watchers", variants: ["control", "treatment"],
        registration: { hypothesis: "A concise opening improves watchers.", observation_window: "one day" },
        assignment_strategy: "stable_hash_sha256_v1", results: { control: { average: 0, sample_size: 0 }, treatment: { average: 0, sample_size: 0 } },
      }]);
      if (url === "/api/functional-learning/experiments/EXP-001/assignments") {
        return response({ assignment_code: "ASSIGN-001", experiment_code: "EXP-001", subject_key: "session-001", variant_key: "treatment", assignment_strategy: "stable_hash_sha256_v1", assigned_at: "2026-07-25T00:00:00Z" });
      }
      if (url === "/api/functional-learning/experiments/EXP-001/outcomes") return response({});
      if (url === "/api/functional-operations/attribution-reports") return response([]);
      if (url === "/api/content-projects") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><LearningPage /></QueryClientProvider>);

    await screen.findByText("Opening · watchers");
    await user.type(screen.getByLabelText("实验主体 EXP-001"), "session-001");
    await user.click(screen.getByRole("button", { name: "确定分组" }));
    await screen.findByText("固定版本：treatment");
    await user.clear(screen.getByLabelText("实验指标值 EXP-001"));
    await user.type(screen.getByLabelText("实验指标值 EXP-001"), "42");
    await user.click(screen.getByRole("button", { name: "回填结果" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-learning/experiments/EXP-001/assignments" && request.init?.method === "POST")).toBe(true));
    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-learning/experiments/EXP-001/outcomes" && request.init?.method === "POST")).toBe(true));
    const assignment = requests.find((item) => item.url === "/api/functional-learning/experiments/EXP-001/assignments" && item.init?.method === "POST");
    const request = requests.find((item) => item.url === "/api/functional-learning/experiments/EXP-001/outcomes" && item.init?.method === "POST");
    expect(JSON.parse(String(assignment?.init?.body))).toEqual({ subject_key: "session-001" });
    expect(JSON.parse(String(request?.init?.body))).toEqual({ subject_key: "session-001", metric_value: 42 });
  });

  it("requires a change hypothesis before creating an effect reproduction draft", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-learning/decisions") return response([]);
      if (url === "/api/functional-learning/experiments") return response([]);
      if (url === "/api/functional-learning/effects") return response([{
        effect_code: "EFFECT-001", attribution_report_code: "ATTR-001", subject_code: "CONTENT-001",
        metric_key: "watchers", evidence_level: "descriptive", status: "approved", note: "Keep the opening.",
        eligibility_snapshot: { qualification: "descriptive_only", selected_session_count: 2 },
      }]);
      if (url === "/api/functional-learning/effects/EFFECT-001/reproduce") {
        return response({ effect_code: "EFFECT-001", decision_code: "DEC-001", source_project_code: "CONTENT-001", reproduced_project_code: "CONTENT-002" });
      }
      if (url === "/api/functional-operations/attribution-reports") return response([]);
      if (url === "/api/content-projects") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><LearningPage /></QueryClientProvider>);

    await screen.findByRole("button", { name: "建立草稿" });
    expect(screen.getByRole("button", { name: "建立草稿" })).toBeDisabled();
    await user.type(screen.getByLabelText("再生产假设 EFFECT-001"), "Preserve the opening and evaluate the new draft.");
    await user.click(screen.getByRole("button", { name: "建立草稿" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-learning/effects/EFFECT-001/reproduce" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-learning/effects/EFFECT-001/reproduce" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ change_hypothesis: "Preserve the opening and evaluate the new draft." });
  });
});
