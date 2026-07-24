import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkbenchApiError, normalizeProblem, requestJson } from "./api";


function response(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}


describe("workbench problem contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("normalizes stable problem fields", () => {
    expect(normalizeProblem({
      code: "STALE_REVISION",
      state: "stale",
      message: "Expected revision is stale",
      impact: "No write was committed.",
      evidence: [{ kind: "trace", ref: "abc" }],
      next_step: "Reload and inspect the diff.",
      retryable: false,
      trace_id: "abc",
    })).toEqual({
      code: "STALE_REVISION",
      state: "stale",
      message: "Expected revision is stale",
      impact: "No write was committed.",
      evidence: [{ kind: "trace", ref: "abc" }],
      nextStep: "Reload and inspect the diff.",
      retryable: false,
      traceId: "abc",
    });
  });

  it("attaches the structured problem while retaining legacy detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      detail: "Retry checkpoint conflict",
      error: {
        code: "STALE_REVISION",
        state: "stale",
        message: "Retry checkpoint conflict",
        impact: "No write was committed.",
        evidence: [{ kind: "request", ref: "/api/retry" }],
        next_step: "Reload the latest revision.",
        retryable: false,
        trace_id: null,
      },
    }, 409)));

    const error = await requestJson("/api/retry").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(WorkbenchApiError);
    expect(error).toMatchObject({
      status: 409,
      message: "Retry checkpoint conflict",
      detail: { detail: "Retry checkpoint conflict" },
      problem: { code: "STALE_REVISION", state: "stale", retryable: false },
    });
  });
});
