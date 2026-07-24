import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OperationsPage } from "./OperationsPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><OperationsPage view="sessions" /></QueryClientProvider>);
}

describe("OperationsPage", () => {
  it("records the operator-entered session interval and distinguishes observed evidence", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-operations/sessions" && init?.method === "POST") return response({ session_code: "OPS-001", title: "晚场", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:30:00Z", metrics: { watchers: 12 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:31:00Z" });
      if (url === "/api/functional-operations/sessions") return response([]);
      if (url === "/api/functional-operations/exposures" || url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      if (url === "/api/functional-operations/sessions/OPS-001/content-timeline") return response({ session_code: "OPS-001", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:30:00Z", total_seconds: 5400, observed_seconds: 0, coverage_ratio: 0, unobserved_seconds: 5400, status: "resolved", missing_plan_codes: [], spans: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "运营场次与实际展示" });
    await user.type(screen.getByLabelText("场次名称"), "晚场");
    fireEvent.change(screen.getByLabelText("场次开始"), { target: { value: "2026-07-20T20:00" } });
    fireEvent.change(screen.getByLabelText("场次结束"), { target: { value: "2026-07-20T21:30" } });
    fireEvent.change(screen.getByLabelText("指标数值 1"), { target: { value: "120" } });
    await user.click(screen.getByRole("button", { name: "添加指标" }));
    await user.type(screen.getByLabelText("指标名称 2"), "orders");
    fireEvent.change(screen.getByLabelText("指标数值 2"), { target: { value: "8" } });
    await user.click(screen.getByRole("button", { name: "登记场次" }));

    const request = requests.find((item) => item.url === "/api/functional-operations/sessions" && item.init?.method === "POST");
    const body = JSON.parse(String(request?.init?.body));
    expect(body.started_at).toBe(new Date("2026-07-20T20:00").toISOString());
    expect(body.ended_at).toBe(new Date("2026-07-20T21:30").toISOString());
    expect(body.metrics).toEqual({ watchers: 120, orders: 8 });
  });

  it("labels a session as observed only when it has an active exposure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/functional-operations/sessions") return response([{ session_code: "OPS-OBS-001", title: "有展示证据的场次", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, live_room_plan_code: "PLAN-001", release_code: "REL-001", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", metrics: { watchers: 12 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:01:00Z" }]);
      if (url === "/api/functional-operations/exposures") return response([{ exposure_code: "EXP-001", session_code: "OPS-OBS-001", plan_code: "PLAN-001", variant_code: "VAR-001", release_code: "REL-001", scene_code: "SCENE-001", started_at: "2026-07-20T12:05:00Z", ended_at: "2026-07-20T12:10:00Z", source_kind: "recording_match", evidence_note: "recording", confidence: .9, status: "active", created_at: "2026-07-20T13:01:00Z" }]);
      if (url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    renderPage();

    expect(await screen.findByText("有展示证据的场次")).toBeInTheDocument();
    expect(screen.getByText(/已观察展示 · PLAN-001/)).toBeInTheDocument();
    expect(screen.queryByText("已交付")).not.toBeInTheDocument();
  });

  it("submits a replacement as an append-only exposure correction", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-operations/sessions") return response([{ session_code: "OPS-001", title: "晚场", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, live_room_plan_code: "PLAN-001", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", metrics: { watchers: 12 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:01:00Z" }]);
      if (url === "/api/functional-operations/exposures") return response([{ exposure_code: "EXP-001", session_code: "OPS-001", plan_code: "PLAN-001", variant_code: "VAR-001", scene_code: "SCENE-001", started_at: "2026-07-20T12:05:00Z", ended_at: "2026-07-20T12:10:00Z", source_kind: "manual_observation", evidence_note: "现场记录", confidence: .8, status: "active", created_at: "2026-07-20T13:01:00Z" }]);
      if (url === "/api/functional-live-room-plans") return response([{ plan_code: "PLAN-001", expected_title: "晚场计划", blueprint: { schema_version: "maitu.v1", scenes: [{ scene_code: "SCENE-001", shot_code: "SHOT-001", title: "商品展示", script: "", layers: [] }] }, build_plan: { schema_version: "build.v1", target_live_room_id: "ROOM-001", operations: [] }, status: "ready", execution_status: "planned", updated_at: "2026-07-20T13:00:00Z" }]);
      if (url === "/api/functional-operations/exposure-corrections" && init?.method === "POST") return response({ exposure_code: "EXP-002", session_code: "OPS-001", plan_code: "PLAN-001", variant_code: "VAR-001", scene_code: "SCENE-001", started_at: "2026-07-20T12:05:00Z", ended_at: "2026-07-20T12:10:00Z", source_kind: "manual_observation", evidence_note: "现场记录", confidence: .8, status: "active", supersedes_exposure_code: "EXP-001", correction_reason: "录屏复核后更正", created_at: "2026-07-20T13:02:00Z" });
      if (url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("EXP-001");
    await user.click(screen.getByRole("button", { name: "校正" }));
    await user.type(screen.getByLabelText("校正原因"), "录屏复核后更正");
    await user.click(screen.getByRole("button", { name: "保存更正观察" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-operations/exposure-corrections" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-operations/exposure-corrections");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({
      source_exposure_code: "EXP-001",
      correction_kind: "supersede",
      reason: "录屏复核后更正",
      replacement: { session_code: "OPS-001", plan_code: "PLAN-001", scene_code: "SCENE-001", evidence_note: "现场记录" },
    });
  });
});
