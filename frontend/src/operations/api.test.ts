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
});
