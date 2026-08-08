import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Eye,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import "./GuidedVersionTree.css";

type GuidedItemVersionIdentity =
  | { id: string; versionCode?: string }
  | { id?: string; versionCode: string };

export type GuidedItemVersion = GuidedItemVersionIdentity & {
  versionNumber?: number;
  sourceLabel: string;
  createdAt: string;
  staleWarning?: string | null;
};

export interface GuidedVersionControlsProps {
  versions: GuidedItemVersion[];
  previewVersionId: string;
  activeVersionId: string;
  pendingConfirmation?: boolean;
  staleWarning?: string | null;
  onPreview: (versionId: string) => void;
  onSelect: (versionId: string) => void;
  onReaffirm?: (versionId: string) => void;
  onRegenerate?: (versionId: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
}

function versionId(version: GuidedItemVersion): string {
  const id = version.id ?? version.versionCode;
  if (!id) throw new Error("Guided item version requires an id or versionCode");
  return id;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function GuidedVersionControls({
  versions,
  previewVersionId,
  activeVersionId,
  pendingConfirmation = false,
  staleWarning,
  onPreview,
  onSelect,
  onReaffirm,
  onRegenerate,
  disabled = false,
  ariaLabel = "条目版本",
}: GuidedVersionControlsProps) {
  const currentIndex = versions.findIndex((version) => versionId(version) === previewVersionId);
  const activeIndex = versions.findIndex((version) => versionId(version) === activeVersionId);
  const current = currentIndex >= 0 ? versions[currentIndex] : undefined;
  const isPriorVersion = currentIndex >= 0 && activeIndex >= 0 && currentIndex < activeIndex;
  const effectiveStaleWarning = staleWarning ?? current?.staleWarning;

  if (!current) {
    return (
      <section className="guided-version-controls is-empty" aria-label={ariaLabel}>
        <span>暂无可用版本</span>
      </section>
    );
  }

  const currentId = versionId(current);
  const isActive = currentId === activeVersionId;

  return (
    <section className="guided-version-controls" aria-label={ariaLabel}>
      <div className="guided-version-controls-main">
        <div className="guided-version-pager" role="group" aria-label="切换条目版本">
          <button
            type="button"
            aria-label="预览上一个版本"
            title="上一个版本"
            disabled={disabled || currentIndex === 0}
            onClick={() => onPreview(versionId(versions[currentIndex - 1]))}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <strong aria-live="polite">{currentIndex + 1}/{versions.length}</strong>
          <button
            type="button"
            aria-label="预览下一个版本"
            title="下一个版本"
            disabled={disabled || currentIndex === versions.length - 1}
            onClick={() => onPreview(versionId(versions[currentIndex + 1]))}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="guided-version-meta">
          <span><Eye size={13} aria-hidden="true" /><strong>{current.sourceLabel}</strong></span>
          <time dateTime={current.createdAt}><Clock3 size={13} aria-hidden="true" />{formatTimestamp(current.createdAt)}</time>
          {current.versionNumber ? <small>版本 v{current.versionNumber}</small> : null}
        </div>

        <div className="guided-version-actions">
          {!isActive ? (
            <button
              className="guided-version-action is-primary"
              type="button"
              disabled={disabled}
              title="加入当前草稿，确认后才会生效"
              onClick={() => onSelect(currentId)}
            >
              <CheckCircle2 size={14} aria-hidden="true" />选为待确认版本
            </button>
          ) : (
            <span className="guided-version-active-label">
              <CheckCircle2 size={14} aria-hidden="true" />{pendingConfirmation ? "草稿已选择" : "当前采用"}
            </span>
          )}
          {onReaffirm && isActive ? (
            <button
              className="guided-version-action"
              type="button"
              disabled={disabled}
              title="确认当前内容仍然适用于新的上游版本"
              onClick={() => onReaffirm(currentId)}
            >
              <RotateCcw size={14} aria-hidden="true" />确认仍然适用
            </button>
          ) : null}
          {onRegenerate && isActive ? (
            <button
              className="guided-version-action"
              type="button"
              disabled={disabled}
              title="基于当前上游内容重新生成此条目"
              onClick={() => onRegenerate(currentId)}
            >
              <RefreshCw size={14} aria-hidden="true" />重新生成
            </button>
          ) : null}
        </div>
      </div>

      {isPriorVersion || pendingConfirmation ? (
        <div className="guided-version-pending" role="status">
          <Eye size={14} aria-hidden="true" />
          <span>{pendingConfirmation ? "此版本已加入当前草稿，确认节点后才会生效。" : "正在预览历史版本；选择后将作为草稿等待确认，不会直接替换已确认内容。"}</span>
        </div>
      ) : null}

      {effectiveStaleWarning ? (
        <div className="guided-version-stale" role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          <span><strong>上游内容已变化</strong>{effectiveStaleWarning}</span>
        </div>
      ) : null}
    </section>
  );
}
