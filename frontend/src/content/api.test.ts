import { beforeEach, describe, expect, it, vi } from "vitest";
import { contentProjectsApi } from "./api";
import { recommendContentTemplates } from "./ContentProjectsPage";
import type { RoomTemplate } from "../live-research/types";

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

  it("updates fact card selections in their own revision patch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      project_code: "CONTENT-001", title: "选酒直播", revision_number: 3, status: "draft", generation_goal: "帮助观众选酒",
      updated_at: "2026-07-25T00:00:00Z", content: { fact_card_codes: ["FACT-WINE"] }, generated: false,
      fact_cards: [{ fact_card_code: "FACT-WINE", version_number: 4, version_code: "FACT-WINE-V4", content_sha256: "sha256" }],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const detail = await contentProjectsApi.update("CONTENT-001", { expected_revision: 2, fact_card_codes: ["FACT-WINE"] });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 2, fact_card_codes: ["FACT-WINE"] });
    expect(detail.factCards).toEqual([{ fact_card_code: "FACT-WINE", version_number: 4, version_code: "FACT-WINE-V4", content_sha256: "sha256" }]);
  });

  it("ranks content strategies only from explicit category, module, and compatibility matches", () => {
    const template = (code: string, category: string, title: string, compatibilityTags: string[]): RoomTemplate => ({
      template_code: code, title: code, source_session_code: "CAP-001", source_type: "external_flat_video", templateKind: "content_strategy", latest_revision: 1, published_revision: 1, status: "published", layout_fidelity: "none", buildability: "reference_only", contentReadiness: "ready", scenes: [],
      contentStrategy: { targetCategory: category, compatibilityTags, programOutline: [{ moduleKey: "opening", title, purpose: "建立选择目标", startMs: 0, endMs: 30_000 }], materialCues: [], reviewedExamples: [] },
    });

    const recommendations = recommendContentTemplates([template("TPL-WINE", "葡萄酒", "聚会开场", ["聚会"]), template("TPL-CARE", "护肤", "日常护理", ["护肤"])], "为聚会挑选葡萄酒，并用聚会开场建立目标");

    expect(recommendations[0]).toMatchObject({ templateCode: "TPL-WINE", score: 132, signals: ["品类：葡萄酒", "模块：聚会开场", "标签：聚会"] });
    expect(recommendations).toHaveLength(1);
  });
});
