import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LiveRoomPlannerPage } from "./LiveRoomPlannerPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage(search?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LiveRoomPlannerPage search={search} />
    </QueryClientProvider>,
  );
}

describe("LiveRoomPlannerPage", () => {
  it("diagnoses a missing executable role and registers its traceable asset gap", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/content-projects")
          return response([{ project_code: "CONTENT-001", title: "缺口测试内容", revision_number: 4, status: "draft", generation_goal: "测试", updated_at: "2026-07-25T00:00:00Z" }]);
        if (url === "/api/content-projects/CONTENT-001")
          return response({ project_code: "CONTENT-001", title: "缺口测试内容", revision_number: 4, status: "draft", generation_goal: "测试", updated_at: "2026-07-25T00:00:00Z", content: {} });
        if (url === "/api/assets") return response([]);
        if (url === "/api/assets/groups" || url === "/api/assets/material-packs") return response([]);
        if (url === "/api/assets/gaps" && init?.method === "POST")
          return response({ gap_code: "AG-GAP-NEW", title: "缺少可执行 background 素材", role: "background", severity: "high", status: "open", gap_type: "role_coverage", specification: {}, source_context: { diagnostic_key: "a".repeat(64) }, alternative_asset_codes: ["AG-IMG-002"], resolution_snapshot: {}, resolution_evidence: {}, events: [] });
        if (url === "/api/assets/gaps") return response([]);
        if (url === "/api/functional-live-room-plans/material-gap-preview")
          return response({ project_code: "CONTENT-001", project_revision_number: 4, shot_list_revision_number: 7, checked_asset_codes: [], gaps: [{ diagnostic_key: "a".repeat(64), role: "background", title: "缺少可执行 background 素材", severity: "high", gap_type: "role_coverage", required_shot_codes: ["SHOT-001"], missing_occurrences: 1, selection_mode: "append", alternative_asset_codes: ["AG-IMG-002"], create_payload: { title: "缺少可执行 background 素材", role: "background", severity: "high", gap_type: "role_coverage", specification: { required_role: "background" }, source_context: { diagnostic_key: "a".repeat(64) }, impact_summary: "缺少背景", alternative_asset_codes: ["AG-IMG-002"] } }] });
        if (url === "/api/functional-live-room-plans") return response([]);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("素材缺口诊断");
    await user.click(screen.getByRole("button", { name: "检测素材缺口" }));
    expect(await screen.findByText("缺少可执行 background 素材")).toBeInTheDocument();
    expect(screen.getByText(/可复核候选：AG-IMG-002/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "登记为素材缺口" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.url === "/api/assets/gaps" && request.init?.method === "POST",
        ),
      ).toBe(true),
    );
    const createRequest = requests.find(
      (request) => request.url === "/api/assets/gaps" && request.init?.method === "POST",
    );
    expect(JSON.parse(String(createRequest?.init?.body))).toMatchObject({
      gap_type: "role_coverage",
      source_context: { diagnostic_key: "a".repeat(64) },
    });
  });

  it("includes an explicitly linked open asset gap when creating a live-room plan", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const plan = {
      plan_code: "LIVEPLAN-001",
      project_code: "CONTENT-001",
      variant_code: "VARIANT-001",
      configuration_code: "CONFIG-001",
      target_live_room_id: "room-001",
      expected_title: "缺口计划",
      selected_asset_codes: ["AG-IMG-001"],
      selected_group_codes: [],
      selected_material_pack_codes: [],
      selected_asset_gap_codes: ["AG-GAP-001"],
      blueprint: { scenes: [] },
      build_plan: {
        inventory_snapshot: {
          asset_codes: ["AG-IMG-001"],
          assets: [],
          material_pack_refs: [],
          asset_gap_refs: [
            {
              gap_code: "AG-GAP-001",
              title: "需要审核的背景",
              role: "background",
              severity: "high",
              status: "open",
              gap_type: "rights_pending",
              fingerprint_sha256: "a".repeat(64),
            },
          ],
        },
        operations: [],
      },
      gate_results: [],
      quality_report: {},
      status: "blocked",
      blocked_reasons: ["asset_gap_unresolved:AG-GAP-001:open"],
      execution_status: "not_requested",
      execution_evidence: {},
      clone_context: {},
      updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/content-projects")
          return response([
            {
              project_code: "CONTENT-001",
              title: "缺口测试内容",
              revision_number: 1,
              status: "draft",
              generation_goal: "测试",
              updated_at: "2026-07-25T00:00:00Z",
            },
          ]);
        if (url === "/api/content-projects/CONTENT-001")
          return response({
            project_code: "CONTENT-001",
            title: "缺口测试内容",
            revision_number: 1,
            status: "draft",
            generation_goal: "测试",
            updated_at: "2026-07-25T00:00:00Z",
            content: {
              template_contribution_decisions: [
                {
                  template_code: "TPL-PRIMARY",
                  revision: 3,
                  selection_role: "primary",
                  accepted_modules: ["opening", "close"],
                  rejected_modules: [],
                  available_modules: ["opening", "close"],
                  material_cues: [],
                },
                {
                  template_code: "TPL-SECONDARY",
                  revision: 2,
                  selection_role: "secondary",
                  accepted_modules: ["interaction"],
                  rejected_modules: [],
                  available_modules: ["interaction"],
                  material_cues: [],
                },
              ],
            },
          });
        if (url === "/api/assets")
          return response([
            {
              asset_code: "AG-IMG-001",
              title: "背景素材",
              original_filename: "background.png",
              asset_type: "IMG",
              material_roles: ["background"],
              execution_capability: "maitu_bound",
            },
          ]);
        if (
          url === "/api/assets/groups" ||
          url === "/api/assets/material-packs"
        )
          return response([]);
        if (url === "/api/assets/gaps")
          return response([
            {
              gap_code: "AG-GAP-001",
              title: "需要审核的背景",
              role: "background",
              severity: "high",
              status: "open",
              gap_type: "rights_pending",
              alternative_asset_codes: [],
              resolution_snapshot: {},
              events: [],
            },
          ]);
        if (
          url === "/api/functional-live-room-plans" &&
          init?.method === "POST"
        )
          return response(plan);
        if (url === "/api/functional-live-room-plans") return response([]);
        if (url === "/api/functional-live-room-plans/LIVEPLAN-001")
          return response(plan);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderPage(
      `?layout_reference_template_code=LAYOUT-001&layout_reference_template_revision_number=3&layout_reference_template_projection_fingerprint=${"a".repeat(64)}`,
    );

    await screen.findByText("主参考模板");
    expect(screen.getByText("TPL-PRIMARY · r3")).toBeInTheDocument();
    expect(screen.getByText("TPL-SECONDARY · r2")).toBeInTheDocument();
    expect(
      screen.getByText(/已固定 LAYOUT-001 · r3 的近似布局参考/),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("直播间 ID"), "room-001");
    await user.type(screen.getByLabelText("直播间标题"), "缺口计划");
    await user.click(screen.getByRole("checkbox", { name: /背景素材/ }));
    await user.click(screen.getByLabelText("AG-IMG-001 至少使用一次"));
    await user.click(
      await screen.findByRole("checkbox", {
        name: "AG-IMG-001 仅当前直播间位置与图层",
      }),
    );
    await user.type(
      screen.getByLabelText("AG-IMG-001 覆盖原因"),
      "适配当前房间背景构图",
    );
    await user.click(screen.getByRole("checkbox", { name: /需要审核的背景/ }));
    await user.type(
      await screen.findByLabelText("AG-GAP-001 当前计划豁免原因"),
      "本次活动使用临时审核素材",
    );
    await user.click(
      screen.getByRole("button", { name: "生成场景与 BuildPlan" }),
    );

    const request = requests.find(
      (item) =>
        item.url === "/api/functional-live-room-plans" &&
        item.init?.method === "POST",
    );
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({
      layout_reference_handoff: {
        template_code: "LAYOUT-001",
        revision: 3,
        projection_fingerprint: "a".repeat(64),
      },
      primary_template_code: "TPL-PRIMARY",
      secondary_template_codes: ["TPL-SECONDARY"],
      asset_gap_codes: ["AG-GAP-001"],
      asset_gap_waivers: { "AG-GAP-001": "本次活动使用临时审核素材" },
      asset_codes: ["AG-IMG-001"],
      required_loose_asset_codes: ["AG-IMG-001"],
      room_constraint_overrides: {
        "AG-IMG-001": {
          reason: "适配当前房间背景构图",
          geometry: { x: 0, y: 0, width: 1, height: 1 },
        },
      },
    });
  });

  it("promotes a persisted room geometry through an explicit global Profile revision", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const plan = {
      plan_code: "LIVEPLAN-001",
      project_code: "CONTENT-001",
      variant_code: "VARIANT-001",
      configuration_code: "CONFIG-001",
      target_live_room_id: "room-001",
      expected_title: "可复用背景计划",
      selected_asset_codes: ["AG-IMG-001"],
      selected_group_codes: [],
      selected_material_pack_codes: [],
      selected_asset_gap_codes: [],
      blueprint: { scenes: [] },
      build_plan: {
        inventory_snapshot: {
          asset_codes: ["AG-IMG-001"],
          assets: [
            {
              asset_code: "AG-IMG-001",
              media_kind: "image",
              material_roles: ["background"],
              execution_capability: "maitu_bound",
              constraint_profile_ref: {
                profile_code: "AG-CP-001",
                revision: 2,
                fingerprint: "a".repeat(64),
              },
              selection_sources: [],
            },
          ],
          material_pack_refs: [],
          asset_gap_refs: [],
          room_constraint_overrides: {
            "AG-IMG-001": {
              reason: "当前房间构图经过验证",
              geometry: { x: 0.05, y: 0.1, width: 0.9, height: 0.75 },
            },
          },
        },
        operations: [],
      },
      gate_results: [],
      quality_report: {},
      status: "ready",
      blocked_reasons: [],
      execution_status: "not_requested",
      execution_evidence: {},
      clone_context: {},
      updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (
          url === "/api/content-projects" ||
          url === "/api/assets" ||
          url === "/api/assets/groups" ||
          url === "/api/assets/material-packs" ||
          url === "/api/assets/gaps"
        )
          return response([]);
        if (url === "/api/functional-live-room-plans") return response([plan]);
        if (url === "/api/functional-live-room-plans/LIVEPLAN-001")
          return response(plan);
        if (
          url ===
            "/api/assets/AG-IMG-001/constraint-profile/promote-room-override" &&
          init?.method === "POST"
        )
          return response({
            profile_code: "AG-CP-001",
            asset_code: "AG-IMG-001",
            revision_number: 3,
            constraints: [],
            fingerprint_sha256: "b".repeat(64),
            source_plan_code: "LIVEPLAN-001",
            source_profile_revision: 2,
            created_at: "2026-07-25T00:00:00Z",
          });
        if (
          url === "/api/assets/AG-IMG-001/constraint-profile" ||
          url === "/api/assets/AG-IMG-001/constraint-profile/revisions"
        )
          return response(
            url.endsWith("revisions")
              ? []
              : {
                  profile_code: "AG-CP-001",
                  asset_code: "AG-IMG-001",
                  revision_number: 3,
                  constraints: [],
                  fingerprint_sha256: "b".repeat(64),
                  created_at: "2026-07-25T00:00:00Z",
                },
          );
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("可复用背景计划");
    await user.type(
      screen.getByLabelText("AG-IMG-001 提升原因"),
      "当前构图适用于所有同类背景素材。",
    );
    await user.click(screen.getByLabelText("AG-IMG-001 确认提升为全局约束"));
    await user.click(screen.getByRole("button", { name: "提升为全局约束" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url ===
            "/api/assets/AG-IMG-001/constraint-profile/promote-room-override",
        ),
      ).toBe(true),
    );
    const request = requests.find(
      (item) =>
        item.url ===
        "/api/assets/AG-IMG-001/constraint-profile/promote-room-override",
    );
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      plan_code: "LIVEPLAN-001",
      expected_revision: 2,
      actor: "functional-operator",
      reason: "当前构图适用于所有同类背景素材。",
    });
  });

  it("resolves an explicit replace mode before creating a live-room plan", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const totalPack = {
      pack_code: "AG-PACK-TOTAL",
      title: "总体背景",
      pack_kind: "total",
      revision_number: 1,
      published_revision_number: 1,
      status: "published",
      revision_status: "published",
      fingerprint_sha256: "a".repeat(64),
      entries: [],
      resolved_asset_codes: ["AG-IMG-TOTAL"],
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    };
    const categoryPack = {
      pack_code: "AG-PACK-CLASS",
      title: "分类背景",
      pack_kind: "classification",
      role: "background",
      revision_number: 1,
      published_revision_number: 1,
      status: "published",
      revision_status: "published",
      fingerprint_sha256: "b".repeat(64),
      entries: [],
      resolved_asset_codes: ["AG-IMG-CLASS"],
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (
          url === "/api/content-projects" ||
          url === "/api/assets" ||
          url === "/api/assets/groups" ||
          url === "/api/assets/gaps" ||
          url === "/api/functional-live-room-plans"
        )
          return response([]);
        if (url === "/api/assets/material-packs" && !init?.method)
          return response([totalPack, categoryPack]);
        if (
          url === "/api/assets/material-packs/resolve" &&
          init?.method === "POST"
        )
          return response({
            schema_version: "material-pack-resolution.v1",
            role_modes: JSON.parse(String(init.body)).role_modes,
            pack_refs: [],
            resolved_asset_codes: ["AG-IMG-CLASS"],
            entry_requirements: [
              {
                pack_code: "AG-PACK-CLASS",
                entry_key: "entry-1",
                mode: "required",
                material_role: "background",
                resolved_asset_codes: ["AG-IMG-CLASS"],
                min_occurrences: 1,
              },
            ],
            material_rules: [],
            conflicts: [],
            fingerprint_sha256: "c".repeat(64),
          });
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("checkbox", { name: /总体背景/ }));
    await user.click(screen.getByRole("checkbox", { name: /分类背景/ }));
    await screen.findByRole("group", { name: "background 素材包合并方式" });
    await user.click(screen.getByRole("button", { name: "替换" }));

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.url === "/api/assets/material-packs/resolve" &&
            JSON.parse(String(request.init?.body)).role_modes.background ===
              "replace",
        ),
      ).toBe(true),
    );
    expect(screen.getByRole("button", { name: "替换" })).toHaveClass("active");
  });
});
