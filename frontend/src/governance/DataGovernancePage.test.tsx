import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataGovernancePage } from "./DataGovernancePage";

const metric = {
  metric_code: "orders",
  revision_number: 1,
  status: "active",
  owner_principal: "data-owner",
  metric_status: "active",
  name: "成交订单",
  description: "退款窗口后确认的成交订单",
  grain: "live_session",
  unit: "order",
  value_type: "integer",
  aggregation: "count",
  dimensions: ["live_session_code"],
  event_contract_refs: [{ code: "commerce-orders", revision: 1 }],
  event_time_field: "event_time",
  timezone: "Asia/Shanghai",
  business_day_boundary: "04:00",
  deduplication_keys: ["order_id"],
  null_rule: { order_id: "reject" },
  outlier_rule: {},
  schema_compatibility: { minimum: "commerce-event.v1" },
  quality_slo: { completeness: 0.99 },
  fingerprint_sha256: "a".repeat(64),
  created_at: "2026-07-25T00:00:00Z",
};

const contract = {
  contract_code: "commerce-orders",
  revision_number: 1,
  status: "active",
  owner_principal: "data-owner",
  source_system: "commerce-platform",
  schema_version: "commerce-event.v1",
  json_schema: { type: "object", properties: { order_id: { type: "string" } } },
  event_id_path: "/event_id",
  event_time_path: "/event_time",
  operation_path: "/operation",
  primary_key_paths: ["/order_id"],
  upsert_delete_semantics: { allowed_operations: ["insert", "upsert"] },
  lateness_policy: { max_lateness_seconds: 3600, max_future_clock_skew_seconds: 60 },
  compatibility_window: { accepted_revisions: [1] },
  enum_mappings: {},
  field_classifications: { order_id: "confidential" },
  expected_volume: { events_per_hour: 1000 },
  quality_slo: { completeness: 0.99 },
  fingerprint_sha256: "b".repeat(64),
  created_at: "2026-07-25T00:00:00Z",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><DataGovernancePage /></QueryClientProvider>);
}

describe("DataGovernancePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = url.endsWith("/metrics") ? [metric]
        : url.endsWith("/contracts") ? [contract]
        : url.endsWith("/metrics/orders/revisions") ? [metric]
        : url.endsWith("/contracts/commerce-orders/revisions") ? [contract]
        : url.endsWith("/contracts/commerce-orders/consumers") ? [{ metric_code: "orders", revision_number: 1, status: "active", owner_principal: "data-owner", name: "成交订单", event_contract_refs: [{ code: "commerce-orders", revision: 1 }] }]
        : init?.method === "POST" && url.includes("/metrics/") ? metric
        : init?.method === "POST" && url.includes("/contracts/") ? contract
        : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
  });

  it("shows revisions, changed fields and consumers without hiding the contract boundary", async () => {
    const user = userEvent.setup();
    renderPage();

    expect((await screen.findAllByText("成交订单")).length).toBeGreaterThan(0);
    expect(screen.getByText("这是首个修订，尚无可比较版本。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "数据契约" }));
    expect(await screen.findByText("指标消费者")).toBeInTheDocument();
    expect((await screen.findAllByText("成交订单")).length).toBeGreaterThan(0);
  });

  it("creates a typed metric revision from the catalog form", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByText("成交订单");
    await user.click(screen.getByRole("button", { name: "新指标" }));
    await user.type(screen.getByLabelText("指标编码"), "clicks");
    await user.type(screen.getByLabelText("指标名称"), "点击次数");
    await user.type(screen.getByLabelText("指标含义"), "直播间点击总数");
    await user.type(screen.getByLabelText("去重键"), "click_id");
    await user.type(screen.getByLabelText("契约引用"), "commerce-orders@1");
    await user.click(screen.getByRole("button", { name: "创建指标 r1" }));

    const calls = vi.mocked(fetch).mock.calls;
    const request = calls.find(([url, init]) => String(url).endsWith("/data-governance/metrics/clicks/revisions") && init?.method === "POST");
    expect(request).toBeTruthy();
    const payload = JSON.parse(String(request?.[1]?.body));
    expect(payload.expected_revision).toBe(0);
    expect(payload.definition.deduplication_keys).toEqual(["click_id"]);
    expect(payload.definition.event_contract_refs).toEqual([{ code: "commerce-orders", revision: 1 }]);
  });
});
