import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeliveryProductPanel } from "./DeliveryProductPanel";

function summary(releaseCode: string, carrierKind = "rendered_video") {
  return {
    release_code: releaseCode,
    subject_type: "production_variant",
    subject_code: `VARIANT-${releaseCode}`,
    subject_revision: 1,
    carrier_kind: carrierKind,
    status: "candidate",
    manifest_code: `MANIFEST-${releaseCode}`,
    manifest_fingerprint: "a".repeat(64),
    delivery_count: 0,
    created_at: "2026-08-09T00:00:00Z",
    updated_at: "2026-08-09T00:00:00Z",
  };
}

function detail(releaseCode: string) {
  return {
    ...summary(releaseCode),
    release_fingerprint: "b".repeat(64),
    manifest: {
      manifest_code: `MANIFEST-${releaseCode}`,
      revision_number: 1,
      manifest_fingerprint: "a".repeat(64),
      subject_refs: {},
      artifact_refs: [{ artifact_code: `ARTIFACT-${releaseCode}` }],
      rights_snapshot: { status: "valid" },
      quality_snapshot: { gates: [] },
      lineage_snapshot: { complete: true },
      carrier_facet: {},
    },
    approvals: [],
    deliveries: [],
  };
}

function renderPanel(search: string, projectCode: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DeliveryProductPanel search={search} projectCode={projectCode} />
    </QueryClientProvider>,
  );
}

describe("project delivery panel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("keeps the requested release selected inside the project-scoped list", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/releases?project_code=CONTENT-001") {
        return new Response(JSON.stringify([summary("RELEASE-001"), summary("RELEASE-002")]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/releases/RELEASE-002") {
        return new Response(JSON.stringify({ ...detail("RELEASE-002"), status: "awaiting_approval" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    renderPanel("?release=RELEASE-002", "CONTENT-001");

    await waitFor(() => expect(calls).toContain("/api/releases/RELEASE-002"));
    expect(await screen.findByRole("heading", { name: "连接审核权限" })).toBeInTheDocument();
    expect(calls).not.toContain("/api/releases/RELEASE-001");
    expect(calls).not.toContain("/api/releases");
  });

  it("falls back only to the first release returned for the project", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/releases?project_code=CONTENT-001") {
        return new Response(JSON.stringify([summary("RELEASE-001")]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/releases/RELEASE-001") {
        return new Response(JSON.stringify(detail("RELEASE-001")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    renderPanel("?release=RELEASE-OTHER-PROJECT", "CONTENT-001");

    await waitFor(() => expect(calls).toContain("/api/releases/RELEASE-001"));
    expect(calls).not.toContain("/api/releases/RELEASE-OTHER-PROJECT");
    expect(calls).not.toContain("/api/releases");
  });
});
