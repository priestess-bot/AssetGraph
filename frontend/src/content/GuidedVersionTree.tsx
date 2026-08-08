import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  Image,
  LayoutTemplate,
  ListTree,
  LoaderCircle,
  Pencil,
  Save,
  X,
} from "lucide-react";
import "./GuidedVersionTree.css";

export type GuidedVersionStage = "setup" | "outline" | "script" | "storyboard";

export type GuidedVersionNodeStatus =
  | "draft"
  | "confirmed"
  | "generating"
  | "failed"
  | "archived"
  | "needs_update";

type GuidedVersionNodeIdentity =
  | { id: string; nodeCode?: string }
  | { id?: string; nodeCode: string };

export type GuidedVersionTreeNode = GuidedVersionNodeIdentity & {
  title: string;
  stage: GuidedVersionStage;
  status: GuidedVersionNodeStatus;
  parentId?: string | null;
  parentNodeCode?: string | null;
  versionNumber?: number;
  children?: GuidedVersionTreeNode[];
};

export interface GuidedVersionTreeProps {
  nodes: GuidedVersionTreeNode[];
  activePath: string[];
  onSelect: (nodeId: string) => void;
  onRename: (nodeId: string, title: string) => void;
  onArchive: (nodeId: string) => void;
  ariaLabel?: string;
  showHeader?: boolean;
}

interface NormalizedNode {
  id: string;
  node: GuidedVersionTreeNode;
  parentId?: string;
  children: NormalizedNode[];
}

const STAGE_PRESENTATION = {
  setup: { label: "主题与素材", icon: Image },
  outline: { label: "直播大纲", icon: ListTree },
  script: { label: "直播脚本", icon: FileText },
  storyboard: { label: "麦兔分镜", icon: LayoutTemplate },
} satisfies Record<GuidedVersionStage, { label: string; icon: typeof Image }>;

const STATUS_LABELS: Record<GuidedVersionNodeStatus, string> = {
  draft: "草稿",
  confirmed: "已确认",
  generating: "生成中",
  failed: "失败",
  archived: "已归档",
  needs_update: "待更新",
};

function nodeId(node: GuidedVersionTreeNode): string {
  const id = node.id ?? node.nodeCode;
  if (!id) throw new Error("GuidedVersionTree node requires an id or nodeCode");
  return id;
}

function normalizeTree(nodes: GuidedVersionTreeNode[]): NormalizedNode[] {
  const records = new Map<string, NormalizedNode>();
  const order: string[] = [];

  const collect = (node: GuidedVersionTreeNode, nestedParentId?: string) => {
    const id = nodeId(node);
    if (!id || records.has(id)) return;
    const explicitParentId = node.parentId ?? node.parentNodeCode ?? undefined;
    records.set(id, { id, node, parentId: explicitParentId ?? nestedParentId, children: [] });
    order.push(id);
    node.children?.forEach((child) => collect(child, id));
  };

  nodes.forEach((node) => collect(node));

  const createsCycle = (record: NormalizedNode): boolean => {
    const visited = new Set([record.id]);
    let parentId = record.parentId;
    while (parentId) {
      if (visited.has(parentId)) return true;
      visited.add(parentId);
      parentId = records.get(parentId)?.parentId;
    }
    return false;
  };

  const roots: NormalizedNode[] = [];
  order.forEach((id) => {
    const record = records.get(id);
    if (!record) return;
    const parent = record.parentId ? records.get(record.parentId) : undefined;
    if (parent && !createsCycle(record)) parent.children.push(record);
    else roots.push(record);
  });
  return roots;
}

