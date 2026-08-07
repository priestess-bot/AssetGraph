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
          topic_status: "succeeded",
          topic_code: "TOPIC-1",
          topic_title: "商品价格",
          analysis: {
            analyzer_version: "v1",
            interaction_form: "question",
            business_intent: "promotion",
            topic_summary: "商品价格",
            classification_reason: "用户询问商品价格",
            quality_applicable: true,
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
      topicCode: "TOPIC-1",
      analysis: { interactionForm: "question", businessIntent: "promotion", overallGrade: "fair" },
    });
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/maitu/interactions/analysis/items?answered=true&limit=50&offset=0",
      expect.any(Object),
    );
  });

  it("parses all dashboard intents and semantic topic metrics", async () => {
    const intentCodes = [
      "product_consultation",
      "promotion",
      "non_inquiry",
      "order_fulfillment",
      "after_sales",
      "account_membership",
      "purchase_conversion",
      "review_complaint",
      "small_talk",
    ];
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({
        analyzer_version: "v2",
        analysis_configured: true,
        total: 233,
        classified: 233,
        classification_pending: 0,
        topic_pending: 0,
        answered: 130,
        unanswered: 103,
        quality_evaluated: 130,
        intents: intentCodes.map((business_intent, index) => ({
          business_intent,
          label: `分类${index + 1}`,
          total: index === 0 ? 20 : 0,
          answered: index === 0 ? 12 : 0,
          unanswered: index === 0 ? 8 : 0,
          answer_rate: index === 0 ? 0.6 : 0,
          good: index === 0 ? 7 : 0,
          fair: index === 0 ? 4 : 0,
          poor: index === 0 ? 1 : 0,
        })),
      }))
      .mockResolvedValueOnce(response({
        items: [{
          topic_code: "TOPIC-1",
          title: "商品口感",
          business_intent: "product_consultation",
          total: 20,
          answered: 12,
          unanswered: 8,
          answer_rate: 0.6,
          good: 7,
          fair: 4,
          poor: 1,
        }],
        total: 1,
        limit: 50,
        offset: 0,
      }));
    vi.stubGlobal("fetch", fetch);

    const dashboard = await interactionsApi.analysisDashboard();
    const topics = await interactionsApi.analysisTopics({ businessIntent: "product_consultation" });

    expect(dashboard.intents.map((item) => item.businessIntent)).toEqual(intentCodes);
    expect(dashboard.intents[0]).toMatchObject({ total: 20, answerRate: 0.6, good: 7 });
    expect(topics.items[0]).toMatchObject({ title: "商品口感", unanswered: 8 });
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/maitu/interactions/analysis/topics?business_intent=product_consultation&limit=50&offset=0",
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
