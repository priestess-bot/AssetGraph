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
        evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", extractor_strategy_ref: "manual_excerpt.v1", extraction_runs: [{ extraction_run_code: "EXTRACT-001", evidence_code: "EVIDENCE-001", extractor_strategy_ref: "manual_excerpt.v1", input_fingerprint_sha256: "a".repeat(64), output_checksum_sha256: "c".repeat(64), extraction_metadata: { capture_mode: "manual" } }], status: "approved",
      }]))
      .mockResolvedValueOnce(response({
        claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty", source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved", claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.", citation_start_offset: 0, citation_end_offset: 31, status: "draft", fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
      }));
    vi.stubGlobal("fetch", fetch);
    const sources = await knowledgeApi.listSourceEvidences();
    const claim = await knowledgeApi.createFactClaim({ fact_title: "Warranty", claim: "Warranty is 12 months.", source_evidence_code: "EVIDENCE-001", citation_excerpt: "Verified warranty is 12 months." });
    expect(sources[0]).toMatchObject({ evidenceCode: "EVIDENCE-001", contentChecksum: "a".repeat(64), extractorStrategyRef: "manual_excerpt.v1", extractionRuns: [{ extractionRunCode: "EXTRACT-001", outputChecksum: "c".repeat(64) }], status: "approved" });
    expect(claim).toMatchObject({ claimCode: "CLAIM-001", sourceEvidenceCode: "EVIDENCE-001", citationExcerpt: "Verified warranty is 12 months.", citationStartOffset: 0, citationEndOffset: 31 });
    expect(fetch).toHaveBeenLastCalledWith("/api/functional-knowledge/fact-claims", expect.objectContaining({ method: "POST" }));
  });

  it("parses knowledge search validation without mistaking it for authorization", async () => {
    const fetch = vi.fn().mockResolvedValue(response([{
      entity_type: "content_rule", entity_code: "RULE-001", title: "No unsupported price claim", summary: "Do not promise an unverified price.", status: "approved",
      source_evidence_code: "EVIDENCE-001", source_status: "approved", scope: { platforms: ["douyin"] },
      validation: { lifecycle: "approved", source: "approved", validity: "valid", scope: "match", rights: "not_modeled", content_eligible: true, authorization_eligible: false, blocking_rule_codes: [] },
      created_at: "2026-07-25T00:00:00Z",
    }]));
    vi.stubGlobal("fetch", fetch);

    const results = await knowledgeApi.searchKnowledge("price", "douyin", "2026-07-25T00:00:00Z");

    expect(results[0]).toMatchObject({ entityType: "content_rule", entityCode: "RULE-001", validation: { contentEligible: true, authorizationEligible: false, rights: "not_modeled" } });
    expect(fetch).toHaveBeenCalledWith("/api/functional-knowledge/search?q=price&platform=douyin&as_of=2026-07-25T00%3A00%3A00Z", expect.any(Object));
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

  it("keeps draft rejections attributable for local evidence and claims", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({
        evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", status: "rejected", rejected_by: "reviewer", rejected_at: "2026-07-25T00:00:00Z", rejection_reason: "The document is incomplete.",
      }))
      .mockResolvedValueOnce(response({
        claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty", source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved", claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.", status: "rejected", rejected_by: "reviewer", rejected_at: "2026-07-25T00:00:00Z", rejection_reason: "The citation is incomplete.", fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
      }));
    vi.stubGlobal("fetch", fetch);

    const source = await knowledgeApi.rejectSourceEvidence("EVIDENCE-001", "reviewer", "The document is incomplete.");
    const claim = await knowledgeApi.rejectFactClaim("CLAIM-001", "reviewer", "The citation is incomplete.");

    expect(source).toMatchObject({ status: "rejected", rejectedBy: "reviewer", rejectionReason: "The document is incomplete." });
    expect(claim).toMatchObject({ status: "rejected", rejectedBy: "reviewer", rejectionReason: "The citation is incomplete." });
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/functional-knowledge/source-evidences/EVIDENCE-001/reject", expect.objectContaining({ method: "POST", body: JSON.stringify({ actor: "reviewer", reason: "The document is incomplete." }) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/functional-knowledge/fact-claims/CLAIM-001/reject", expect.objectContaining({ method: "POST", body: JSON.stringify({ actor: "reviewer", reason: "The citation is incomplete." }) }));
  });

  it("queries fact claims by text without dropping validity metadata", async () => {
    const fetch = vi.fn().mockResolvedValue(response([{
      claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty", source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved", claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.", valid_from: "2026-07-25T00:00:00Z", valid_until: "2026-12-31T23:59:59Z", status: "approved", fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
    }]));
    vi.stubGlobal("fetch", fetch);

    const claims = await knowledgeApi.searchFactClaims("Warranty term");

    expect(claims[0]).toMatchObject({ validFrom: "2026-07-25T00:00:00Z", validUntil: "2026-12-31T23:59:59Z" });
    expect(fetch).toHaveBeenCalledWith("/api/functional-knowledge/fact-claims?q=Warranty%20term", expect.any(Object));
  });

  it("reads only explicit fixed claim usage from the lineage endpoint", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty",
      claim_status: "approved", fact_status: "approved",
      source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved",
      uses: [{ relation_type: "pins_fact_claim", object_type: "content_project", object_code: "CONTENT-001", revision_number: 2, status: "confirmed", created_at: "2026-07-25T00:00:00Z" }],
    }));
    vi.stubGlobal("fetch", fetch);

    const lineage = await knowledgeApi.getFactClaimLineage("CLAIM-001");

    expect(lineage).toMatchObject({ claimCode: "CLAIM-001", factStatus: "approved", uses: [{ objectCode: "CONTENT-001", revisionNumber: 2, relationType: "pins_fact_claim" }] });
    expect(fetch).toHaveBeenCalledWith("/api/functional-knowledge/fact-claims/CLAIM-001/lineage", expect.any(Object));
  });

  it("keeps reviewed content rules separate from product facts", async () => {
    const fetch = vi.fn().mockResolvedValue(response({
      rule_code: "RULE-001", rule_kind: "expression_ban", directive: "must_avoid",
      title: "No unsupported price claim", rule_text: "Do not promise an unverified price.",
      scope: { platforms: ["douyin"] }, source_evidence_code: "EVIDENCE-001",
      source_title: "Product sheet", source_status: "approved", source_content_sha256: "a".repeat(64),
      status: "draft", fingerprint_sha256: "c".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
    }));
    vi.stubGlobal("fetch", fetch);

    const rule = await knowledgeApi.createContentRule({ rule_kind: "expression_ban", directive: "must_avoid", title: "No unsupported price claim", rule_text: "Do not promise an unverified price.", source_evidence_code: "EVIDENCE-001" });

    expect(rule).toMatchObject({ ruleCode: "RULE-001", ruleKind: "expression_ban", directive: "must_avoid", sourceStatus: "approved" });
    expect(fetch).toHaveBeenCalledWith("/api/functional-knowledge/content-rules", expect.objectContaining({ method: "POST" }));
  });

  it("reads and rebuilds a local graph projection without treating it as a source of truth", async () => {
    const projection = {
      projection_code: "GRAPH-001", revision_number: 1, status: "completed", ontology_version: "knowledge-lineage.v1",
      source_watermark: { source_fingerprint: "a".repeat(64), node_count: 2, edge_count: 1 },
      current_source_watermark: { source_fingerprint: "a".repeat(64), node_count: 2, edge_count: 1 },
      snapshot_fingerprint_sha256: "b".repeat(64), node_count: 2, edge_count: 1, is_stale: false,
      nodes: [{ node_type: "source_evidence", node_code: "EVIDENCE-001", revision_number: 0, status: "approved", properties: {}, source_fingerprint_sha256: "c".repeat(64) }],
      edges: [{ source_node_type: "source_evidence", source_node_code: "EVIDENCE-001", source_revision_number: 0, target_node_type: "fact_claim", target_node_code: "CLAIM-001", target_revision_number: 0, relationship_type: "SUPPORTS", assertion_kind: "recorded_fact", evidence: {} }],
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(null))
      .mockResolvedValueOnce(response(projection, 201));
    vi.stubGlobal("fetch", fetch);

    expect(await knowledgeApi.currentGraphProjection()).toBeNull();
    const rebuilt = await knowledgeApi.rebuildGraphProjection("graph_operator");

    expect(rebuilt).toMatchObject({ projectionCode: "GRAPH-001", nodeCount: 2, edges: [{ relationshipType: "SUPPORTS", assertionKind: "recorded_fact" }] });
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/functional-knowledge/graph-projections/current", expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/functional-knowledge/graph-projections/rebuild", expect.objectContaining({ method: "POST", body: JSON.stringify({ actor: "graph_operator" }) }));
  });

  it("maps a scoped graph lineage search", async () => {
    const asset = { node_type: "asset", node_code: "ASSET-001", revision_number: 0, status: "ready", properties: { title: "Product image" }, source_fingerprint_sha256: "a".repeat(64) };
    const fetch = vi.fn().mockResolvedValue(response({
      query: "Product", scope: "material", projection_code: "GRAPH-001", projection_revision: 2, is_stale: false,
      results: [{ match: asset, nodes: [asset], edges: [], truncated: false }],
    }));
    vi.stubGlobal("fetch", fetch);

    const result = await knowledgeApi.searchGraphLineage("Product", "material");

    expect(result).toMatchObject({ projectionCode: "GRAPH-001", scope: "material", results: [{ match: { nodeCode: "ASSET-001" }, truncated: false }] });
    expect(fetch).toHaveBeenCalledWith("/api/functional-knowledge/graph-search?q=Product&scope=material", expect.any(Object));
  });
});
