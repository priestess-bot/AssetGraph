import { beforeEach, describe, expect, it, vi } from "vitest";
import { contentProjectsApi } from "./api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("content projects api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("creates an expected-revision input patch instead of mutating a project in place", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "修订后的直播", revision_number: 2, status: "draft", generation_goal: "更新后的目标",
      updated_at: "2026-07-25T00:00:00Z", content: { theme: "夏日聚会", must_include: ["真实场景"] }, generated: false,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.update("CONTENT-001", {
      expected_revision: 1, title: "修订后的直播", generation_goal: "更新后的目标", must_include: ["真实场景"], visual_requirements: ["产品置于桌面"],
    });

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/content-projects/CONTENT-001");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 1, title: "修订后的直播", generation_goal: "更新后的目标", must_include: ["真实场景"], visual_requirements: ["产品置于桌面"] });
    expect(detail).toMatchObject({ revisionNumber: 2, status: "draft", generationGoal: "更新后的目标" });
  });
});
