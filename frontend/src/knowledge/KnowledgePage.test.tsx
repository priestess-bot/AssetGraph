import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
});
