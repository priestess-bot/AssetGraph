import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LiveRoomEditorProductPage } from "./LiveRoomEditorProductPage";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPage(search = "") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><LiveRoomEditorProductPage search={search} /></QueryClientProvider>);
}

const projectBase = {
  project_code: "CONTENT-UI-001",
  title: "介绍张裕品酒大师PRO - 直播间方案 - 202607311200",
  revision_number: 1,
  generation_goal: "介绍张裕品酒大师PRO并讲清三段品鉴内容",
  updated_at: "2026-07-31T03:00:00Z",
  content: {
    target_live_room_id: "41172",
    theme: "介绍张裕品酒大师PRO",
    story: "从一次朋友聚会开始",
    detailed_design: "开场、品鉴、总结互动三段",
    selected_asset_codes: ["AG-BG-001"],
    selected_group_codes: [],
    secondary_template_codes: [],
  },
};

function projectDetail(status: string, extra: Record<string, unknown> = {}) {
  return { ...projectBase, status, generated: false, ...extra };
}

function generatedProject() {
  const segments = [0, 1, 2].map((index) => ({
    segment_code: `SEG-${index + 1}`,
    semantic_goal: ["开场引入", "品鉴介绍", "总结互动"][index],
    program_phase: index === 0 ? "opening" : index === 2 ? "conversion" : "body",
    product_refs: [], interaction_actions: [], cta_actions: [], branch_applicability: [], metadata: {},
    script_block_codes: [`BLOCK-${index + 1}`],
  }));
  const shots = segments.map((segment, index) => ({
    shot_code: `SHOT-${index + 1}`,
    shot_goal: segment.semantic_goal,
    program_segment_code: segment.segment_code,
    composition_intent: {},
    material_role_requirements: ["background"],
    audio_actions: [], continuity: {}, acceptance_criteria: [], branch_applicability: [], must_include: [], must_avoid: [],
    script_block_codes: [`BLOCK-${index + 1}`],
  }));
  return projectDetail("confirmed", {
    generated: true,
    design_brief: { design_brief_code: "BRIEF-1", revision_number: 1, status: "confirmed", raw_input: "三段内容", parsed_brief: {}, user_overrides: {}, open_questions: [] },
    program: { program_revision_code: "PROGRAM-1", revision_number: 1, segments },
    shot_list: { shot_list_revision_code: "SHOTS-1", revision_number: 1, shots },
  });
}

function livePlan() {
  return {
    plan_code: "LIVEPLAN-UI-001",
    project_code: "CONTENT-UI-001",
    variant_code: "VARIANT-1",
    configuration_code: "CONFIG-1",
    target_live_room_id: "41172",
    expected_title: "asser测试",
    selected_asset_codes: ["AG-BG-001"],
    selected_group_codes: [],
    selected_material_pack_codes: [],
    blueprint: {
      schema_version: "maitu-scene-blueprint.functional.v2",
      scenes: [0, 1, 2].map((index) => ({
        scene_code: `SCENE-${index + 1}`,
        shot_code: `SHOT-${index + 1}`,
        title: ["开场引入", "品鉴介绍", "总结互动"][index],
        script: `第 ${index + 1} 段话术`,
        layers: [{ material_role: "background", asset_code: "AG-BG-001", asset_binding_ref: { execution_capability: "maitu_bound" }, normalized_geometry: { x: 0, y: 0, width: 1, height: 1 }, z_order: 1 }],
      })),
    },
    build_plan: { inventory_snapshot: {}, target_live_room_id: "41172", go_live: false, operations: [] },
    gate_results: [], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-31T03:00:00Z",
  };
}

function successfulInspection() {
  return {
    inspection_code: "ROOMCHECK-SUCCESS",
    target_live_room_id: "41172",
    expected_title: "asser测试",
    authority_mode: "worker_readback",
    status: "succeeded",
    attempt: 1,
    room_fingerprint: "b".repeat(64),
    result: {
      target_live_room_id: "41172",
      actual_title: "asser测试",
      is_live: false,
      has_live_trace: false,
      read_environment: "working",
      scene_count: 3,
      scenes: [0, 1, 2].map((index) => ({
        scene_id: `OLD-SCENE-${index + 1}`,
        order_number: index + 1,
        name: `旧场景 ${index + 1}`,
        material_count: 2,
      })),
      ready_for_go_live: false,
      go_live_clicked: false,
    },
  };
}

