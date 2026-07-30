import { describe, expect, it } from "vitest";
import { knowledgeText, knowledgeTextList, knowledgeTitle } from "./presentation";

describe("knowledge presentation", () => {
  it("presents legacy fact fixtures as readable Chinese", () => {
    expect(knowledgeTitle("Compatibility fact")).toBe("基础商品事实");
    expect(knowledgeTitle("Lineage fact 894d59bb2fa84b63a713a8cb572a20a7")).toBe("可追溯商品事实");
    expect(knowledgeTitle("UI 验收来源-1785262291471")).toBe("界面验收来源");
  });

  it("localizes known fixture content without changing ordinary Chinese copy", () => {
    expect(knowledgeText("The product has a verified 12-month warranty.")).toBe("该商品已核验的质保期为 12 个月。");
    expect(knowledgeTextList(["The replacement fact.", "库存充足，适合本周活动。"]))
      .toEqual(["这是更新后的已核验事实。", "库存充足，适合本周活动。"]);
  });
});
