import { describe, expect, it } from "vitest";
import { LEGACY_ROUTE_MAP, PRODUCT_ROUTES, productPageTitle, routeIsActive } from "./routes";

describe("product routes", () => {
  it("defines exactly the seven customer-facing workspaces", () => {
    expect(PRODUCT_ROUTES.map((item) => item.label)).toEqual(["业务概览", "素材库", "直播模板", "知识库", "内容项目", "运营分析", "效果学习"]);
  });

  it("matches nested product routes and normalizes supported legacy deep links", () => {
    const projects = PRODUCT_ROUTES.find((item) => item.path === "/projects")!;
    expect(routeIsActive("/projects/active", projects)).toBe(true);
    expect(productPageTitle("/production/live-rooms")).toBe("内容项目");
    expect(LEGACY_ROUTE_MAP).toContainEqual(["/content/projects", "/projects"]);
  });
});