describe("unified live-room generation entry", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/console/production/live-rooms");
    vi.restoreAllMocks();
  });

  it("creates the content chain and three-scene plan only through the page", async () => {
    const requests: Array<{ url: string; method: string; body?: Record<string, unknown>; headers?: HeadersInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      requests.push({ url, method, body, headers: init?.headers });
      if (url === "/api/functional-live-room-plans" && method === "GET") return json([]);
      if (url.endsWith("/maitu-capabilities")) return json({ schema_version: "maitu-capability-matrix.v1", adapter_contract: "local", contract_fingerprint: "a".repeat(64), source: "test", can_execute_draft: true, manual_handoff_available: true, unverified_required_capabilities: [], capabilities: [] });
      if (url === "/api/live-research/room-templates") return json([]);
      if (url === "/api/assets/groups") return json([]);
      if (url === "/api/assets?limit=500") return json([{ asset_code: "AG-BG-001", title: "背景素材", original_filename: "background.png", asset_type: "IMG", media_kind: "image", material_roles: ["background"], execution_capability: "maitu_bound", status: "stored", rights_status: "approved", classification_review_status: "confirmed", classification_evidence: {} }]);
      if (url === "/api/functional-live-room-plans/room-inspections" && method === "POST") return json({ inspection_code: "ROOMCHECK-FAILED", target_live_room_id: "41172", expected_title: "asser测试", authority_mode: "worker_readback", status: "failed", attempt: 1, error_message: "worker browser unavailable" }, 201);
      if (url.endsWith("/room-inspections/ROOMCHECK-FAILED")) return json({ inspection_code: "ROOMCHECK-FAILED", target_live_room_id: "41172", expected_title: "asser测试", authority_mode: "worker_readback", status: "failed", attempt: 1, error_message: "worker browser unavailable" });
      if (url === "/api/content-projects" && method === "POST") return json({ ...projectBase, title: body?.title, status: "draft" }, 201);
      if (url === "/api/content-projects/CONTENT-UI-001" && method === "GET") return json(projectDetail("draft"));
      if (url.endsWith("/CONTENT-UI-001/confirm")) return json(projectDetail("confirmed"));
      if (url.endsWith("/CONTENT-UI-001/parse-brief")) return json(projectDetail("confirmed", { design_brief: { design_brief_code: "BRIEF-1", revision_number: 1, status: "draft", raw_input: "三段内容", parsed_brief: {}, user_overrides: {}, open_questions: [{ field: "audience", question: "核心受众是谁？", recommended_answer: "葡萄酒入门用户", blocking: true }] } }));
      if (url.endsWith("/CONTENT-UI-001/design-brief") && method === "PATCH") return json(projectDetail("confirmed", { design_brief: { design_brief_code: "BRIEF-1", revision_number: 2, status: "draft", raw_input: "三段内容", parsed_brief: { audience: body?.overrides && (body.overrides as Record<string, unknown>).audience }, user_overrides: body?.overrides, open_questions: [] } }));
      if (url.endsWith("/CONTENT-UI-001/design-brief/confirm")) return json(projectDetail("confirmed", { design_brief: { design_brief_code: "BRIEF-1", revision_number: 1, status: "confirmed", raw_input: "三段内容", parsed_brief: {}, user_overrides: {}, open_questions: [] } }));
      if (url.endsWith("/CONTENT-UI-001/generate")) return json(generatedProject());
      if (url === "/api/functional-live-room-plans" && method === "POST") return json(livePlan(), 201);
      return json([]);
    }));

    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("直播间 ID"), "41172");
    await user.type(screen.getByLabelText("麦兔当前标题"), "asser测试");
    await user.type(screen.getByLabelText("生成目标"), "介绍张裕品酒大师PRO并讲清三段品鉴内容");
    await user.type(screen.getByLabelText("主题"), "介绍张裕品酒大师PRO");
    await user.click(screen.getByRole("button", { name: "读取房间" }));
    expect(await screen.findByText("本地执行器暂时无法读取麦兔页面。")).toBeInTheDocument();
    await user.click(await screen.findByText("背景素材"));
    await user.click(screen.getByRole("button", { name: "生成直播间方案" }));
    const audience = await screen.findByLabelText("核心受众是谁？");
    expect(audience).toHaveValue("葡萄酒入门用户");
    await user.clear(audience);
    await user.type(audience, "刚开始学习葡萄酒品鉴的用户");
    await user.click(screen.getByRole("button", { name: "采用补充并继续" }));

    expect((await screen.findAllByText("第 1 段话术")).length).toBeGreaterThan(0);
    expect(screen.getByText("直播间 41172")).toBeInTheDocument();
    const projectCreate = requests.find((request) => request.url === "/api/content-projects" && request.method === "POST");
    expect(projectCreate?.body?.title).toContain("介绍张裕品酒大师PRO - 直播间方案");
    expect(projectCreate?.body?.title).not.toBe("asser测试");
    expect(new Headers(projectCreate?.headers).get("Idempotency-Key")).toBeTruthy();
    const planCreate = requests.find((request) => request.url === "/api/functional-live-room-plans" && request.method === "POST");
    expect(planCreate?.body).toMatchObject({ expected_title: "asser测试", required_loose_asset_codes: ["AG-BG-001"], material_role_overrides: { background: "AG-BG-001" } });
    expect(planCreate?.body?.idempotency_key).toEqual(expect.any(String));
    const briefRevision = requests.find((request) => request.url.endsWith("/CONTENT-UI-001/design-brief") && request.method === "PATCH");
    expect(briefRevision?.body?.overrides).toEqual({ audience: "刚开始学习葡萄酒品鉴的用户" });
    expect(window.location.search).toContain("project=CONTENT-UI-001");
    expect(window.location.search).toContain("run=LIVEPLAN-UI-001");

    await user.click(screen.getByRole("button", { name: /背景素材.*固定底层/ }));
    expect(screen.queryByRole("button", { name: /添加图层/ })).not.toBeInTheDocument();
    expect(screen.queryByTitle("删除场景")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "画面用途" })).not.toBeInTheDocument();
    expect(screen.getByText("用途来自剧本与素材约束，不能在场景中绕过。")).toBeInTheDocument();
    expect(screen.getAllByRole("slider")[0]).toHaveAttribute("max", "0");
  });

  it("saves dirty scene edits before queueing and refreshes to the executed plan", async () => {
    const requests: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    const revised = {
      ...livePlan(),
      plan_code: "LIVEPLAN-UI-002",
      blueprint: {
        ...livePlan().blueprint,
        scenes: livePlan().blueprint.scenes.map((scene, index) => ({
          ...scene,
          title: index === 0 ? "修改后的开场" : scene.title,
        })),
      },
    };
    const executed = {
      ...revised,
      execution_status: "requested",
      execution_job_code: "MT-WB-EXEC-001",
      room_inspection_code: "ROOMCHECK-SUCCESS",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      requests.push({ url, method, body });
      if (url === "/api/functional-live-room-plans" && method === "GET") return json([livePlan()]);
      if (url.endsWith("/maitu-capabilities")) return json({ schema_version: "maitu-capability-matrix.v1", adapter_contract: "local", contract_fingerprint: "a".repeat(64), source: "test", can_execute_draft: true, manual_handoff_available: true, unverified_required_capabilities: [], capabilities: [] });
      if (url === "/api/assets?limit=500") return json([{ asset_code: "AG-BG-001", title: "背景素材", original_filename: "background.png", asset_type: "IMG", media_kind: "image", material_roles: ["background"], execution_capability: "maitu_bound", status: "stored", rights_status: "approved", classification_review_status: "confirmed", classification_evidence: {} }]);
      if (url === "/api/functional-live-room-plans/LIVEPLAN-UI-001" && method === "GET") return json(livePlan());
      if (url === "/api/functional-live-room-plans/LIVEPLAN-UI-002" && method === "GET") return json(executed);
      if (url === "/api/functional-live-room-plans/room-inspections" && method === "POST") return json(successfulInspection(), 202);
      if (url.endsWith("/room-inspections/ROOMCHECK-SUCCESS")) return json(successfulInspection());
      if (url.endsWith("/LIVEPLAN-UI-001/blueprint-revisions") && method === "POST") return json(revised, 201);
      if (url.endsWith("/LIVEPLAN-UI-002/confirm-execution") && method === "POST") return json(executed);
      if (url.endsWith("/LIVEPLAN-UI-002/execution")) return json({ execution_job_code: "MT-WB-EXEC-001", plan_code: "LIVEPLAN-UI-002", source_kind: "functional_live_room_plan", status: "succeeded", stage: "verified", progress_current: 5, progress_total: 5, stage_events: [], result: { ready_for_go_live: false }, retryable: false });
      return json([]);
    }));

    const user = userEvent.setup();
    const firstRender = renderPage("?run=LIVEPLAN-UI-001");
    const title = await screen.findByLabelText("场景名称");
    await user.clear(title);
    await user.type(title, "修改后的开场");
    expect(screen.getByText("有未保存的画面修改，写入时会先保存并重新编译")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "写入草稿" }).at(-1)!);
    await user.click(screen.getByRole("button", { name: "读取房间" }));
    expect((await screen.findAllByText("旧场景 1")).length).toBeGreaterThan(0);
    await user.click(firstRender.container.querySelector(".live-test-use-ack input")!);
    await user.click(screen.getByRole("button", { name: "保存修改并写入麦兔测试草稿" }));
    await screen.findByText("仅完成离线测试草稿");

    const revisionIndex = requests.findIndex((request) => request.url.endsWith("/LIVEPLAN-UI-001/blueprint-revisions"));
    const executionIndex = requests.findIndex((request) => request.url.endsWith("/LIVEPLAN-UI-002/confirm-execution"));
    expect(revisionIndex).toBeGreaterThan(-1);
    expect(executionIndex).toBeGreaterThan(revisionIndex);
    expect(requests[revisionIndex].body?.idempotency_key).toEqual(expect.any(String));
    expect(window.location.search).toContain("run=LIVEPLAN-UI-002");

    firstRender.unmount();
    renderPage(window.location.search);
    expect(await screen.findByDisplayValue("修改后的开场")).toBeInTheDocument();
    expect(requests.some((request) => request.url === "/api/functional-live-room-plans/LIVEPLAN-UI-002" && request.method === "GET")).toBe(true);
  });

  it("closes a reconciled job and creates a new job only after a fresh room inspection", async () => {
    const requests: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    let reconciliationClosed = false;
    let replacementQueued = false;
    const oldPlan = {
      ...livePlan(),
      execution_status: "maitu_reconcile_required",
      execution_job_code: "MT-WB-EXEC-OLD",
      room_inspection_code: "ROOMCHECK-OLD",
      execution_evidence: { status: "reconcile_required", execution_job_code: "MT-WB-EXEC-OLD" },
    };
    const closedPlan = {
      ...oldPlan,
      execution_status: "not_requested",
      execution_evidence: {
        status: "reconciled_reinspection_required",
        execution_job_code: "MT-WB-EXEC-OLD",
        closed_job_status: "cancelled",
      },
    };
    const replacementPlan = {
      ...closedPlan,
      execution_status: "requested",
      execution_job_code: "MT-WB-EXEC-NEW",
      room_inspection_code: "ROOMCHECK-FRESH",
      execution_evidence: {
        status: "queued",
        execution_job_code: "MT-WB-EXEC-NEW",
        execution_history: [{ execution_job_code: "MT-WB-EXEC-OLD", status: "cancelled" }],
      },
    };
    const oldInspection = { ...successfulInspection(), inspection_code: "ROOMCHECK-OLD", room_fingerprint: "a".repeat(64) };
    const freshInspection = { ...successfulInspection(), inspection_code: "ROOMCHECK-FRESH", room_fingerprint: "c".repeat(64) };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
      requests.push({ url, method, body });
      if (url === "/api/functional-live-room-plans" && method === "GET") return json([replacementQueued ? replacementPlan : reconciliationClosed ? closedPlan : oldPlan]);
      if (url.endsWith("/maitu-capabilities")) return json({ schema_version: "maitu-capability-matrix.v1", adapter_contract: "local", contract_fingerprint: "a".repeat(64), source: "test", can_execute_draft: true, manual_handoff_available: true, unverified_required_capabilities: [], capabilities: [] });
      if (url === "/api/assets?limit=500") return json([{ asset_code: "AG-BG-001", title: "背景素材", original_filename: "background.png", asset_type: "IMG", media_kind: "image", material_roles: ["background"], execution_capability: "maitu_bound", status: "stored", rights_status: "approved", classification_review_status: "confirmed", classification_evidence: {} }]);
      if (url === "/api/functional-live-room-plans/LIVEPLAN-UI-001" && method === "GET") return json(replacementQueued ? replacementPlan : reconciliationClosed ? closedPlan : oldPlan);
      if (url.endsWith("/room-inspections/ROOMCHECK-OLD")) return json(oldInspection);
      if (url === "/api/functional-live-room-plans/room-inspections" && method === "POST") return json(freshInspection, 202);
      if (url.endsWith("/room-inspections/ROOMCHECK-FRESH")) return json(freshInspection);
      if (url.endsWith("/LIVEPLAN-UI-001/execution/reconcile") && method === "POST") {
        reconciliationClosed = true;
        return json({ execution_job_code: "MT-WB-EXEC-OLD", plan_code: "LIVEPLAN-UI-001", source_kind: "functional_live_room_plan", status: "cancelled", stage: "reconciled", progress_current: 2, progress_total: 5, stage_events: [{ stage: "reconciled", message: "旧任务已核对并关闭" }], result: { reconciliation: { replay_allowed: false } }, retryable: false });
      }
      if (url.endsWith("/LIVEPLAN-UI-001/confirm-execution") && method === "POST") {
        replacementQueued = true;
        return json(replacementPlan);
      }
      if (url.endsWith("/LIVEPLAN-UI-001/execution")) {
        if (replacementQueued) return json({ execution_job_code: "MT-WB-EXEC-NEW", plan_code: "LIVEPLAN-UI-001", source_kind: "functional_live_room_plan", status: "queued", stage: "queued", progress_current: 0, progress_total: 5, stage_events: [], result: {}, retryable: false });
        if (reconciliationClosed) return json({ execution_job_code: "MT-WB-EXEC-OLD", plan_code: "LIVEPLAN-UI-001", source_kind: "functional_live_room_plan", status: "cancelled", stage: "reconciled", progress_current: 2, progress_total: 5, stage_events: [{ stage: "reconciled" }], result: { reconciliation: { replay_allowed: false } }, retryable: false });
        return json({ execution_job_code: "MT-WB-EXEC-OLD", plan_code: "LIVEPLAN-UI-001", source_kind: "functional_live_room_plan", status: "reconcile_required", stage: "reconcile_required", progress_current: 2, progress_total: 5, stage_events: [], result: {}, error: { code: "ROOM_WRITE_UNCERTAIN", customer_message: "需要核对麦兔现场", next_step: "重新读取房间" }, retryable: false });
      }
      return json([]);
    }));

    const user = userEvent.setup();
    const rendered = renderPage("?run=LIVEPLAN-UI-001");
    await user.click((await screen.findAllByRole("button", { name: "写入草稿" })).at(-1)!);
    await user.click(await screen.findByRole("button", { name: "重新读取并核对" }));

    expect(await screen.findByText("旧任务已停止，不会自动重放")).toBeInTheDocument();
    expect((await screen.findAllByText("旧场景 1")).length).toBeGreaterThan(0);
    await user.click(rendered.container.querySelector(".live-test-use-ack input")!);
    await user.click(screen.getByRole("button", { name: "按最新现场重新创建任务" }));

    const replacement = requests.find((request) => request.url.endsWith("/LIVEPLAN-UI-001/confirm-execution") && request.method === "POST");
    expect(replacement?.body).toMatchObject({
      room_inspection_code: "ROOMCHECK-FRESH",
      expected_room_fingerprint: "c".repeat(64),
      confirmed_scene_ids: ["OLD-SCENE-1", "OLD-SCENE-2", "OLD-SCENE-3"],
    });
    expect(replacement?.body?.idempotency_key).toEqual(expect.any(String));
  });
});
