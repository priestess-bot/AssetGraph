import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
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

const batch = {
  batch_code: "DQB-20260725-000001",
  contract_code: "commerce-orders",
  contract_revision: 1,
  source_batch_id: "export-001",
  source_checksum: "c".repeat(64),
  status: "accepted",
  row_count: 1,
  accepted_count: 1,
  quarantined_count: 0,
  rejected_count: 0,
  quality_summary: {},
  source_watermark: "2026-07-25T00:00:00Z",
  validated_at: "2026-07-25T00:00:00Z",
  created_at: "2026-07-25T00:00:00Z",
  replayed: false,
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
        : init?.method === "POST" && url.endsWith("/batches") ? batch
        : url.endsWith("/batches") ? []
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

  it("imports a source-identified event batch through the selected contract", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByText("成交订单");
    await user.click(screen.getByRole("button", { name: "数据契约" }));
    await user.click(screen.getByRole("button", { name: "导入事件" }));
    await user.type(screen.getByLabelText("来源批次 ID"), "export-20260725-001");
    fireEvent.change(screen.getByLabelText("事件行 JSON"), {
      target: {
        value: JSON.stringify([{
          entity_type: "live_session",
          entity_id: "OPS-001",
          envelope: {
            event_id: "4b6d5675-7a11-4628-82e0-8b7c60d934c5",
            source_system: "commerce-platform",
            source_event_id: "order-001",
            schema_version: "commerce-event.v1",
            operation: "upsert",
            event_time: "2026-07-25T00:00:00Z",
            processing_time: "2026-07-25T00:01:00Z",
            payload: { order_id: "order-001" },
          },
        }]),
      },
    });
    await user.click(screen.getByRole("button", { name: "导入批次" }));

    const calls = vi.mocked(fetch).mock.calls;
    const request = calls.find(([url, init]) => String(url).endsWith("/data-governance/batches") && init?.method === "POST");
    expect(request).toBeTruthy();
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      contract_code: "commerce-orders",
      contract_revision: 1,
      source_batch_id: "export-20260725-001",
    });
  });
});
