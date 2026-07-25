import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GovernanceRunsPage } from "./GovernanceRunsPage";

const run = {
  run_code: "RUN-001", workflow_type: "content_generation", subject_type: "content_project", subject_code: "CONTENT-001", subject_revision: 2,
  status: "waiting_human", priority: 50, progress_completed: 1, progress_total: 3, queue_reason: "waiting_review", waiting_reason: "approval task", budget: { tokens: 1000 }, actual_cost: { tokens: 230 }, requested_by: "operator-a", updated_at: "2026-07-25T00:00:00Z",
  steps: [{ step_code: "STEP-001", step_type: "generate_script", sort_order: 0, status: "succeeded", priority: 50, attempt: 1, max_attempts: 3, side_effect_level: "pure_compute", timeout_seconds: 60, depends_on: [] }],
  human_tasks: [{ task_code: "TASK-001", run_code: "RUN-001", task_type: "approve_content", status: "open", revision: 1, priority: 50, owner_principal: "operator-a", subject: {}, created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" }],
};

describe("GovernanceRunsPage", () => {
  it("loads a deep-linked run with steps and human task details", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/workflow-runs/RUN-001") return new Response(JSON.stringify(run), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><GovernanceRunsPage search="?run=RUN-001&task=TASK-001" tasks={[{ itemCode: "TASK-001", itemType: "human_task", title: "approve_content", status: "open", priority: 50, summary: "approval task", href: "/governance/runs?run=RUN-001&task=TASK-001", updatedAt: "2026-07-25T00:00:00Z", runCode: "RUN-001", progressCompleted: 1, progressTotal: 3 }]} notifications={[]} loading={false} /></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "content_generation / CONTENT-001" })).toBeInTheDocument();
    expect(screen.getByText("generate_script")).toBeInTheDocument();
    expect(screen.getAllByText("approve_content")).toHaveLength(2);
    expect(screen.getAllByText("approval task")).toHaveLength(2);
  });

  it("submits a structured reason to cancel a non-terminal local run", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/workflow-runs/RUN-001" && init?.method !== "POST") return new Response(JSON.stringify(run), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/workflow-runs/RUN-001/cancel") return new Response(JSON.stringify({ ...run, status: "cancelled" }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><GovernanceRunsPage search="?run=RUN-001" tasks={[]} notifications={[]} loading={false} /></QueryClientProvider>);
    await screen.findByRole("heading", { name: "content_generation / CONTENT-001" });
    await user.type(screen.getByLabelText("取消原因"), "superseded by a newer project revision");
    await user.click(screen.getByRole("button", { name: "取消运行" }));
    await waitFor(() => expect(requests.some((item) => item.url === "/api/workflow-runs/RUN-001/cancel")).toBe(true));
    const request = requests.find((item) => item.url === "/api/workflow-runs/RUN-001/cancel");
    expect(request?.init?.body).toBe(JSON.stringify({ reason: "superseded by a newer project revision" }));
  });
});
