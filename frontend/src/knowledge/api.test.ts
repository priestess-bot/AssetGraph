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

  it("keeps source evidence checksum and claim citation explicit", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response([{
        evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", status: "approved",
      }]))
      .mockResolvedValueOnce(response({
        claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty", source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved", claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.", status: "draft", fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
      }));
    vi.stubGlobal("fetch", fetch);
    const sources = await knowledgeApi.listSourceEvidences();
    const claim = await knowledgeApi.createFactClaim({ fact_title: "Warranty", claim: "Warranty is 12 months.", source_evidence_code: "EVIDENCE-001", citation_excerpt: "Verified warranty is 12 months." });
    expect(sources[0]).toMatchObject({ evidenceCode: "EVIDENCE-001", contentChecksum: "a".repeat(64), status: "approved" });
    expect(claim).toMatchObject({ claimCode: "CLAIM-001", sourceEvidenceCode: "EVIDENCE-001", citationExcerpt: "Verified warranty is 12 months." });
    expect(fetch).toHaveBeenLastCalledWith("/api/functional-knowledge/fact-claims", expect.objectContaining({ method: "POST" }));
  });

  it("requires a named reason when revoking local evidence and claims", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({
        evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", status: "revoked", revoked_by: "reviewer", revoked_at: "2026-07-25T00:00:00Z", revoked_reason: "Source corrected.",
      }))
      .mockResolvedValueOnce(response({
        claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty", source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "revoked", claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.", status: "revoked", revoked_by: "reviewer", revoked_at: "2026-07-25T00:00:00Z", revoked_reason: "Terms changed.", fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
      }));
    vi.stubGlobal("fetch", fetch);

    const source = await knowledgeApi.revokeSourceEvidence("EVIDENCE-001", "reviewer", "Source corrected.");
    const claim = await knowledgeApi.revokeFactClaim("CLAIM-001", "reviewer", "Terms changed.");

    expect(source).toMatchObject({ status: "revoked", revokedBy: "reviewer", revokedReason: "Source corrected." });
    expect(claim).toMatchObject({ status: "revoked", sourceStatus: "revoked", revokedReason: "Terms changed." });
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/functional-knowledge/source-evidences/EVIDENCE-001/revoke", expect.objectContaining({ method: "POST", body: JSON.stringify({ actor: "reviewer", reason: "Source corrected." }) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/functional-knowledge/fact-claims/CLAIM-001/revoke", expect.objectContaining({ method: "POST", body: JSON.stringify({ actor: "reviewer", reason: "Terms changed." }) }));
  });
});
