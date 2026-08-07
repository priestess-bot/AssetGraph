import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InteractionProductPage } from "./InteractionProductPage";


const INTENTS = [
  ["product_consultation", "商品咨询"],
  ["promotion", "优惠活动"],
  ["non_inquiry", "非问询"],
  ["order_fulfillment", "订单履约"],
  ["after_sales", "售后服务"],
  ["account_membership", "账户与会员"],
  ["purchase_conversion", "下单转化"],
  ["review_complaint", "评价与投诉"],
  ["small_talk", "闲聊"],
] as const;


function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}


function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InteractionProductPage />
    </QueryClientProvider>,
  );
}


describe("interaction analysis product page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps all nine intents visible even when some categories have zero interactions", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/source")) return json({ source_code: "maitu-primary", status: "active", timezone: "Asia/Shanghai", daily_sync_time: "02:00", rescan_days: 7, analysis_configured: true });
      if (url.includes("/sync-runs")) return json([]);
      if (url.includes("/platforms")) return json([{ external_platform_id: 4, platform_code: "jd", platform_name: "京东", is_available: true, session_count: 0, interaction_count: 233, arrival_count: 0, effective_count: 233 }]);
      if (url.includes("/sessions")) return json({ items: [], total: 0, limit: 100, offset: 0 });
      if (url.includes("/analysis/dashboard")) return json({
        analyzer_version: "v2",
        analysis_configured: true,
        total: 233,
        classified: 233,
        classification_pending: 0,
        topic_pending: 0,
        answered: 130,
        unanswered: 103,
        quality_evaluated: 130,
        intents: INTENTS.map(([business_intent, label], index) => ({
          business_intent,
          label,
          total: index === 0 ? 233 : 0,
          answered: index === 0 ? 130 : 0,
          unanswered: index === 0 ? 103 : 0,
          answer_rate: index === 0 ? 130 / 233 : 0,
          good: index === 0 ? 90 : 0,
          fair: index === 0 ? 30 : 0,
          poor: index === 0 ? 10 : 0,
        })),
      });
      if (url.includes("/analysis/topics")) return json({ items: [], total: 0, limit: 100, offset: 0 });
      if (url.includes("/analysis/items")) return json({ items: [], total: 0, limit: 50, offset: 0 });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "互动分析" }));

    for (const [, label] of INTENTS) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("233 条已分类")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "关注热点" })).toHaveAttribute("aria-selected", "true");
  });
});
