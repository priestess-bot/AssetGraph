import { afterEach, describe, expect, it, vi } from "vitest";
import { knowledgeApi } from "./api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("knowledge api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps approved fact-card revisions explicit for production selection", async () => {
    const fetch = vi.fn().mockResolvedValue(response([{
      fact_card_code: "MT-FACT-001", title: "已验证商品", status: "active", current_approved_version: 2,
      versions: [{ version_code: "MT-FACT-001-V002", version_number: 2, status: "approved", content: { verified_facts: ["库存充足"] }, approved_by: "reviewer" }],
    }]));
    vi.stubGlobal("fetch", fetch);
    const cards = await knowledgeApi.listProductFactCards();
    expect(cards[0]).toMatchObject({ factCardCode: "MT-FACT-001", currentApprovedVersion: 2 });
    expect(cards[0]?.versions[0]).toMatchObject({ versionNumber: 2, status: "approved", approvedBy: "reviewer" });
    expect(fetch).toHaveBeenCalledWith("/api/maitu/workbench/product-fact-cards", expect.any(Object));
  });

  it("uses explicit reviewer and rejection reason for version decisions", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ version_code: "MT-FACT-001-V002" }));
    vi.stubGlobal("fetch", fetch);
    await knowledgeApi.rejectProductFactCardVersion("MT-FACT-001", 2, "reviewer", "来源不足");
    expect(fetch).toHaveBeenCalledWith("/api/maitu/workbench/product-fact-cards/MT-FACT-001/versions/2/reject", expect.objectContaining({ method: "POST", body: JSON.stringify({ rejected_by: "reviewer", reason: "来源不足" }) }));
  });
});
