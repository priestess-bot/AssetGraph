import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AssetLibraryPage } from "./AssetLibraryPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><AssetLibraryPage /></QueryClientProvider>);
}

describe("AssetLibraryPage", () => {
  it("updates independent group membership and retains multi-membership semantics", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/assets") return response([{ asset_code: "AG-IMG-001", title: "主图", original_filename: "main.png", asset_type: "IMG", material_roles: ["background"], execution_capability: "maitu_bound" }]);
      if (url === "/api/assets/groups") return response([{ group_code: "AG-GRP-001", title: "主素材组", asset_codes: ["AG-IMG-001"], asset_count: 1, created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/material-packs" || url === "/api/assets/gaps") return response([]);
      if (url === "/api/assets/groups/AG-GRP-001/members" && init?.method === "PUT") return response({ group_code: "AG-GRP-001", title: "主素材组", asset_codes: [], asset_count: 0, created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "分组" }));
    const member = await screen.findByRole("checkbox", { name: /主图/ });
    expect(member).toBeChecked();
    await user.click(member);
    await user.click(screen.getByRole("button", { name: "更新成员" }));

    expect(fetch).toHaveBeenCalledWith("/api/assets/groups/AG-GRP-001/members", expect.objectContaining({ method: "PUT", body: JSON.stringify({ asset_codes: [] }) }));
  });

  it("submits material-pack occurrence constraints", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/assets") return response([]);
      if (url === "/api/assets/groups") return response([{ group_code: "AG-GRP-001", title: "主素材组", asset_codes: [], asset_count: 0, created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/material-packs" && init?.method === "POST") return response({ pack_code: "AG-PACK-001", title: "主场景素材包", role: "background", revision_number: 1, status: "draft", fingerprint_sha256: "a".repeat(64), entries: [], resolved_asset_codes: [], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" });
      if (url === "/api/assets/material-packs" || url === "/api/assets/gaps") return response([]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "素材包" }));
    await user.type(screen.getByLabelText("素材包名称"), "主场景素材包");
    await user.type(screen.getByPlaceholderText("AG-GRP-*"), "AG-GRP-001");
    const usageMode = screen.getAllByRole("combobox").find((element) => Array.from((element as HTMLSelectElement).options).some((option) => option.value === "required"));
    expect(usageMode).toBeDefined();
    await user.selectOptions(usageMode!, "required");
    await user.clear(screen.getByLabelText("最少出现次数"));
    await user.type(screen.getByLabelText("最少出现次数"), "2");
    await user.type(screen.getByLabelText("最多出现次数"), "3");
    await user.click(screen.getByRole("button", { name: "添加条目" }));
    expect(screen.getByText(/background · required · 2 至 3 次/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "创建素材包" }));

    const request = requests.find((item) => item.url === "/api/assets/material-packs" && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({ title: "主场景素材包", pack_kind: "classification", role: "background", entries: [{ selection_kind: "group", selection_code: "AG-GRP-001", material_role: "background", mode: "required", min_occurrences: 2, max_occurrences: 3, applicable_scope: { kind: "whole_room", scene_types: [], scene_codes: [] }, pack_constraints: [] }], exclusive_roles: [] }));
  });

  it("writes a table-surface constraint through structured normalized fields", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/assets") return response([{ asset_code: "AG-IMG-001", title: "餐桌背景", original_filename: "table.png", asset_type: "IMG", material_roles: ["background"], execution_capability: "maitu_bound" }]);
      if (url === "/api/assets/groups" || url === "/api/assets/material-packs" || url === "/api/assets/gaps") return response([]);
      if (url === "/api/assets/AG-IMG-001/constraint-profile/revisions" && !init?.method) return response([{ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/AG-IMG-001/constraint-profile" && !init?.method) return response({ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-25T00:00:00Z" });
      if (url === "/api/assets/AG-IMG-001/constraint-profile" && init?.method === "POST") return response({ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 2, constraints: [], fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z" });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("位置与图层约束");
    expect(await screen.findByText("约束修订历史")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "添加约束" }));
    await user.selectOptions(screen.getByLabelText("约束类型"), "table_surface");
    expect(screen.getByLabelText("归一化区域预览")).toBeInTheDocument();
    expect(screen.getByLabelText("约束参数：承载商品角色")).toHaveValue("product_display");
    await user.click(screen.getByRole("button", { name: "保存新修订" }));

    const request = requests.find((item) => item.url === "/api/assets/AG-IMG-001/constraint-profile" && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({ constraints: [{ kind: "table_surface", hard: true, parameters: { name: "table_surface", x: 0.1, y: 0.58, width: 0.8, height: 0.28, product_role: "product_display", product_anchor: "bottom_center" } }] }));
  });

  it("creates a new draft revision from an immutable material-pack revision", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const pack = { pack_code: "AG-PACK-001", title: "背景素材包", role: "background", revision_number: 1, status: "published", fingerprint_sha256: "a".repeat(64), entries: [{ selection_kind: "group", selection_code: "AG-GRP-001", mode: "required", min_occurrences: 1, max_occurrences: null }], resolved_asset_codes: ["AG-IMG-001"], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/assets" || url === "/api/assets/groups" || url === "/api/assets/gaps") return response([]);
      if (url === "/api/assets/material-packs" && !init?.method) return response([pack]);
      if (url === "/api/assets/material-packs/AG-PACK-001/revisions" && !init?.method) return response([{ revision_number: 1, entries: pack.entries, fingerprint_sha256: pack.fingerprint_sha256, created_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/material-packs/AG-PACK-001/revisions" && init?.method === "POST") return response({ ...pack, revision_number: 2, status: "draft", fingerprint_sha256: "b".repeat(64) });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "素材包" }));
    await screen.findByText("创建素材包新修订");
    expect(screen.getByText("修订历史")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "创建 r2" }));

    const request = requests.find((item) => item.url === "/api/assets/material-packs/AG-PACK-001/revisions" && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({ expected_revision: 1, entries: [{ selection_kind: "group", selection_code: "AG-GRP-001", mode: "required", min_occurrences: 1, applicable_scope: { kind: "whole_room", scene_types: [], scene_codes: [] }, pack_constraints: [] }] }));
  });

  it("shows structured additions and removals against the prior material-pack revision", async () => {
    const pack = { pack_code: "AG-PACK-001", title: "背景素材包", role: "background", revision_number: 2, status: "draft", fingerprint_sha256: "b".repeat(64), entries: [{ selection_kind: "asset", selection_code: "AG-IMG-002", mode: "optional", min_occurrences: 0, max_occurrences: null }], resolved_asset_codes: ["AG-IMG-002"], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/assets" || url === "/api/assets/groups" || url === "/api/assets/gaps") return response([]);
      if (url === "/api/assets/material-packs" && !init?.method) return response([pack]);
      if (url === "/api/assets/material-packs/AG-PACK-001/revisions" && !init?.method) return response([
        { revision_number: 2, entries: pack.entries, fingerprint_sha256: pack.fingerprint_sha256, created_at: "2026-07-25T00:00:00Z" },
        { revision_number: 1, entries: [{ selection_kind: "group", selection_code: "AG-GRP-001", mode: "required", min_occurrences: 1, max_occurrences: null }], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-24T00:00:00Z" },
      ]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "素材包" }));
    expect(await screen.findByText("与 r1 差异")).toBeInTheDocument();
    expect(screen.getByText(/新增：optional:asset:AG-IMG-002/)).toBeInTheDocument();
    expect(screen.getByText(/移除：required:group:AG-GRP-001/)).toBeInTheDocument();
  });

  it("batch-corrects selected unclassified assets through the explicit three-axis contract", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const assets = [
      { asset_code: "AG-IMG-001", title: "主图", original_filename: "main.png", asset_type: "IMG", material_roles: [], execution_capability: "unclassified" },
      { asset_code: "AG-IMG-002", title: "商品图", original_filename: "product.png", asset_type: "IMG", material_roles: [], execution_capability: "unclassified" },
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/assets" || url === "/api/assets/groups" || url === "/api/assets/material-packs" || url === "/api/assets/gaps") return response(url === "/api/assets" ? assets : []);
      if (url === "/api/assets/AG-IMG-001/constraint-profile/revisions" && !init?.method) return response([{ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/AG-IMG-001/constraint-profile" && !init?.method) return response({ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-25T00:00:00Z" });
      if (url === "/api/assets/batch-classification") return response(assets.map((asset) => ({ ...asset, media_kind: "image", material_roles: ["background"], execution_capability: "local_only", id: `id-${asset.asset_code}` })));
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    const targets = await screen.findByLabelText("待校正素材");
    await user.selectOptions(targets, ["AG-IMG-001", "AG-IMG-002"]);
    await user.selectOptions(screen.getAllByLabelText("媒体类型")[0]!, "image");
    await user.selectOptions(screen.getAllByLabelText("执行能力")[0]!, "local_only");
    await user.click(screen.getAllByRole("checkbox", { name: "background" })[0]!);
    await user.click(screen.getByRole("button", { name: "校正 2 个素材" }));

    const request = requests.find((item) => item.url === "/api/assets/batch-classification");
    expect(request?.init?.method).toBe("PATCH");
    expect(request?.init?.body).toBe(JSON.stringify({ asset_codes: ["AG-IMG-001", "AG-IMG-002"], media_kind: "image", material_roles: ["background"], execution_capability: "local_only" }));
  });

  it("marks an obsolete gap with an explicit reason while preserving its event evidence", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const gap = { gap_code: "AG-GAP-001", title: "已不适用背景", role: "background", severity: "medium", status: "open", gap_type: "material_missing", specification: {}, source_context: {}, alternative_asset_codes: [], resolution_snapshot: {}, resolution_evidence: {}, events: [{ event_code: "AG-GAP-EVT-001", status: "open" }], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/assets" || url === "/api/assets/groups" || url === "/api/assets/material-packs") return response([]);
      if (url === "/api/assets/gaps" && !init?.method) return response([gap]);
      if (url === "/api/assets/gaps/AG-GAP-001" && init?.method === "PATCH") return response({ ...gap, status: "obsolete", resolution_evidence: { obsolete_reason: "Campaign scope changed." }, events: [...gap.events, { event_code: "AG-GAP-EVT-002", previous_status: "open", status: "obsolete" }] });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "缺口" }));
    await user.type(screen.getByLabelText("AG-GAP-001 过时原因"), "Campaign scope changed.");
    await user.click(screen.getByRole("button", { name: "标记过时" }));

    const request = requests.find((item) => item.url === "/api/assets/gaps/AG-GAP-001" && item.init?.method === "PATCH");
    expect(JSON.parse(String(request?.init?.body))).toEqual({ status: "obsolete", resolution_evidence: { obsolete_reason: "Campaign scope changed." }, actor: "material_library" });
  });

  it("shows constraint revision differences without replacing the current Profile", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/assets") return response([{ asset_code: "AG-IMG-001", title: "餐桌背景", original_filename: "table.png", asset_type: "IMG", material_roles: ["background"], execution_capability: "maitu_bound" }]);
      if (url === "/api/assets/groups" || url === "/api/assets/material-packs" || url === "/api/assets/gaps") return response([]);
      if (url === "/api/assets/AG-IMG-001/constraint-profile" && !init?.method) return response({ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 2, constraints: [{ kind: "table_surface", hard: true, parameters: { name: "table_surface" } }], fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z" });
      if (url === "/api/assets/AG-IMG-001/constraint-profile/revisions" && !init?.method) return response([
        { profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 2, constraints: [{ kind: "table_surface", hard: true, parameters: { name: "table_surface" } }], fingerprint_sha256: "b".repeat(64), created_at: "2026-07-25T00:00:00Z" },
        { profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [{ kind: "preserve_aspect_ratio", hard: true, parameters: {} }], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-24T00:00:00Z" },
      ]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    renderPage();

    expect(await screen.findByText("约束修订历史")).toBeInTheDocument();
    expect(screen.getByText(/r2 · 当前/)).toBeInTheDocument();
    expect(screen.getByText(/与 r1 差异：新增 桌面摆放区域/)).toBeInTheDocument();
    expect(screen.getByText(/移除 保持等比例/)).toBeInTheDocument();
  });

  it("shows local material relationships and withholds automatic recommendation without effect samples", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/assets") return response([{ asset_code: "AG-IMG-001", title: "主背景", original_filename: "main.png", asset_type: "IMG", material_roles: ["background"], execution_capability: "maitu_bound" }]);
      if (url === "/api/assets/groups") return response([{ group_code: "AG-GRP-001", title: "主场景组", asset_codes: ["AG-IMG-001"], asset_count: 1, created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/material-packs") return response([{ pack_code: "AG-PACK-001", title: "主背景包", pack_kind: "classification", role: "background", revision_number: 2, published_revision_number: 1, status: "draft", revision_status: "draft", fingerprint_sha256: "a".repeat(64), entries: [], resolved_asset_codes: ["AG-IMG-001"], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z" }]);
      if (url === "/api/assets/gaps") return response([{ gap_code: "AG-GAP-001", title: "背景缺口", role: "background", severity: "medium", status: "candidate_found", gap_type: "material_missing", alternative_asset_codes: ["AG-IMG-001"], resolution_snapshot: {}, resolution_evidence: {}, events: [] }]);
      if (url === "/api/assets/AG-IMG-001/constraint-profile") return response({ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-25T00:00:00Z" });
      if (url === "/api/assets/AG-IMG-001/constraint-profile/revisions") return response([{ profile_code: "AG-CP-001", asset_code: "AG-IMG-001", revision_number: 1, constraints: [], fingerprint_sha256: "a".repeat(64), created_at: "2026-07-25T00:00:00Z" }]);
      throw new Error(`Unexpected request: ${url}`);
    }));
    renderPage();

    expect(await screen.findByText("效果与关系")).toBeInTheDocument();
    expect(screen.getByText("样本不足")).toBeInTheDocument();
    expect(screen.getByText("主场景组")).toBeInTheDocument();
    expect(screen.getByText("主背景包")).toBeInTheDocument();
    expect(screen.getByText("背景缺口")).toBeInTheDocument();
  });
});
