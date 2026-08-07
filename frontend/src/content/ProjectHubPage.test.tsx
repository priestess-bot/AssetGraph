import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectHubPage } from "./ProjectHubPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ProjectHubPage search="" /></QueryClientProvider>);
}

describe("guided project creation", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/console/projects");
    vi.restoreAllMocks();
  });

  it("collects only the title and Maitu room id", async () => {
    const requests: Array<{ url: string; body?: Record<string, unknown>; idempotencyKey?: string | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      requests.push({ url, body, idempotencyKey: new Headers(init?.headers).get("Idempotency-Key") });
      if (url.endsWith("/api/content-projects/guided") && init?.method === "POST") {
        return new Response(JSON.stringify({
          workflow_version: "guided-live.v1",
          project: { project_code: "CONTENT-GENERATED-001", title: body?.title, revision_number: 1, status: "confirmed", target_live_room_id: body?.target_live_room_id, theme: "", updated_at: "2026-07-28T00:00:00Z" },
          material_pool: { pool_revision_code: "POOL-001", revision_number: 1, selected_asset_codes: [], fingerprint_sha256: "a".repeat(64) },
          jobs: {}, gates: {},
        }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "新建项目" }));
    await user.type(screen.getByLabelText("项目标题"), "盛夏新品直播");
    await user.type(screen.getByLabelText("麦兔直播间号"), "39826");
    await user.click(screen.getByRole("button", { name: "创建项目" }));

    const create = requests.find((item) => item.url.endsWith("/api/content-projects/guided") && item.body);
    expect(create?.body).toEqual({ target_live_room_id: "39826", title: "盛夏新品直播" });
    expect(create?.body).not.toHaveProperty("project_code");
    expect(create?.idempotencyKey).toMatch(/^guided-create:/);
    await waitFor(() => expect(window.location.search).toContain("project=CONTENT-GENERATED-001"));
    expect(window.location.pathname).toBe("/console/projects");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("reuses the creation idempotency key when a request is retried", async () => {
    const createKeys: Array<string | null> = [];
    let createAttempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/content-projects/guided") && init?.method === "POST") {
        createAttempts += 1;
        createKeys.push(new Headers(init.headers).get("Idempotency-Key"));
        if (createAttempts === 1) {
          return new Response(JSON.stringify({ detail: "temporary failure" }), { status: 503, headers: { "Content-Type": "application/json" } });
        }
        return new Response(JSON.stringify({
          workflow_version: "guided-live.v1",
          project: { project_code: "CONTENT-GENERATED-RETRY", title: "重试项目", revision_number: 1, status: "confirmed", target_live_room_id: "39826", theme: "", updated_at: "2026-07-28T00:00:00Z" },
          material_pool: { pool_revision_code: "POOL-RETRY", revision_number: 1, selected_asset_codes: [], fingerprint_sha256: "a".repeat(64) },
          jobs: {}, gates: {},
        }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "新建项目" }));
    await user.type(screen.getByLabelText("项目标题"), "重试项目");
    await user.type(screen.getByLabelText("麦兔直播间号"), "39826");
    await user.click(screen.getByRole("button", { name: "创建项目" }));
    await screen.findByText("项目未创建");
    await user.click(screen.getByRole("button", { name: "创建项目" }));

    await waitFor(() => expect(window.location.search).toContain("CONTENT-GENERATED-RETRY"));
    expect(window.location.pathname).toBe("/console/projects");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(createKeys).toHaveLength(2);
    expect(createKeys[0]).toMatch(/^guided-create:/);
    expect(createKeys[1]).toBe(createKeys[0]);
  });
});
