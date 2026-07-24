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
      alignment_coverage_ratio: 0.2,
      time_mapping: {
        mapping_code: "TIME-MAP-001",
        session_code: "OPS-001",
        revision_number: 2,
        status: "active",
        source_clock: "recording_elapsed_ms",
        source_kind: "recording_anchor",
        source_offset_ms: 120,
        drift_ppm: 5,
        coverage_start_ms: 0,
        coverage_end_ms: 120000,
        evidence_note: "matched recording anchors",
        actor: "operator",
        created_at: "2026-07-25T12:11:00Z",
      },
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
        source_start_ms: 120,
        source_end_ms: 120121,
        alignment_status: "aligned",
      }],
    })));

    const timeline = await operationsApi.getContentTimeline("OPS-001");

    expect(timeline.spans[0]?.content).toEqual({
      status: "resolved",
      programSegment: { segmentCode: "SEGMENT-001", programPhase: "conversion", semanticGoal: "引导互动", productRefs: ["PROD-001"], ctaActions: [{ type: "comment" }] },
      scriptBlocks: [{ blockCode: "BLOCK-001", moduleType: "conversion", productRef: "PROD-001", templateModules: [{ templateCode: "TEMPLATE-001", revision: 2, moduleKey: "conversion" }], ctaIntent: { type: "comment" } }],
    });
    expect(timeline.timeMapping).toMatchObject({
      mappingCode: "TIME-MAP-001",
      revisionNumber: 2,
      sourceOffsetMs: 120,
    });
    expect(timeline.spans[0]).toMatchObject({
      sourceStartMs: 120,
      sourceEndMs: 120121,
      alignmentStatus: "aligned",
    });
  });

  it("creates a revisioned session time mapping", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        mapping_code: "TIME-MAP-001",
        session_code: "OPS-001",
        revision_number: 1,
        status: "active",
        source_clock: "recording_elapsed_ms",
        source_kind: "recording_anchor",
        source_offset_ms: 0,
        drift_ppm: 0,
        coverage_start_ms: 0,
        coverage_end_ms: 600000,
        evidence_note: "opening anchor",
        actor: "operator",
        created_at: "2026-07-25T12:11:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const payload = {
      expected_revision: 0,
      source_clock: "recording_elapsed_ms",
      source_kind: "recording_anchor",
      source_offset_ms: 0,
      drift_ppm: 0,
      coverage_start_ms: 0,
      coverage_end_ms: 600000,
      evidence_note: "opening anchor",
      actor: "operator",
    };

    const mapping = await operationsApi.createTimeMapping("OPS-001", payload);

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/functional-operations/sessions/OPS-001/time-mappings",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual(payload);
    expect(mapping).toMatchObject({ mappingCode: "TIME-MAP-001", revisionNumber: 1 });
  });
});
