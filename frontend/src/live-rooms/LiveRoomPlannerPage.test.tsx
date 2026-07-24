import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LiveRoomPlannerPage } from "./LiveRoomPlannerPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><LiveRoomPlannerPage /></QueryClientProvider>);
}

describe("LiveRoomPlannerPage", () => {
  it("includes an explicitly linked open asset gap when creating a live-room plan", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const plan = { plan_code: "LIVEPLAN-001", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "room-001", expected_title: "缺口计划", selected_asset_codes: ["AG-IMG-001"], selected_group_codes: [], selected_material_pack_codes: [], selected_asset_gap_codes: ["AG-GAP-001"], blueprint: { scenes: [] }, build_plan: { inventory_snapshot: { asset_codes: ["AG-IMG-001"], assets: [], material_pack_refs: [], asset_gap_refs: [{ gap_code: "AG-GAP-001", title: "需要审核的背景", role: "background", severity: "high", status: "open", gap_type: "rights_pending", fingerprint_sha256: "a".repeat(64) }] }, operations: [] }, gate_results: [], quality_report: {}, status: "blocked", blocked_reasons: ["asset_gap_unresolved:AG-GAP-001:open"], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-25T00:00:00Z" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return response([{ project_code: "CONTENT-001", title: "缺口测试内容", revision_number: 1, status: "draft", generation_goal: "测试", updated_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets") return response([{ asset_code: "AG-IMG-001", title: "背景素材", original_filename: "background.png", asset_type: "IMG", material_roles: ["background"], execution_capability: "maitu_bound" }]);
      if (url === "/api/assets/groups" || url === "/api/assets/material-packs") return response([]);
      if (url === "/api/assets/gaps") return response([{ gap_code: "AG-GAP-001", title: "需要审核的背景", role: "background", severity: "high", status: "open", gap_type: "rights_pending", alternative_asset_codes: [], resolution_snapshot: {}, events: [] }]);
      if (url === "/api/functional-live-room-plans" && init?.method === "POST") return response(plan);
      if (url === "/api/functional-live-room-plans") return response([]);
      if (url === "/api/functional-live-room-plans/LIVEPLAN-001") return response(plan);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("关联素材缺口");
    await user.type(screen.getByLabelText("直播间 ID"), "room-001");
    await user.type(screen.getByLabelText("直播间标题"), "缺口计划");
    await user.click(screen.getByRole("checkbox", { name: /背景素材/ }));
    await user.click(screen.getByRole("checkbox", { name: /需要审核的背景/ }));
    await user.click(screen.getByRole("button", { name: "生成场景与 BuildPlan" }));

    const request = requests.find((item) => item.url === "/api/functional-live-room-plans" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({ asset_gap_codes: ["AG-GAP-001"], asset_codes: ["AG-IMG-001"] });
  });
});
