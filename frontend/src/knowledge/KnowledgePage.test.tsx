import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { KnowledgePage } from "./KnowledgePage";

const card = {
  fact_card_code: "MT-FACT-001",
  title: "Product facts",
  status: "active",
  current_approved_version: 1,
  versions: [
    {
      version_code: "MT-FACT-001-V001",
      version_number: 1,
      status: "approved",
      content: {
        product_name: "Product",
        positioning: "Daily use",
        verified_facts: ["Approved fact"],
      },
    },
  ],
};

describe("KnowledgePage", () => {
  it("shows the exact revision usage lineage for the selected fact card", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/maitu/workbench/product-fact-cards") {
        return new Response(JSON.stringify([card]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/maitu/workbench/product-fact-cards/MT-FACT-001/versions/1/usage") {
        return new Response(JSON.stringify([{
          relation_type: "uses_fact_card",
          object_type: "content_project",
          object_code: "CONTENT-001",
          revision_number: 2,
          status: "confirmed",
          created_at: "2026-07-25T00:00:00Z",
        }]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    expect(await screen.findByText(/CONTENT-001 · r2/)).toBeInTheDocument();
    expect(screen.getByText("uses_fact_card")).toBeInTheDocument();
  });

  it("rebuilds and displays the local relation projection explicitly", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    let rebuilt = false;
    const projection = {
      projection_code: "GRAPH-001", revision_number: 1, status: "completed", ontology_version: "knowledge-lineage.v1",
      source_watermark: { source_fingerprint: "a".repeat(64), node_count: 2, edge_count: 1 },
      current_source_watermark: { source_fingerprint: "a".repeat(64), node_count: 2, edge_count: 1 },
      snapshot_fingerprint_sha256: "b".repeat(64), node_count: 2, edge_count: 1, is_stale: false,
      created_at: "2026-07-25T00:00:00Z",
      nodes: [{ node_type: "source_evidence", node_code: "EVIDENCE-001", revision_number: 0, status: "approved", properties: {}, source_fingerprint_sha256: "c".repeat(64) }],
      edges: [{ source_node_type: "source_evidence", source_node_code: "EVIDENCE-001", source_revision_number: 0, target_node_type: "fact_claim", target_node_code: "CLAIM-001", target_revision_number: 0, relationship_type: "SUPPORTS", assertion_kind: "recorded_fact", evidence: {} }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/graph-projections/current") return new Response(JSON.stringify(rebuilt ? projection : null), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/graph-projections/rebuild" && init?.method === "POST") { rebuilt = true; return new Response(JSON.stringify(projection), { status: 201, headers: { "Content-Type": "application/json" } }); }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "关系图谱" }));
    expect(await screen.findByText("尚未构建关系投影")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重建本地关系投影" }));

    expect(await screen.findByRole("heading", { name: "投影快照" })).toBeInTheDocument();
    expect(screen.getAllByText(/EVIDENCE-001/)).toHaveLength(2);
    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-knowledge/graph-projections/rebuild" && request.init?.method === "POST")).toBe(true));
  });

  it("registers local source evidence before creating a fact claim", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences" && init?.method !== "POST") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences" && init?.method === "POST") return new Response(JSON.stringify({
        evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", source_url: null, excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", status: "draft", created_by: "console_operator", created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
      }), { status: 201, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "来源证据" }));
    await screen.findByRole("heading", { name: "来源证据" });
    await user.type(screen.getByLabelText("来源标题"), "Product sheet");
    await user.type(screen.getByLabelText("可引用摘录"), "Verified warranty is 12 months.");
    await user.click(screen.getByRole("button", { name: "登记来源草稿" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-knowledge/source-evidences" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-knowledge/source-evidences" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({ source_type: "document", title: "Product sheet", excerpt: "Verified warranty is 12 months.", access_scope: "internal", extractor_strategy_ref: "manual_excerpt.v1" });
  });

  it("shows revalidation state separately from authorization in knowledge search", async () => {
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input); requests.push(url);
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/search?q=price&platform=douyin") return new Response(JSON.stringify([{
        entity_type: "content_rule", entity_code: "RULE-001", title: "No unsupported price claim", summary: "Do not promise an unverified price.", status: "approved",
        source_evidence_code: "EVIDENCE-001", source_status: "approved", scope: { platforms: ["douyin"] },
        validation: { lifecycle: "approved", source: "approved", validity: "valid", scope: "match", rights: "not_modeled", content_eligible: true, authorization_eligible: false, blocking_rule_codes: [] },
        created_at: "2026-07-25T00:00:00Z",
      }]), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "知识检索" }));
    await screen.findByRole("heading", { name: "知识检索" });
    await user.type(screen.getByLabelText("检索词"), "price");
    await user.type(screen.getByLabelText("平台上下文"), "douyin");
    await user.click(screen.getByRole("button", { name: "查询" }));

    expect(await screen.findByText("No unsupported price claim")).toBeInTheDocument();
    expect(screen.getByText("引用检查：通过 · 授权：待审")).toBeInTheDocument();
    expect(requests).toContain("/api/functional-knowledge/search?q=price&platform=douyin");
  });

  it("opens the fixed content usage chain for a fact claim", async () => {
    const claim = {
      claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty",
      source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved",
      claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.",
      status: "approved", fingerprint_sha256: "b".repeat(64),
      created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims") return new Response(JSON.stringify([claim]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims/CLAIM-001/lineage") return new Response(JSON.stringify({
        claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty",
        claim_status: "approved", fact_status: "approved",
        source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved",
        uses: [{ relation_type: "pins_fact_claim", object_type: "content_project", object_code: "CONTENT-001", revision_number: 2, status: "confirmed", created_at: "2026-07-25T00:00:00Z" }],
      }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "来源证据" }));
    await screen.findByText("Warranty is 12 months.");
    await user.click(screen.getByRole("button", { name: "查看使用链" }));

    expect(await screen.findByRole("heading", { name: "声明使用链" })).toBeInTheDocument();
    expect(screen.getByText(/CONTENT-001 · r2/)).toBeInTheDocument();
    expect(screen.getByText("pins_fact_claim")).toBeInTheDocument();
  });

  it("keeps content rules in a workspace separate from product facts", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/content-rules") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "内容规则" }));

    expect(await screen.findByRole("heading", { name: "内容规则" })).toBeInTheDocument();
    expect(screen.getByText("尚无内容规则")).toBeInTheDocument();
  });

  it("revokes approved local evidence with an explicit reason", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const approvedSource = {
      evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", source_url: null, excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", extractor_strategy_ref: "manual_excerpt.v1", extraction_metadata: {}, extraction_runs: [{ extraction_run_code: "EXTRACT-001", evidence_code: "EVIDENCE-001", extractor_strategy_ref: "manual_excerpt.v1", input_fingerprint_sha256: "a".repeat(64), output_checksum_sha256: "c".repeat(64), extraction_metadata: {}, created_at: "2026-07-25T00:00:00Z" }], status: "approved", created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences" && init?.method !== "POST") return new Response(JSON.stringify([approvedSource]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences/EVIDENCE-001/revoke") return new Response(JSON.stringify({ ...approvedSource, status: "revoked", revoked_by: "console_reviewer", revoked_at: "2026-07-25T01:00:00Z", revoked_reason: "The source was corrected." }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "来源证据" }));
    await screen.findByRole("heading", { name: "来源证据" });
    expect(await screen.findByText("抽取：manual_excerpt.v1 · 1 次")).toBeInTheDocument();
    expect(screen.getByText("输出 checksum：cccccccccccc")).toBeInTheDocument();
    await user.type(screen.getByLabelText("EVIDENCE-001 撤销原因"), "The source was corrected.");
    await user.click(screen.getByRole("button", { name: "撤销来源" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-knowledge/source-evidences/EVIDENCE-001/revoke")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-knowledge/source-evidences/EVIDENCE-001/revoke");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ actor: "console_reviewer", reason: "The source was corrected." });
  });

  it("rejects draft local evidence with an explicit reason", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const draftSource = {
      evidence_code: "EVIDENCE-001", source_type: "document", title: "Draft product sheet", source_url: null, excerpt: "Warranty wording is incomplete.", content_sha256: "a".repeat(64), access_scope: "internal", status: "draft", created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences" && init?.method !== "POST") return new Response(JSON.stringify([draftSource]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences/EVIDENCE-001/reject") return new Response(JSON.stringify({ ...draftSource, status: "rejected", rejected_by: "console_reviewer", rejected_at: "2026-07-25T01:00:00Z", rejection_reason: "The document is incomplete." }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "来源证据" }));
    await screen.findByRole("heading", { name: "来源证据" });
    await user.type(screen.getByLabelText("EVIDENCE-001 驳回原因"), "The document is incomplete.");
    await user.click(screen.getByRole("button", { name: "驳回来源" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-knowledge/source-evidences/EVIDENCE-001/reject")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-knowledge/source-evidences/EVIDENCE-001/reject");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ actor: "console_reviewer", reason: "The document is incomplete." });
  });

  it("submits a searchable fact claim with its explicit validity window", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const approvedSource = {
      evidence_code: "EVIDENCE-001", source_type: "document", title: "Product sheet", source_url: null, excerpt: "Verified warranty is 12 months.", content_sha256: "a".repeat(64), access_scope: "internal", status: "approved", created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/maitu/workbench/product-fact-cards") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/source-evidences" && init?.method !== "POST") return new Response(JSON.stringify([approvedSource]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims" && init?.method !== "POST") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-knowledge/fact-claims" && init?.method === "POST") return new Response(JSON.stringify({
        claim_code: "CLAIM-001", fact_code: "FACT-001", fact_title: "Warranty", source_evidence_code: "EVIDENCE-001", source_title: "Product sheet", source_status: "approved", claim: "Warranty is 12 months.", citation_excerpt: "Verified warranty is 12 months.", valid_from: "2026-07-25T00:00:00Z", valid_until: "2026-12-31T23:59:59Z", status: "draft", fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
      }), { status: 201, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><KnowledgePage /></QueryClientProvider>);

    await screen.findByText("尚无事实卡");
    await user.click(screen.getByRole("button", { name: "来源证据" }));
    await screen.findByRole("heading", { name: "来源证据" });
    await user.type(screen.getByLabelText("事实标题"), "Warranty");
    await user.selectOptions(screen.getByLabelText("批准来源"), "EVIDENCE-001");
    await user.type(screen.getByLabelText("事实声明"), "Warranty is 12 months.");
    await user.clear(screen.getByLabelText("引用摘录"));
    await user.type(screen.getByLabelText("引用摘录"), "Verified warranty is 12 months.");
    await user.type(screen.getByLabelText("有效开始时间 (UTC)"), "2026-07-25T00:00:00Z");
    await user.type(screen.getByLabelText("有效结束时间 (UTC)"), "2026-12-31T23:59:59Z");
    await user.click(screen.getByRole("button", { name: "创建事实声明" }));

    await waitFor(() => expect(requests.some((request) => request.url === "/api/functional-knowledge/fact-claims" && request.init?.method === "POST")).toBe(true));
    const request = requests.find((item) => item.url === "/api/functional-knowledge/fact-claims" && item.init?.method === "POST");
    expect(JSON.parse(String(request?.init?.body))).toMatchObject({
      source_evidence_code: "EVIDENCE-001",
      valid_from: "2026-07-25T00:00:00Z",
      valid_until: "2026-12-31T23:59:59Z",
    });
  });
});
