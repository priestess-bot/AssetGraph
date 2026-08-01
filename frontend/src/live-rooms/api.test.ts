import { afterEach, describe, expect, it, vi } from "vitest";
import { functionalLiveRoomsApi } from "./api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("functional live room api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the conservative Maitu capability contract", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      schema_version: "maitu-capability-matrix.v1",
      adapter_contract: "maitu-web-working-room.internal.v1",
      contract_fingerprint: "a".repeat(64),
      source: "repository_evidence",
      can_execute_draft: false,
      manual_handoff_available: true,
      unverified_required_capabilities: ["create_scene"],
      capabilities: [{
        key: "create_scene",
        title: "创建场景",
        status: "manual_only",
        required_for_draft: true,
        last_verified_at: null,
        evidence_level: "repository_contract_only",
        evidence_refs: ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        customer_message: "等待真实账号验证。",
      }],
    }));
    vi.stubGlobal("fetch", fetch);

    const matrix = await functionalLiveRoomsApi.maituCapabilities();

    expect(matrix).toMatchObject({
      canExecuteDraft: false,
      manualHandoffAvailable: true,
      unverifiedRequiredCapabilities: ["create_scene"],
    });
    expect(matrix.capabilities[0]).toMatchObject({
      key: "create_scene",
      status: "manual_only",
      requiredForDraft: true,
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/functional-live-room-plans/maitu-capabilities",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("reads persisted material-role selection decisions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      plan_code: "LIVEPLAN-001", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "room-001", expected_title: "素材选择", selected_asset_codes: [], selected_group_codes: [], selected_material_pack_codes: [],
      blueprint: { schema_version: "maitu-scene-blueprint.functional.v2", scenes: [{ scene_code: "MSB-001", shot_code: "SHOT-001", title: "开场", layers: [{ material_role: "background", asset_code: "AG-IMG-001", asset_binding_ref: { execution_capability: "maitu_bound" }, z_order: 1 }] }] },
      build_plan: { inventory_snapshot: { asset_codes: [], assets: [], material_pack_refs: [], room_constraint_overrides: { "AG-IMG-001": { reason: "适配当前房间", geometry: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, z_order: 12, actor_id: "operator-1" } } }, operations: [] }, gate_results: [], status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-25T00:00:00Z",
      quality_report: { material_role_overrides: { background: "AG-IMG-001" }, material_selection_decisions: [{ role: "background", shot_code: "SHOT-001", strategy: "explicit_override", selected_asset_code: "AG-IMG-001", selected_score: 100, selection_reasons: ["ROLE_MATCH"], candidate_scores: [{ asset_code: "AG-IMG-001", score: 100 }] }] },
    })));
    const plan = await functionalLiveRoomsApi.get("LIVEPLAN-001");
    expect(plan.materialRoleOverrides).toEqual({ background: "AG-IMG-001" });
    expect(plan.materialSelectionDecisions[0]).toMatchObject({ role: "background", selectedAssetCode: "AG-IMG-001", strategy: "explicit_override" });
    expect(plan.blueprint.scenes[0]?.layers[0]).toMatchObject({ role: "background", execution_capability: "maitu_bound" });
    expect(plan.materialSnapshot.roomConstraintOverrides["AG-IMG-001"]).toMatchObject({ reason: "适配当前房间", geometry: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, zOrder: 12, actorId: "operator-1" });
  });

  it("sends role overrides with a new plan", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      plan_code: "LIVEPLAN-002", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "room-001", expected_title: "素材选择", selected_asset_codes: [], selected_group_codes: [], selected_material_pack_codes: [], blueprint: { scenes: [] }, build_plan: { inventory_snapshot: {}, operations: [] }, gate_results: [], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-25T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetch);
    await functionalLiveRoomsApi.create({ idempotency_key: "plan-request-001", project_code: "CONTENT-001", target_live_room_id: "room-001", expected_title: "素材选择", secondary_template_codes: [], asset_codes: ["AG-IMG-001"], group_codes: [], material_pack_codes: [], asset_gap_codes: ["AG-GAP-001"], material_role_overrides: { background: "AG-IMG-001" }, room_constraint_overrides: { "AG-IMG-001": { reason: "适配当前直播间", geometry: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, zOrder: 12 } } });
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"material_role_overrides":{"background":"AG-IMG-001"}') }));
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"asset_gap_codes":["AG-GAP-001"]') }));
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"room_constraint_overrides":{"AG-IMG-001":{"reason":"适配当前直播间","geometry":{"x":0.1,"y":0.1,"width":0.8,"height":0.8},"z_order":12}}') }));
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"idempotency_key":"plan-request-001"') }));
  });

  it("previews live-room material gaps without creating a plan", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001",
      project_revision_number: 4,
      shot_list_revision_number: 7,
      checked_asset_codes: ["AG-IMG-001"],
      gaps: [{
        diagnostic_key: "a".repeat(64), role: "background", title: "缺少可执行 background 素材",
        severity: "high", gap_type: "role_coverage", required_shot_codes: ["SHOT-001"],
        missing_occurrences: 1, selection_mode: "append", alternative_asset_codes: ["AG-IMG-002"],
        create_payload: {
          title: "缺少可执行 background 素材", role: "background", severity: "high", gap_type: "role_coverage",
          specification: { required_role: "background" },
          source_context: { diagnostic_key: "a".repeat(64) },
          impact_summary: "缺少背景", alternative_asset_codes: ["AG-IMG-002"],
        },
      }],
    }));
    vi.stubGlobal("fetch", fetch);

    const preview = await functionalLiveRoomsApi.previewMaterialGaps({
      project_code: "CONTENT-001", asset_codes: ["AG-IMG-001"], group_codes: [], material_pack_codes: [],
      material_role_modes: { background: "append" },
    });

    expect(preview.gaps[0]).toMatchObject({ role: "background", alternativeAssetCodes: ["AG-IMG-002"] });
    expect(fetch).toHaveBeenCalledWith(
      "/api/functional-live-room-plans/material-gap-preview",
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"project_code":"CONTENT-001"') }),
    );
  });

  it("requests a worker handoff and synchronizes its readback", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({
        plan_code: "LIVEPLAN-003",
        build_plan_code: "MT-BUILD-001",
        target_live_room_id: "room-001",
        checkpoint_contract: "script_layout_checkpoint_v1",
        source_plan_fingerprint: "a".repeat(64),
        operation_count: 3,
        operation_types: ["preflight_content_build_plan", "create_scene", "save_draft"],
      }))
      .mockResolvedValueOnce(response({
        plan_code: "LIVEPLAN-003", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "room-001", expected_title: "素材选择", selected_asset_codes: [], selected_group_codes: [], selected_material_pack_codes: [], blueprint: { scenes: [] }, build_plan: { inventory_snapshot: {}, operations: [] }, gate_results: [], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "maitu_complete", execution_evidence: { status: "finalized_draft_readback" }, clone_context: {}, updated_at: "2026-07-25T00:00:00Z",
      }));
    vi.stubGlobal("fetch", fetch);

    const handoff = await functionalLiveRoomsApi.executionHandoff("LIVEPLAN-003");
    const synced = await functionalLiveRoomsApi.syncExecution("LIVEPLAN-003");

    expect(handoff).toMatchObject({ buildPlanCode: "MT-BUILD-001", operationCount: 3 });
    expect(synced.executionStatus).toBe("maitu_complete");
    expect(fetch).toHaveBeenCalledWith(
      "/api/functional-live-room-plans/LIVEPLAN-003/execution-handoff",
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/functional-live-room-plans/LIVEPLAN-003/sync-execution",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("reads a room inspection without exposing worker internals to the page model", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      inspection_code: "ROOMCHECK-001",
      target_live_room_id: "41172",
      expected_title: "asser测试",
      authority_mode: "worker_readback",
      status: "succeeded",
      attempt: 1,
      room_fingerprint: "f".repeat(64),
      result: {
        actual_title: "asser测试",
        is_live: false,
        has_live_trace: false,
        read_environment: "working_room",
        scene_count: 2,
        scenes: [
          { scene_id: "scene-a", name: "旧场景一", order_num: 1, material_count: 3 },
          { scene_id: "scene-b", name: "旧场景二", order_num: 2, material_count: 4 },
        ],
        ready_for_go_live: false,
        go_live_clicked: false,
      },
    }));
    vi.stubGlobal("fetch", fetch);

    const inspection = await functionalLiveRoomsApi.getRoomInspection("ROOMCHECK-001");

    expect(inspection).toMatchObject({ targetLiveRoomId: "41172", status: "succeeded", roomFingerprint: "f".repeat(64) });
    expect(inspection.result?.scenes[1]).toEqual({ sceneId: "scene-b", name: "旧场景二", orderNumber: 2, materialCount: 4 });
  });

  it("confirms replacement only with the inspected fingerprint and explicit test acknowledgement", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      plan_code: "LIVEPLAN-004", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "41172", expected_title: "asser测试", selected_asset_codes: [], selected_group_codes: [], selected_material_pack_codes: [], blueprint: { scenes: [] }, build_plan: { inventory_snapshot: {}, operations: [] }, gate_results: [], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "requested", execution_job_code: "DRAFTJOB-001", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-31T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetch);

    const plan = await functionalLiveRoomsApi.confirmExecution("LIVEPLAN-004", {
      draftMode: "replace_test_draft",
      roomInspectionCode: "ROOMCHECK-001",
      expectedRoomFingerprint: "f".repeat(64),
      confirmedSceneIds: ["scene-a", "scene-b"],
      idempotencyKey: "request-001",
      testUseAcknowledged: true,
    });

    expect(plan.executionJobCode).toBe("DRAFTJOB-001");
    expect(fetch).toHaveBeenCalledWith(
      "/api/functional-live-room-plans/LIVEPLAN-004/confirm-execution",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"test_use_acknowledged":true'),
      }),
    );
    expect(String(fetch.mock.calls[0]?.[1]?.body)).toContain('"confirmed_scene_ids":["scene-a","scene-b"]');
  });

  it("normalizes real draft job progress and customer-facing recovery", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      execution_job_code: "DRAFTJOB-002",
      plan_code: "LIVEPLAN-004",
      source_kind: "functional_live_room_plan",
      status: "failed",
      stage: "building_scenes",
      progress_current: 4,
      progress_total: 9,
      stage_events: [{ stage: "preparing_materials", status: "completed" }, { stage: "building_scenes", status: "failed" }],
      error: { code: "INTERNAL_CODE", message: "raw worker failure", customer_message: "第二个场景没有保存", next_step: "重新登录麦兔后重试失败步骤" },
      retryable: true,
    })));

    const job = await functionalLiveRoomsApi.getExecution("LIVEPLAN-004");

    expect(job).toMatchObject({ executionJobCode: "DRAFTJOB-002", status: "failed", stage: "building_scenes", progressCurrent: 4, progressTotal: 9, retryable: true });
    expect(job.error?.customerMessage).toBe("第二个场景没有保存");
  });

  it("saves a blueprint revision with normalized layer geometry", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      plan_code: "LIVEPLAN-REV-002",
      project_code: "CONTENT-001",
      variant_code: "VARIANT-002",
      configuration_code: "CONFIG-002",
      target_live_room_id: "room-001",
      expected_title: "场景调整",
      selected_asset_codes: ["AG-IMG-002"],
      selected_group_codes: [],
      selected_material_pack_codes: [],
      revised_from_plan_code: "LIVEPLAN-REV-001",
      revision_context: { changed_shot_codes: ["SHOT-001"] },
      blueprint: {
        schema_version: "maitu-scene-blueprint.functional.v2",
        scenes: [{
          scene_code: "MSB-002",
          shot_code: "SHOT-001",
          title: "调整后的开场",
          script: "调整后的话术",
          layers: [{
            material_role: "background",
            asset_code: "AG-IMG-002",
            asset_binding_ref: { execution_capability: "maitu_bound" },
            normalized_geometry: { x: 0.1, y: 0.2, width: 0.8, height: 0.6 },
            z_order: 12,
          }],
        }],
      },
      build_plan: { inventory_snapshot: {}, operations: [], go_live: false },
      gate_results: [],
      quality_report: {},
      status: "ready",
      blocked_reasons: [],
      execution_status: "not_requested",
      execution_evidence: {},
      clone_context: {},
      updated_at: "2026-07-26T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetch);

    const revised = await functionalLiveRoomsApi.reviseBlueprint(
      "LIVEPLAN-REV-001",
      {
        scenes: [{
          shot_code: "SHOT-001",
          sort_order: 0,
          title: "调整后的开场",
          script: "调整后的话术",
          layers: [{
            role: "background",
            asset_code: "AG-IMG-002",
            geometry: { x: 0.1, y: 0.2, width: 0.8, height: 0.6 },
            z_order: 12,
          }],
        }],
      },
    );

    expect(revised.revisedFromPlanCode).toBe("LIVEPLAN-REV-001");
    expect(revised.revisionContext).toEqual({ changed_shot_codes: ["SHOT-001"] });
    expect(revised.blueprint.scenes[0]?.layers[0]?.normalized_geometry).toEqual({
      x: 0.1,
      y: 0.2,
      width: 0.8,
      height: 0.6,
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/functional-live-room-plans/LIVEPLAN-REV-001/blueprint-revisions",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"asset_code":"AG-IMG-002"'),
      }),
    );
  });
});
