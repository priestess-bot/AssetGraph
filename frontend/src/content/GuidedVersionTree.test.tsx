import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GuidedVersionTree, type GuidedVersionTreeNode } from "./GuidedVersionTree";

const recursiveNodes: GuidedVersionTreeNode[] = [{
  id: "setup-a",
  title: "夏季主题",
  stage: "setup",
  status: "confirmed",
  children: [{
    id: "outline-a1",
    title: "大纲方案 A1",
    stage: "outline",
    status: "confirmed",
    versionNumber: 2,
    children: [{ id: "script-a1", title: "脚本方案 A1", stage: "script", status: "needs_update" }],
  }],
}];

describe("GuidedVersionTree", () => {
  it("renders a recursive active path, selects globally, and collapses child branches", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <GuidedVersionTree
        nodes={recursiveNodes}
        activePath={["setup-a", "outline-a1", "script-a1"]}
        onSelect={onSelect}
        onRename={vi.fn()}
        onArchive={vi.fn()}
      />,
    );

    const active = screen.getByRole("button", { name: "切换到 脚本方案 A1" });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "归档 大纲方案 A1" })).toBeDisabled();
    expect(screen.getByText("待更新")).toBeInTheDocument();
    expect(screen.getByText("直播大纲 · v2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "切换到 大纲方案 A1" }));
    expect(onSelect).toHaveBeenCalledWith("outline-a1");

    await user.click(screen.getByRole("button", { name: "收起 夏季主题" }));
    expect(screen.queryByRole("button", { name: "切换到 大纲方案 A1" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开 夏季主题" }));
    expect(screen.getByRole("button", { name: "切换到 大纲方案 A1" })).toBeInTheDocument();
  });

  it("builds a flat tree and supports rename and archive actions", async () => {
    const onRename = vi.fn();
    const onArchive = vi.fn();
    const user = userEvent.setup();
    const flatNodes: GuidedVersionTreeNode[] = [
      { nodeCode: "setup-b", title: "秋季主题", stage: "setup", status: "draft" },
      { nodeCode: "outline-b1", parentNodeCode: "setup-b", title: "方案 1", stage: "outline", status: "failed" },
      { nodeCode: "outline-b2", parentNodeCode: "setup-b", title: "方案 2", stage: "outline", status: "archived" },
      { nodeCode: "storyboard-b1", parentNodeCode: "outline-b1", title: "分镜方案", stage: "storyboard", status: "generating" },
    ];
    render(
      <GuidedVersionTree
        nodes={flatNodes}
        activePath={["setup-b"]}
        onSelect={vi.fn()}
        onRename={onRename}
        onArchive={onArchive}
      />,
    );

    expect(screen.getByText("草稿")).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText("已归档")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "归档 秋季主题" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "展开 方案 1" }));
    expect(screen.getByText("生成中")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重命名 方案 1" }));
    const input = screen.getByRole("textbox", { name: "重命名 方案 1" });
    await user.clear(input);
    await user.type(input, "重点商品方案");
    await user.click(screen.getByRole("button", { name: "保存 方案 1 的新名称" }));
    expect(onRename).toHaveBeenCalledWith("outline-b1", "重点商品方案");

    const archivedRow = screen.getByRole("treeitem", { name: "方案 2，已归档" });
    expect(within(archivedRow).getByRole("button", { name: "归档 方案 2" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "归档 方案 1" }));
    expect(onArchive).toHaveBeenCalledWith("outline-b1");
  });

  it("shows an explicit empty state", () => {
    render(<GuidedVersionTree nodes={[]} activePath={[]} onSelect={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />);
    expect(screen.getByText("暂无版本分支")).toBeInTheDocument();
  });
});
