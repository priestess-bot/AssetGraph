import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
      if (url === "/api/content-projects/CONTENT-001") return response({ project_code: "CONTENT-001", title: "缺口测试内容", revision_number: 1, status: "draft", generation_goal: "测试", updated_at: "2026-07-25T00:00:00Z", content: { template_contribution_decisions: [{ template_code: "TPL-PRIMARY", revision: 3, selection_role: "primary", accepted_modules: ["opening", "close"], rejected_modules: [], available_modules: ["opening", "close"], material_cues: [] }, { template_code: "TPL-SECONDARY", revision: 2, selection_role: "secondary", accepted_modules: ["interaction"], rejected_modules: [], available_modules: ["interaction"], material_cues: [] }] } });
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

    await screen.findByText("主参考模板");
    expect(screen.getByText("TPL-PRIMARY · r3")).toBeInTheDocument();
    expect(screen.getByText("TPL-SECONDARY · r2")).toBeInTheDocument();
    await user.type(screen.getByLabelText("直播间 ID"), "room-001");
    await user.type(screen.getByLabelText("直播间标题"), "缺口计划");
    await user.click(screen.getByRole("checkbox", { name: /背景素材/ }));
    await user.click(await screen.findByRole("checkbox", { name: "AG-IMG-001 仅当前直播间位置与图层" }));
    await user.type(screen.getByLabelText("AG-IMG-001 覆盖原因"), "适配当前房间背景构图");
    await user.click(screen.getByRole("checkbox", { name: /需要审核的背景/ }));
    await user.click(screen.getByRole("button", { name: "生成场景与 BuildPlan" }));

    const request = requests.find((item) => item.url === "/api/functional-live-room-plans" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({ primary_template_code: "TPL-PRIMARY", secondary_template_codes: ["TPL-SECONDARY"], asset_gap_codes: ["AG-GAP-001"], asset_codes: ["AG-IMG-001"], room_constraint_overrides: { "AG-IMG-001": { reason: "适配当前房间背景构图", geometry: { x: 0, y: 0, width: 1, height: 1 } } } });
  });

  it("promotes a persisted room geometry through an explicit global Profile revision", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const plan = {
      plan_code: "LIVEPLAN-001", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "room-001", expected_title: "可复用背景计划", selected_asset_codes: ["AG-IMG-001"], selected_group_codes: [], selected_material_pack_codes: [], selected_asset_gap_codes: [],
      blueprint: { scenes: [] }, build_plan: { inventory_snapshot: { asset_codes: ["AG-IMG-001"], assets: [{ asset_code: "AG-IMG-001", media_kind: "image", material_roles: ["background"], execution_capability: "maitu_bound", constraint_profile_ref: { profile_code: "AG-CP-001", revision: 2, fingerprint: "a".repeat(64) }, selection_sources: [] }], material_pack_refs: [], asset_gap_refs: [], room_constraint_overrides: { "AG-IMG-001": { reason: "当前房间构图经过验证", geometry: { x: 0.05, y: 0.1, width: 0.9, height: 0.75 } } } }, operations: [] },
      gate_results: [], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects" || url === "/api/assets" || url === "/api/assets/groups" || url === "/api/assets/material-packs" || url === "/api/assets/gaps") return response([]);
      if (url === "/api/functional-live-room-plans") return response([plan]);
      if (url === "/api/functional-live-room-plans/LIVEPLAN-001") return response(plan);
      if (url === "/api/assets/AG-IMG-001/constraint-profile/promote-room-override" && init?.method === "POST") return response({ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 3, constraints: [], fingerprint_sha256: "b".repeat(64), source_plan_code: "LIVEPLAN-001", source_profile_revision: 2, created_at: "2026-07-25T00:00:00Z" });
      if (url === "/api/assets/AG-IMG-001/constraint-profile" || url === "/api/assets/AG-IMG-001/constraint-profile/revisions") return response(url.endsWith("revisions") ? [] : { profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 3, constraints: [], fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z" });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("可复用背景计划");
    await user.type(screen.getByLabelText("AG-IMG-001 提升原因"), "当前构图适用于所有同类背景素材。");
    await user.click(screen.getByLabelText("AG-IMG-001 确认提升为全局约束"));
    await user.click(screen.getByRole("button", { name: "提升为全局约束" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/assets/AG-IMG-001/constraint-profile/promote-room-override")).toBe(true));
    const request = requests.find((item) => item.url === "/api/assets/AG-IMG-001/constraint-profile/promote-room-override");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ plan_code: "LIVEPLAN-001", expected_revision: 2, actor: "functional-operator", reason: "当前构图适用于所有同类背景素材。" });
  });
});
