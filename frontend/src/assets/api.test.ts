import { beforeEach, describe, expect, it, vi } from "vitest";
import { assetLibraryApi } from "./api";

describe("asset library api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("keeps global, display and local file identifiers in the list projection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([{
      asset_code: "AG-IMG-20260729-000002",
      display_code: "MT-IMG-0002",
      local_file_code: "IMG-LOCAL-0002",
      title: "酒庄背景",
      original_filename: "winery.png",
      asset_type: "IMG",
      media_kind: "image",
      material_roles: ["background"],
      execution_capability: "local_only",
      rights_status: "approved",
    }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const [asset] = await assetLibraryApi.listAssets();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/assets?limit=500");
    expect(asset).toMatchObject({
      assetCode: "AG-IMG-20260729-000002",
      displayCode: "MT-IMG-0002",
      localFileCode: "IMG-LOCAL-0002",
    });
  });
});
