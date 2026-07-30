import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyBlock, LoadingBlock, operationalTone, ProblemNotice } from "./components";


describe("operational problem presentation", () => {
  it("renders explicit loading and empty states instead of a blank workspace", () => {
    const { rerender } = render(<LoadingBlock label="正在读取素材" />);
    expect(screen.getByText("正在读取素材")).toBeInTheDocument();

    rerender(<EmptyBlock title="尚无匹配素材" detail="调整筛选条件后重试。" />);
    expect(screen.getByText("尚无匹配素材")).toBeInTheDocument();
    expect(screen.getByText("调整筛选条件后重试。")).toBeInTheDocument();
    expect(screen.queryByText("正在读取素材")).not.toBeInTheDocument();
  });

  it("never maps warning, stale, insufficient data, or reconciliation to success", () => {
    expect(operationalTone("warning")).toBe("warning");
    expect(operationalTone("stale")).toBe("warning");
    expect(operationalTone("insufficient_data")).toBe("info");
    expect(operationalTone("reconcile_required")).toBe("warning");
    expect(operationalTone("error")).toBe("danger");
  });

  it("renders business impact and next step without internal code or evidence reference", () => {
    render(<ProblemNotice problem={{
      code: "INSUFFICIENT_DATA",
      state: "insufficient_data",
      message: "证据不足",
      impact: "不能发布效果结论",
      evidence: [{ kind: "run", ref: "RUN-001" }],
      nextStep: "补充曝光数据",
      retryable: false,
    }} />);

    expect(screen.getByText("现有信息不足以继续")).toBeInTheDocument();
    expect(screen.getByText("不能发布效果结论")).toBeInTheDocument();
    expect(screen.queryByText("INSUFFICIENT_DATA")).not.toBeInTheDocument();
    expect(screen.queryByText("run:RUN-001")).not.toBeInTheDocument();
    expect(screen.getByText("补充曝光数据")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveClass("wb-notice-info");
    expect(screen.getByRole("status")).not.toHaveClass("wb-notice-success");
  });
});
