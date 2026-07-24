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
      build_plan: { inventory_snapshot: { asset_codes: [], assets: [], material_pack_refs: [] }, operations: [] }, gate_results: [], status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-25T00:00:00Z",
      quality_report: { material_role_overrides: { background: "AG-IMG-001" }, material_selection_decisions: [{ role: "background", shot_code: "SHOT-001", strategy: "explicit_override", selected_asset_code: "AG-IMG-001", selected_score: 100, selection_reasons: ["ROLE_MATCH"], candidate_scores: [{ asset_code: "AG-IMG-001", score: 100 }] }] },
    })));
    const plan = await functionalLiveRoomsApi.get("LIVEPLAN-001");
    expect(plan.materialRoleOverrides).toEqual({ background: "AG-IMG-001" });
    expect(plan.materialSelectionDecisions[0]).toMatchObject({ role: "background", selectedAssetCode: "AG-IMG-001", strategy: "explicit_override" });
    expect(plan.blueprint.scenes[0]?.layers[0]).toMatchObject({ role: "background", execution_capability: "maitu_bound" });
  });

  it("sends role overrides with a new plan", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      plan_code: "LIVEPLAN-002", project_code: "CONTENT-001", variant_code: "VARIANT-001", configuration_code: "CONFIG-001", target_live_room_id: "room-001", expected_title: "素材选择", selected_asset_codes: [], selected_group_codes: [], selected_material_pack_codes: [], blueprint: { scenes: [] }, build_plan: { inventory_snapshot: {}, operations: [] }, gate_results: [], quality_report: {}, status: "ready", blocked_reasons: [], execution_status: "not_requested", execution_evidence: {}, clone_context: {}, updated_at: "2026-07-25T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetch);
    await functionalLiveRoomsApi.create({ project_code: "CONTENT-001", target_live_room_id: "room-001", expected_title: "素材选择", secondary_template_codes: [], asset_codes: ["AG-IMG-001"], group_codes: [], material_pack_codes: [], material_role_overrides: { background: "AG-IMG-001" } });
    expect(fetch).toHaveBeenCalledWith("/api/functional-live-room-plans", expect.objectContaining({ method: "POST", body: expect.stringContaining('"material_role_overrides":{"background":"AG-IMG-001"}') }));
  });
});
