import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GuidedVersionControls, type GuidedItemVersion } from "./GuidedVersionControls";

const versions: GuidedItemVersion[] = [
  { versionCode: "section-v1", versionNumber: 1, sourceLabel: "DeepSeek 初次生成", createdAt: "2026-08-06T02:01:00Z" },
  { versionCode: "section-v2", versionNumber: 2, sourceLabel: "人工编辑", createdAt: "2026-08-06T03:02:00Z" },
  { versionCode: "section-v3", versionNumber: 3, sourceLabel: "引导重生成", createdAt: "2026-08-06T04:03:00Z" },
];

describe("GuidedVersionControls", () => {
  it("pages through versions while keeping preview selection controlled by the parent", async () => {
    const onPreview = vi.fn();
    const user = userEvent.setup();
    render(
      <GuidedVersionControls
        versions={versions}
        previewVersionId="section-v2"
        activeVersionId="section-v2"
        onPreview={onPreview}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("2/3")).toBeInTheDocument();
    expect(screen.getByText("人工编辑")).toBeInTheDocument();
    expect(screen.getByText("版本 v2")).toBeInTheDocument();
    expect(screen.getByText("当前采用")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "预览上一个版本" }));
    await user.click(screen.getByRole("button", { name: "预览下一个版本" }));
    expect(onPreview).toHaveBeenNthCalledWith(1, "section-v1");
    expect(onPreview).toHaveBeenNthCalledWith(2, "section-v3");
  });

  it("frames a historical selection as pending and exposes stale recovery actions", async () => {
    const onSelect = vi.fn();
    const onReaffirm = vi.fn();
    const onRegenerate = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <GuidedVersionControls
        versions={versions}
        previewVersionId="section-v1"
        activeVersionId="section-v3"
        staleWarning="直播大纲第 2 段已更新，请检查当前话术。"
        onPreview={vi.fn()}
        onSelect={onSelect}
        onReaffirm={onReaffirm}
        onRegenerate={onRegenerate}
      />,
    );

    expect(screen.getByText(/正在预览历史版本/)).toHaveTextContent("不会直接替换已确认内容");
    expect(screen.getByText("上游内容已变化")).toBeInTheDocument();
    expect(screen.getByText("直播大纲第 2 段已更新，请检查当前话术。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "选为待确认版本" }));
    expect(onSelect).toHaveBeenCalledWith("section-v1");
    expect(screen.queryByRole("button", { name: "确认仍然适用" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新生成" })).not.toBeInTheDocument();

    rerender(
      <GuidedVersionControls
        versions={versions}
        previewVersionId="section-v1"
        activeVersionId="section-v1"
        staleWarning="直播大纲第 2 段已更新，请检查当前话术。"
        onPreview={vi.fn()}
        onSelect={onSelect}
        onReaffirm={onReaffirm}
        onRegenerate={onRegenerate}
      />,
    );
    await user.click(screen.getByRole("button", { name: "确认仍然适用" }));
    await user.click(screen.getByRole("button", { name: "重新生成" }));
    expect(onReaffirm).toHaveBeenCalledWith("section-v1");
    expect(onRegenerate).toHaveBeenCalledWith("section-v1");
  });

  it("describes a selected draft as pending confirmation", () => {
    render(
      <GuidedVersionControls
        versions={versions}
        previewVersionId="section-v1"
        activeVersionId="section-v1"
        pendingConfirmation
        onPreview={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("草稿已选择")).toBeInTheDocument();
    expect(screen.getByText("此版本已加入当前草稿，确认节点后才会生效。")).toBeInTheDocument();
  });

  it("handles an empty version collection", () => {
    render(
      <GuidedVersionControls
        versions={[]}
        previewVersionId="missing"
        activeVersionId="missing"
        onPreview={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("暂无可用版本")).toBeInTheDocument();
  });
});
