import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OperationsPage } from "./OperationsPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const metricCatalog = [
  {
    metric_code: "orders",
    revision_number: 2,
    status: "active",
    owner_principal: "data-owner",
    metric_status: "active",
    name: "Completed orders",
    description: "Orders after the refund window",
    grain: "live_session",
    unit: "order",
    value_type: "integer",
    aggregation: "count",
    dimensions: [],
    event_contract_refs: [],
    deduplication_keys: ["order_id"],
    null_rule: {},
    outlier_rule: {},
    schema_compatibility: {},
    quality_slo: {},
    fingerprint_sha256: "a".repeat(64),
  },
];

function renderPage(view: "sessions" | "attribution" = "sessions") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><OperationsPage view={view} /></QueryClientProvider>);
}

describe("OperationsPage", () => {
  it("records the operator-entered session interval and distinguishes observed evidence", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-operations/sessions" && init?.method === "POST") return response({ session_code: "OPS-001", title: "晚场", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:30:00Z", metrics: { watchers: 12 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:31:00Z" });
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions") return response([]);
      if (url === "/api/functional-operations/exposures" || url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      if (url === "/api/functional-operations/sessions/OPS-001/content-timeline") return response({ session_code: "OPS-001", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:30:00Z", total_seconds: 5400, observed_seconds: 0, coverage_ratio: 0, unobserved_seconds: 5400, status: "resolved", missing_plan_codes: [], spans: [] });
      if (url === "/api/functional-operations/sessions/OPS-001/time-mappings" && init?.method === "POST") return response({ mapping_code: "TIME-MAP-001", session_code: "OPS-001", revision_number: 1, status: "active", source_clock: "recording_elapsed_ms", source_kind: "manual_calibration", source_offset_ms: 0, drift_ppm: 0, coverage_start_ms: 0, coverage_end_ms: 5400000, evidence_note: "开场锚点", actor: "functional-operator", created_at: "2026-07-20T13:31:00Z" });
      if (url === "/api/functional-operations/sessions/OPS-001/time-mappings") return response([]);
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

    await screen.findByText("尚未校准来源时钟");
    await user.type(screen.getByLabelText("校准证据"), "开场锚点");
    await user.click(screen.getByRole("button", { name: "保存时间对齐" }));
    await waitFor(() => expect(requests.some((item) => item.url === "/api/functional-operations/sessions/OPS-001/time-mappings" && item.init?.method === "POST")).toBe(true));
    const mappingRequest = requests.find((item) => item.url === "/api/functional-operations/sessions/OPS-001/time-mappings" && item.init?.method === "POST");
    expect(JSON.parse(String(mappingRequest?.init?.body))).toMatchObject({
      expected_revision: 0,
      source_clock: "recording_elapsed_ms",
      coverage_start_ms: 0,
      coverage_end_ms: 5400000,
      evidence_note: "开场锚点",
    });
  });

  it("pins a selected metric catalog revision with the submitted session value", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/functional-operations/sessions" && init?.method === "POST") return response({ session_code: "OPS-002", title: "目录指标场次", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", metrics: { orders: 4 }, metric_definition_refs: [{ metric_key: "orders", metric_code: "orders", revision_number: 2, name: "Completed orders", unit: "order" }], source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:01:00Z" });
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions") return response([]);
      if (url === "/api/functional-operations/exposures" || url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      if (url === "/api/functional-operations/sessions/OPS-002/content-timeline") return response({ session_code: "OPS-002", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", total_seconds: 3600, observed_seconds: 0, coverage_ratio: 0, unobserved_seconds: 3600, status: "resolved", missing_plan_codes: [], spans: [] });
      if (url === "/api/functional-operations/sessions/OPS-002/time-mappings") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "运营场次与实际展示" });
    await user.type(screen.getByLabelText("场次名称"), "目录指标场次");
    await screen.findByRole("option", { name: /Completed orders/ });
    await user.selectOptions(screen.getByLabelText("指标目录 1"), "orders:2");
    fireEvent.change(screen.getByLabelText("指标数值 1"), { target: { value: "4" } });
    await user.click(screen.getByRole("button", { name: "登记场次" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-operations/sessions" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-operations/sessions" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({
      metrics: { orders: 4 },
      metric_definition_refs: [
        { metric_key: "orders", metric_code: "orders", revision_number: 2 },
      ],
    });
  });

  it("creates a frozen metric snapshot for a selected operation session", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions") return response([
        { session_code: "OPS-001", title: "有事件的场次", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", metrics: {}, source_kind: "adapter_import", import_version: 1, created_at: "2026-07-20T13:01:00Z" },
      ]);
      if (url === "/api/functional-operations/sessions/OPS-001/metric-snapshots" && init?.method === "POST") return response({ snapshot_code: "METRIC-SNAP-001", session_code: "OPS-001", metric_key: "orders", metric_code: "orders", metric_revision: 2, aggregation: "count", status: "ready", value: 2, source_event_count: 2, source_batches: [], quality_summary: {}, input_snapshot: {}, fingerprint_sha256: "a".repeat(64), created_at: "2026-07-20T13:02:00Z" });
      if (url === "/api/functional-operations/sessions/OPS-001/metric-snapshots") return response([]);
      if (url === "/api/functional-operations/exposures" || url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("有事件的场次");
    await user.click(screen.getByRole("button", { name: "指标快照" }));
    expect(await screen.findByText(/会话指标快照 · OPS-001/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "生成冻结快照" }));

    await waitFor(() => expect(requests.some((item) => item.url === "/api/functional-operations/sessions/OPS-001/metric-snapshots" && item.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-operations/sessions/OPS-001/metric-snapshots" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      metric_key: "orders",
      metric_code: "orders",
      revision_number: 2,
    });
  });

  it("creates descriptive attribution from an explicit session selection", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions") return response([
        { session_code: "OPS-001", title: "早场", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", metrics: { watchers: 12 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:01:00Z" },
        { session_code: "OPS-002", title: "晚场", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, started_at: "2026-07-20T14:00:00Z", ended_at: "2026-07-20T15:00:00Z", metrics: { watchers: 24 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T15:01:00Z" },
      ]);
      if (url === "/api/functional-operations/attribution-reports" && init?.method === "POST") return response({ report_code: "ATTR-001", metric_key: "watchers", evidence_level: "descriptive", session_codes: ["OPS-001"], results: { groups: {}, metadata: { method: "session_metric_grouped_by_source_backed_exposure", metric_grain: "operation_session", selected_session_count: 1, observed_session_count: 0, session_only_count: 1, source_kind_counts: {}, release_bound_exposure_count: 0, metric_definition_state: "metric_unpinned" } }, created_at: "2026-07-20T15:02:00Z" });
      if (url === "/api/functional-operations/exposures" || url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage("attribution");

    await screen.findByRole("heading", { name: "归因与排播" });
    await screen.findByLabelText("归因场次 OPS-002");
    await user.click(screen.getByLabelText("归因场次 OPS-002"));
    await user.click(screen.getByRole("button", { name: "生成描述性归因" }));

    await waitFor(() => expect(requests.some((item) => item.url === "/api/functional-operations/attribution-reports" && item.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-operations/attribution-reports" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      metric_key: "watchers",
      session_codes: ["OPS-001"],
    });
  });

  it("renders scene estimates as duration-proportional descriptive allocations", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions" || url === "/api/functional-operations/exposures" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      if (url === "/api/functional-operations/attribution-reports") return response([{
        report_code: "ATTR-ALLOC-001", metric_key: "watchers", evidence_level: "descriptive", session_codes: ["OPS-001"],
        results: {
          groups: {},
          scene_allocations: [{
            scope_type: "observed_scene_duration_allocation", plan_code: "PLAN-001", scene_code: "SCENE-001",
            estimated_metric_value: 6, observed_duration_seconds: 30, source_session_codes: ["OPS-001"], source_session_count: 1,
            source_kind_counts: { recording_match: 1 }, release_codes: ["REL-001"], average_confidence: .9,
            allocation_basis: "active_observed_exposure_duration_within_each_session", limitations: ["descriptive only"],
          }],
          measured_scene_allocations: [{
            scope_type: "measured_event_time_bucket", plan_code: "PLAN-001", scene_code: "SCENE-001", aggregation: "sum",
            measured_metric_value: 4, event_count: 2, source_session_codes: ["OPS-001"], source_snapshot_codes: ["METRIC-SNAP-001"],
            source_bucket_codes: ["METRIC-BUCKET-001", "METRIC-BUCKET-002"], release_codes: ["REL-001"],
            allocation_basis: "event_time_within_active_content_exposure", limitations: ["descriptive only"],
          }],
          measured_scene_allocation_summary: { candidate_bucket_count: 2, allocated_bucket_count: 2, unallocated_bucket_count: 0, session_only_bucket_count: 0 },
          metadata: { method: "session_metric_grouped_by_source_backed_exposure", metric_grain: "operation_session", selected_session_count: 1, observed_session_count: 1, session_only_count: 0, source_kind_counts: { recording_match: 1 }, release_bound_exposure_count: 1, metric_definition_state: "metric_unpinned", scene_allocation_method: "proportional_by_active_observed_exposure_duration", scene_allocation_count: 1 },
        },
        created_at: "2026-07-20T15:02:00Z",
      }]);
      throw new Error(`Unexpected request: ${url}`);
    }));

    renderPage("attribution");

    expect(await screen.findByText("场景级估算（观察时长比例）")).toBeInTheDocument();
    expect(screen.getByText("场景级实测值（事件时刻）")).toBeInTheDocument();
    expect(screen.getAllByText("SCENE-001")).toHaveLength(2);
    expect(screen.getByText("6.00")).toBeInTheDocument();
    expect(screen.getByText(/不代表场景真实归因或因果效果/)).toBeInTheDocument();
  });

  it("compares frozen reports with the same metric at group and measured-scene level", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions" || url === "/api/functional-operations/exposures" || url === "/api/functional-operations/schedule-plans" || url === "/api/functional-live-room-plans") return response([]);
      if (url === "/api/functional-operations/attribution-reports") return response([
        {
          report_code: "ATTR-CANDIDATE", metric_key: "orders", evidence_level: "descriptive", session_codes: ["OPS-002"], status: "review_required", fingerprint_sha256: "b".repeat(64),
          results: {
            groups: { "plan:PLAN-001": { scope_type: "live_room_plan", scope_code: "PLAN-001", display_label: "实际展示计划 PLAN-001", average: 12, sample_size: 2, session_codes: ["OPS-002"], source_evidence: { exposure_count: 2, release_bound_exposure_count: 2, coverage_seconds: 60, source_kind_counts: { recording_match: 2 }, scene_codes: ["SCENE-001"], release_codes: ["REL-001"] }, limitations: [] } },
            measured_scene_allocations: [{ scope_type: "measured_event_time_bucket", plan_code: "PLAN-001", scene_code: "SCENE-001", aggregation: "sum", measured_metric_value: 7, event_count: 2, source_session_codes: ["OPS-002"], source_snapshot_codes: ["METRIC-SNAP-002"], source_bucket_codes: ["METRIC-BUCKET-002"], release_codes: ["REL-001"], allocation_basis: "event_time_within_active_content_exposure", limitations: [] }],
            metadata: { method: "descriptive", metric_grain: "live_session", selected_session_count: 2, observed_session_count: 2, session_only_count: 0, source_kind_counts: { recording_match: 2 }, release_bound_exposure_count: 2, metric_definition_state: "resolved", scene_allocation_method: "event_time", scene_allocation_count: 1 },
          }, created_at: "2026-07-25T12:10:00Z",
        },
        {
          report_code: "ATTR-BASELINE", metric_key: "orders", evidence_level: "descriptive", session_codes: ["OPS-001"], status: "published_descriptive", fingerprint_sha256: "a".repeat(64),
          results: {
            groups: { "plan:PLAN-001": { scope_type: "live_room_plan", scope_code: "PLAN-001", display_label: "实际展示计划 PLAN-001", average: 8, sample_size: 2, session_codes: ["OPS-001"], source_evidence: { exposure_count: 2, release_bound_exposure_count: 2, coverage_seconds: 60, source_kind_counts: { recording_match: 2 }, scene_codes: ["SCENE-001"], release_codes: ["REL-001"] }, limitations: [] } },
            measured_scene_allocations: [{ scope_type: "measured_event_time_bucket", plan_code: "PLAN-001", scene_code: "SCENE-001", aggregation: "sum", measured_metric_value: 5, event_count: 2, source_session_codes: ["OPS-001"], source_snapshot_codes: ["METRIC-SNAP-001"], source_bucket_codes: ["METRIC-BUCKET-001"], release_codes: ["REL-001"], allocation_basis: "event_time_within_active_content_exposure", limitations: [] }],
            metadata: { method: "descriptive", metric_grain: "live_session", selected_session_count: 2, observed_session_count: 2, session_only_count: 0, source_kind_counts: { recording_match: 2 }, release_bound_exposure_count: 2, metric_definition_state: "resolved", scene_allocation_method: "event_time", scene_allocation_count: 1 },
          }, created_at: "2026-07-25T12:00:00Z",
        },
      ]);
      throw new Error(`Unexpected request: ${url}`);
    }));

    renderPage("attribution");

    expect(await screen.findByRole("heading", { name: "描述性报告比较" })).toBeInTheDocument();
    expect(screen.getByText("同一指标")).toBeInTheDocument();
    expect(screen.getByText("场景 SCENE-001 · PLAN-001")).toBeInTheDocument();
    expect(screen.getAllByText("+2.00")).toHaveLength(1);
    expect(screen.getAllByText("+4.00")).toHaveLength(1);
  });

  it("labels a session as observed only when it has an active exposure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
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
      if (url === "/api/data-governance/metrics") return response(metricCatalog);
      if (url === "/api/functional-operations/sessions") return response([{ session_code: "OPS-001", title: "晚场", platform: "douyin", source_timezone: "Asia/Shanghai", source_evidence: {}, live_room_plan_code: "PLAN-001", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", metrics: { watchers: 12 }, source_kind: "manual_import", import_version: 1, created_at: "2026-07-20T13:01:00Z" }]);
      if (url === "/api/functional-operations/exposures") return response([{ exposure_code: "EXP-001", session_code: "OPS-001", plan_code: "PLAN-001", variant_code: "VAR-001", scene_code: "SCENE-001", started_at: "2026-07-20T12:05:00Z", ended_at: "2026-07-20T12:10:00Z", source_kind: "manual_observation", evidence_note: "现场记录", confidence: .8, status: "active", created_at: "2026-07-20T13:01:00Z" }]);
      if (url === "/api/functional-live-room-plans") return response([{ plan_code: "PLAN-001", expected_title: "晚场计划", blueprint: { schema_version: "maitu.v1", scenes: [{ scene_code: "SCENE-001", shot_code: "SHOT-001", title: "商品展示", script: "", layers: [] }] }, build_plan: { schema_version: "build.v1", target_live_room_id: "ROOM-001", operations: [] }, status: "ready", execution_status: "planned", updated_at: "2026-07-20T13:00:00Z" }]);
      if (url === "/api/functional-operations/exposure-corrections" && init?.method === "POST") return response({ exposure_code: "EXP-002", session_code: "OPS-001", plan_code: "PLAN-001", variant_code: "VAR-001", scene_code: "SCENE-001", started_at: "2026-07-20T12:05:00Z", ended_at: "2026-07-20T12:10:00Z", source_kind: "manual_observation", evidence_note: "现场记录", confidence: .8, status: "active", supersedes_exposure_code: "EXP-001", correction_reason: "录屏复核后更正", created_at: "2026-07-20T13:02:00Z" });
      if (url === "/api/functional-operations/attribution-reports" || url === "/api/functional-operations/schedule-plans") return response([]);
      if (url === "/api/functional-operations/sessions/OPS-001/content-timeline") return response({ session_code: "OPS-001", started_at: "2026-07-20T12:00:00Z", ended_at: "2026-07-20T13:00:00Z", total_seconds: 3600, observed_seconds: 300, coverage_ratio: 1 / 12, unobserved_seconds: 3300, status: "resolved", missing_plan_codes: [], spans: [] });
      if (url === "/api/functional-operations/sessions/OPS-001/time-mappings") return response([]);
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
