import { afterEach, describe, expect, it, vi } from "vitest";
import { functionalLiveRoomsApi } from "./api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("functional live room api", () => {
  afterEach(() => vi.unstubAllGlobals());

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
    await functionalLiveRoomsApi.create({ project_code: "CONTENT-001", target_live_room_id: "room-001", expected_title: "素材选择", secondary_template_codes: [], asset_codes: ["AG-IMG-001"], group_codes: [], material_pack_codes: [], asset_gap_codes: ["AG-GAP-001"], material_role_overrides: { background: "AG-IMG-001" }, room_constraint_overrides: { "AG-IMG-001": { reason: "适配当前直播间", geometry: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, zOrder: 12 } } });
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"material_role_overrides":{"background":"AG-IMG-001"}') }));
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"asset_gap_codes":["AG-GAP-001"]') }));
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"room_constraint_overrides":{"AG-IMG-001":{"reason":"适配当前直播间","geometry":{"x":0.1,"y":0.1,"width":0.8,"height":0.8},"z_order":12}}') }));
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
});
