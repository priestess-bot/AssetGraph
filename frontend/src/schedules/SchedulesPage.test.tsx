import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SchedulesPage } from "./SchedulesPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("SchedulesPage", () => {
  it("creates a local UTC schedule draft against a fixed release", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/releases") return response([{
        release_code: "RELEASE-001", subject_code: "CONTENT-001", status: "approved", subject_type: "content_project", subject_revision: 1, carrier_kind: "live_room_draft", manifest_code: "MANIFEST-001", manifest_fingerprint: "a".repeat(64), delivery_count: 0,
      }]);
      if (url === "/api/broadcast-schedules") {
        if (init?.method === "POST") return response({
          schedule_code: "SCHEDULE-001", revision_number: 1, title: "Evening session", release_code: "RELEASE-001", release_fingerprint_sha256: null,
          target_account_id: "account-1", target_room_id: "room-1", platform: "douyin", timezone: "Asia/Shanghai", starts_at: "2026-07-26T10:00:00Z", ends_at: "2026-07-26T11:00:00Z", owner: "functional-operator",
          promotion_dependencies: [], inventory_dependencies: [], conflict_strategy: "manual_reschedule", stop_conditions: ["inventory unavailable"], status: "draft", validation_result: { state: "not_validated", go_live_capability: "disabled" }, fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z",
        });
        return response([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><SchedulesPage /></QueryClientProvider>);

    await screen.findByRole("heading", { name: "排播计划" });
    await user.type(screen.getByLabelText("计划名称"), "Evening session");
    await user.selectOptions(screen.getByLabelText("固定 Release"), "RELEASE-001");
    await user.type(screen.getByLabelText("目标账号"), "account-1");
    await user.type(screen.getByLabelText("目标直播间"), "room-1");
    fireEvent.change(screen.getByLabelText("开始窗口（UTC）"), { target: { value: "2026-07-26T10:00" } });
    fireEvent.change(screen.getByLabelText("结束窗口（UTC）"), { target: { value: "2026-07-26T11:00" } });
    await user.type(screen.getByLabelText("停止条件"), "inventory unavailable");
    await user.click(screen.getByRole("button", { name: "创建排播草稿" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/broadcast-schedules" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/broadcast-schedules" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({
      title: "Evening session", release_code: "RELEASE-001", target_account_id: "account-1", target_room_id: "room-1",
      starts_at: "2026-07-26T10:00:00Z", ends_at: "2026-07-26T11:00:00Z", stop_conditions: ["inventory unavailable"],
    });
  });
});
