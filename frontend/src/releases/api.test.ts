import { beforeEach, describe, expect, it, vi } from "vitest";
import { releasesApi } from "./api";

describe("releases api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("adds an encoded project filter when listing releases", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await releasesApi.list(" CONTENT/001 ");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/releases?project_code=CONTENT%2F001");
  });

  it("keeps the unfiltered release endpoint for the global console", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await releasesApi.list();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/releases");
  });

});
