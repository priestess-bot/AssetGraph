import { describe, expect, it, vi } from "vitest";
import { operationsApi } from "./api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("operations api", () => {
  it("submits an append-only exposure supersede correction", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        exposure_code: "EXPOSURE-002",
        session_code: "OPS-001",
        plan_code: "PLAN-001",
        variant_code: "VAR-001",
        scene_code: "SCENE-002",
        started_at: "2026-07-25T12:00:00Z",
        ended_at: "2026-07-25T12:02:00Z",
        source_kind: "recording_match",
        evidence_note: "recording",
        confidence: 0.95,
        status: "active",
        supersedes_exposure_code: "EXPOSURE-001",
        correction_reason: "corrected recording match",
        created_at: "2026-07-25T12:03:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const payload = {
      source_exposure_code: "EXPOSURE-001",
      correction_kind: "supersede",
      reason: "corrected recording match",
      actor: "operator",
      replacement: {
        session_code: "OPS-001",
        plan_code: "PLAN-001",
        scene_code: "SCENE-002",
        started_at: "2026-07-25T12:00:00Z",
        ended_at: "2026-07-25T12:02:00Z",
        source_kind: "recording_match",
        evidence_note: "recording",
        confidence: 0.95,
      },
    };

    const corrected = await operationsApi.correctExposure(payload);

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/functional-operations/exposure-corrections",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual(
      payload,
    );
    expect(corrected).toMatchObject({
      exposureCode: "EXPOSURE-002",
      supersedesExposureCode: "EXPOSURE-001",
      correctionReason: "corrected recording match",
    });
  });

  it("parses the fixed content chain for an observed timeline span", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      session_code: "OPS-001",
      started_at: "2026-07-25T12:00:00Z",
      ended_at: "2026-07-25T12:10:00Z",
      total_seconds: 600,
      observed_seconds: 120,
      coverage_ratio: 0.2,
      unobserved_seconds: 480,
      status: "resolved",
      missing_plan_codes: [],
      spans: [{
        exposure_code: "EXPOSURE-001",
        plan_code: "PLAN-001",
        variant_code: "VAR-001",
        scene_code: "SCENE-001",
        started_at: "2026-07-25T12:00:00Z",
        ended_at: "2026-07-25T12:02:00Z",
        duration_seconds: 120,
        source_kind: "recording_match",
        confidence: 0.95,
        scene: { scene_code: "SCENE-001", shot_code: "SHOT-001", status: "resolved" },
        content: {
          status: "resolved",
          program_segment: { segment_code: "SEGMENT-001", program_phase: "conversion", semantic_goal: "引导互动", product_refs: ["PROD-001"], cta_actions: [{ type: "comment" }] },
          script_blocks: [{ block_code: "BLOCK-001", module_type: "conversion", product_ref: "PROD-001", template_modules: [{ template_code: "TEMPLATE-001", revision: 2, module_key: "conversion" }], cta_intent: { type: "comment" } }],
        },
        layers: [],
      }],
    })));

    const timeline = await operationsApi.getContentTimeline("OPS-001");

    expect(timeline.spans[0]?.content).toEqual({
      status: "resolved",
      programSegment: { segmentCode: "SEGMENT-001", programPhase: "conversion", semanticGoal: "引导互动", productRefs: ["PROD-001"], ctaActions: [{ type: "comment" }] },
      scriptBlocks: [{ blockCode: "BLOCK-001", moduleType: "conversion", productRef: "PROD-001", templateModules: [{ templateCode: "TEMPLATE-001", revision: 2, moduleKey: "conversion" }], ctaIntent: { type: "comment" } }],
    });
  });
});