function TreeNode({
  item,
  activePath,
  activeNodeId,
  expanded,
  editingId,
  renameDraft,
  onToggle,
  onSelect,
  onBeginRename,
  onRenameDraftChange,
  onCommitRename,
  onCancelRename,
  onArchive,
}: {
  item: NormalizedNode;
  activePath: Set<string>;
  activeNodeId?: string;
  expanded: Set<string>;
  editingId?: string;
  renameDraft: string;
  onToggle: (nodeId: string) => void;
  onSelect: (nodeId: string) => void;
  onBeginRename: (item: NormalizedNode) => void;
  onRenameDraftChange: (value: string) => void;
  onCommitRename: (item: NormalizedNode) => void;
  onCancelRename: () => void;
  onArchive: (nodeId: string) => void;
}) {
  const { id, node, children } = item;
  const hasChildren = children.length > 0;
  const isExpanded = expanded.has(id);
  const isActive = activeNodeId === id;
  const isInActivePath = activePath.has(id);
  const isEditing = editingId === id;
  const stage = STAGE_PRESENTATION[node.stage];
  const StageIcon = stage.icon;
  const archiveDisabled = isInActivePath || node.status === "archived";
  const archiveTitle = isInActivePath
    ? "当前路径中的分支不能归档"
    : node.status === "archived"
      ? "此分支已归档"
      : `归档 ${node.title}`;

  return (
    <li
      className={`guided-version-tree-item${isInActivePath ? " is-in-active-path" : ""}${isActive ? " is-active" : ""}`}
      role="treeitem"
      aria-label={`${node.title}，${STATUS_LABELS[node.status]}`}
      aria-expanded={hasChildren ? isExpanded : undefined}
      aria-selected={isActive}
    >
      <div className="guided-version-tree-row">
        {hasChildren ? (
          <button
            className="guided-version-tree-icon-button guided-version-tree-toggle"
            type="button"
            aria-label={`${isExpanded ? "收起" : "展开"} ${node.title}`}
            title={`${isExpanded ? "收起" : "展开"}子分支`}
            onClick={() => onToggle(id)}
          >
            {isExpanded ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
          </button>
        ) : <span className="guided-version-tree-spacer" aria-hidden="true" />}

        {isEditing ? (
          <div className="guided-version-tree-rename">
            <input
              autoFocus
              aria-label={`重命名 ${node.title}`}
              value={renameDraft}
              onChange={(event) => onRenameDraftChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onCommitRename(item);
                if (event.key === "Escape") onCancelRename();
              }}
            />
            <button
              className="guided-version-tree-icon-button"
              type="button"
              aria-label={`保存 ${node.title} 的新名称`}
              title="保存名称"
              disabled={!renameDraft.trim()}
              onClick={() => onCommitRename(item)}
            >
              <Save size={14} aria-hidden="true" />
            </button>
            <button
              className="guided-version-tree-icon-button"
              type="button"
              aria-label={`取消重命名 ${node.title}`}
              title="取消"
              onClick={onCancelRename}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <>
            <button
              className="guided-version-tree-select"
              type="button"
              aria-label={`切换到 ${node.title}`}
              aria-current={isActive ? "true" : undefined}
              title={`切换项目到${node.title}`}
              onClick={() => onSelect(id)}
            >
              <span className="guided-version-tree-stage-icon">
                {node.status === "generating"
                  ? <LoaderCircle className="guided-version-tree-spin" size={15} aria-hidden="true" />
                  : <StageIcon size={15} aria-hidden="true" />}
              </span>
              <span className="guided-version-tree-copy">
                <strong>{node.title}</strong>
                <small>{stage.label}{node.versionNumber ? ` · v${node.versionNumber}` : ""}</small>
              </span>
              <span className={`guided-version-tree-status is-${node.status}`}>{STATUS_LABELS[node.status]}</span>
            </button>
            <span className="guided-version-tree-actions">
              <button
                className="guided-version-tree-icon-button"
                type="button"
                aria-label={`重命名 ${node.title}`}
                title="重命名分支"
                onClick={() => onBeginRename(item)}
              >
                <Pencil size={13} aria-hidden="true" />
              </button>
              <button
                className="guided-version-tree-icon-button is-danger"
                type="button"
                aria-label={`归档 ${node.title}`}
                title={archiveTitle}
                disabled={archiveDisabled}
                onClick={() => onArchive(id)}
              >
                <Archive size={13} aria-hidden="true" />
              </button>
            </span>
          </>
        )}
      </div>
      {hasChildren && isExpanded ? (
        <ul className="guided-version-tree-children" role="group">
          {children.map((child) => (
            <TreeNode
              key={child.id}
              item={child}
              activePath={activePath}
              activeNodeId={activeNodeId}
              expanded={expanded}
              editingId={editingId}
              renameDraft={renameDraft}
              onToggle={onToggle}
              onSelect={onSelect}
              onBeginRename={onBeginRename}
              onRenameDraftChange={onRenameDraftChange}
              onCommitRename={onCommitRename}
              onCancelRename={onCancelRename}
              onArchive={onArchive}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function GuidedVersionTree({
  nodes,
  activePath,
  onSelect,
  onRename,
  onArchive,
  ariaLabel = "创作版本树",
  showHeader = true,
}: GuidedVersionTreeProps) {
  const tree = useMemo(() => normalizeTree(nodes), [nodes]);
  const activePathKey = activePath.join("\u0000");
  const activePathSet = useMemo(() => new Set(activePath), [activePathKey]);
  const activeNodeId = activePath.at(-1);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(activePath));
  const [editingId, setEditingId] = useState<string>();
  const [renameDraft, setRenameDraft] = useState("");

  useEffect(() => {
    setExpanded((current) => new Set([...current, ...activePath]));
  }, [activePathKey]);

  const commitRename = (item: NormalizedNode) => {
    const title = renameDraft.trim();
    if (!title) return;
    if (title !== item.node.title) onRename(item.id, title);
    setEditingId(undefined);
    setRenameDraft("");
  };

  return (
    <aside className={`guided-version-tree${showHeader ? "" : " is-headerless"}`} aria-label={ariaLabel}>
      {showHeader ? <header className="guided-version-tree-header">
        <div>
          <ListTree size={17} aria-hidden="true" />
          <span><strong>版本分支</strong><small>切换将作用于整个项目</small></span>
        </div>
        <span className="guided-version-tree-current" title="当前路径">
          <Check size={13} aria-hidden="true" />当前
        </span>
      </header> : null}
      {tree.length ? (
        <ul className="guided-version-tree-root" role="tree" aria-label="项目创作分支">
          {tree.map((item) => (
            <TreeNode
              key={item.id}
              item={item}
              activePath={activePathSet}
              activeNodeId={activeNodeId}
              expanded={expanded}
              editingId={editingId}
              renameDraft={renameDraft}
              onToggle={(id) => setExpanded((current) => {
                const next = new Set(current);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return next;
              })}
              onSelect={onSelect}
              onBeginRename={(target) => {
                setEditingId(target.id);
                setRenameDraft(target.node.title);
              }}
              onRenameDraftChange={setRenameDraft}
              onCommitRename={commitRename}
              onCancelRename={() => {
                setEditingId(undefined);
                setRenameDraft("");
              }}
              onArchive={onArchive}
            />
          ))}
        </ul>
      ) : <p className="guided-version-tree-empty">暂无版本分支</p>}
    </aside>
  );
}
