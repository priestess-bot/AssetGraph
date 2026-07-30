import { describe, expect, it } from "vitest";
import { containsInternalToken, problemPresentation, productCopy, productLabel, productTitle } from "./productLanguage";

describe("product language boundary", () => {
  it("maps registered backend values to business Chinese", () => {
    expect(productLabel("waiting_human")).toBe("等待人工处理");
    expect(productLabel("reference_only")).toBe("仅供参考");
    expect(productLabel("operator", "运营人员")).toBe("运营人员");
  });

  it("never echoes unknown internal values", () => {
    expect(productLabel("LINEAGE_INPUT_STALE")).toBe("待确认");
    expect(productLabel("ALERT-LINEAGE-009", "业务提醒")).toBe("业务提醒");
    expect(productLabel("some_new_backend_state", "处理中")).toBe("处理中");
  });

  it("removes embedded internal codes without state leaking between calls", () => {
    expect(productCopy("LINEAGE_INPUT_STALE 项目内容已更新", "请重试")).toBe("项目内容已更新");
    expect(productCopy("ALERT-LINEAGE-009 项目内容已更新", "请重试")).toBe("项目内容已更新");
    expect(containsInternalToken("ALERT-LINEAGE-009")).toBe(true);
    expect(containsInternalToken("ALERT-LINEAGE-009")).toBe(true);
  });

  it("cleans technical suffixes from names shown to operators", () => {
    expect(productTitle("Single room strategy 843165ae04cc4faea6eaf1587b74b974")).toBe("Single room strategy");
    expect(productTitle("promotion_text 2c8d424f10be4e6a924faf0d1671c9ad")).toBe("促销文案");
    expect(productTitle("ALERT-LINEAGE-009", "业务提醒")).toBe("业务提醒");
  });

  it("presents known and unknown problems without exposing codes", () => {
    expect(problemPresentation({ code: "LINEAGE_INPUT_STALE" })).toEqual({
      title: "项目使用的内容已有更新",
      impact: "继续操作可能会使用旧版本素材或内容。",
      nextStep: "请查看最新内容并确认是否更新当前项目。",
    });
    const fallback = problemPresentation({ code: "ALERT-LINEAGE-009", state: "error" });
    expect(JSON.stringify(fallback)).not.toContain("ALERT-LINEAGE-009");
  });
});
