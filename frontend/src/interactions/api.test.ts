import { afterEach, describe, expect, it, vi } from "vitest";
import { interactionsApi } from "./api";


function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}


describe("interactions api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses source, platform, and interaction analysis without changing reply semantics", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({
        source_code: "maitu-primary",
        status: "active",
        timezone: "Asia/Shanghai",
        daily_sync_time: "02:00",
        rescan_days: 7,
        analysis_configured: true,
      }))
      .mockResolvedValueOnce(response([{
        external_platform_id: 4,
        platform_code: "jd",
        platform_name: "京东",
        is_available: true,
        session_count: 2,
        interaction_count: 10,
        arrival_count: 7,
        effective_count: 3,
      }]))
      .mockResolvedValueOnce(response({
        items: [{
          id: "row-1",
          external_interaction_id: "9001",
          external_session_id: 156953,
          session_title: "测试直播",
          external_platform_id: 4,
          platform_name: "京东",
          interaction_type: 0,
          content: "多少钱？",
          normalized_content: "多少钱？",
          is_arrival: false,
          digital_reply_content: "请看三号链接",
          bullet_reply_content: "三号链接",
          is_answered: true,
          analysis_status: "succeeded",
          analysis: {
            analyzer_version: "v1",
            interaction_form: "question",
            business_intent: "price_promotion_gift",
            relevance_grade: "good",
            completeness_grade: "fair",
            resolution_grade: "fair",
            overall_grade: "fair",
            confidence: 0.9,
            reason: "相关但不够完整",
            created_at: "2026-08-03T00:00:00Z",
          },
        }],
        total: 1,
        limit: 50,
        offset: 0,
      }));
    vi.stubGlobal("fetch", fetch);

    const source = await interactionsApi.source();
    const platforms = await interactionsApi.platforms();
    const items = await interactionsApi.analysisItems({ answered: true });

    expect(source).toMatchObject({ status: "active", dailySyncTime: "02:00", analysisConfigured: true });
    expect(platforms[0]).toMatchObject({ platformName: "京东", effectiveCount: 3 });
    expect(items.items[0]).toMatchObject({
      answered: true,
      digitalReplyContent: "请看三号链接",
      bulletReplyContent: "三号链接",
      analysis: { interactionForm: "question", overallGrade: "fair" },
    });
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/maitu/interactions/analysis/items?answered=true&limit=50&offset=0",
      expect.any(Object),
    );
  });

  it("starts an explicit incremental sync", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      run_code: "MT-INT-SYNC-1",
      sync_mode: "incremental",
      status: "queued",
      attempt: 0,
      result_summary: {},
      created_at: "2026-08-03T00:00:00Z",
      updated_at: "2026-08-03T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetch);

    await interactionsApi.startSync();

    expect(fetch).toHaveBeenCalledWith(
      "/api/maitu/interactions/sync-runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          sync_mode: "incremental",
          target_external_session_id: undefined,
          requested_by: "console-operator",
        }),
      }),
    );
  });
});
