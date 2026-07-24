import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { operationalTone, ProblemNotice } from "./components";


describe("operational problem presentation", () => {
  it("never maps warning, stale, insufficient data, or reconciliation to success", () => {
    expect(operationalTone("warning")).toBe("warning");
    expect(operationalTone("stale")).toBe("warning");
    expect(operationalTone("insufficient_data")).toBe("info");
    expect(operationalTone("reconcile_required")).toBe("warning");
    expect(operationalTone("error")).toBe("danger");
  });

  it("renders rule code, impact, evidence, and next step", () => {
    render(<ProblemNotice problem={{
      code: "INSUFFICIENT_DATA",
      state: "insufficient_data",
      message: "证据不足",
      impact: "不能发布效果结论",
      evidence: [{ kind: "run", ref: "RUN-001" }],
      nextStep: "补充曝光数据",
      retryable: false,
    }} />);

    expect(screen.getByText("INSUFFICIENT_DATA")).toBeInTheDocument();
    expect(screen.getByText("不能发布效果结论")).toBeInTheDocument();
    expect(screen.getByText("run:RUN-001")).toBeInTheDocument();
    expect(screen.getByText("补充曝光数据")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveClass("wb-notice-info");
    expect(screen.getByRole("status")).not.toHaveClass("wb-notice-success");
  });
});
