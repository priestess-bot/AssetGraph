import * as Dialog from "@radix-ui/react-dialog";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  BookOpen,
  Check,
  Clapperboard,
  Clock3,
  ExternalLink,
  FileText,
  FilePenLine,
  GripVertical,
  Image,
  Layers3,
  ListTree,
  LockKeyhole,
  LoaderCircle,
  PackageCheck,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { assetLibraryApi, type LibraryAsset } from "../assets/api";
import { liveResearchApi } from "../live-research/api";
import { IconButton, Inspector, PageHeader } from "../product/components";
import { DeliveryProductPanel } from "../releases/DeliveryProductPanel";
import { VideoEditorProductPage } from "../videos/VideoEditorProductPage";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  StatusBadge,
  formatDate,
} from "../workbench/components";
import { productLabel } from "../workbench/productLanguage";
import { contentProjectsApi } from "./api";
import {
  guidedContentApi,
  type GuidedCitation,
  type GuidedJob,
  type GuidedMaituRoomConfiguration,
  type GuidedConfirmationPreview,
  type GuidedItemVersionRecord,
  type GuidedOutlineSection,
  type GuidedStoryboardScene,
  type GuidedWorkflow,
  type GuidedWorkflowStage,
} from "./workflowApi";
import { GuidedVersionControls, type GuidedItemVersion } from "./GuidedVersionControls";
import { GuidedVersionTree, type GuidedVersionNodeStatus } from "./GuidedVersionTree";


const TABS = [
  { value: "setup", label: "主题与素材", icon: Image },
  { value: "outline", label: "直播大纲", icon: ListTree },
  { value: "script", label: "直播脚本", icon: FileText },
  { value: "storyboard", label: "麦兔分镜", icon: Layers3 },
  { value: "video", label: "成片", icon: Clapperboard },
  { value: "delivery", label: "交付", icon: PackageCheck },
  { value: "activity", label: "动态", icon: Clock3 },
] as const;

const ROLE_ORDER = [
  "background",
  "set_surface",
  "product_display",
  "digital_human",
  "brand_title",
  "promotion_text",
  "decoration_foreground",
  "supporting_video",
  "voice",
  "background_music",
  "sound_effect",
];

function mutationError(error: unknown): string {
  return error instanceof Error ? error.message : "操作未完成，请刷新后重试。";
}

function activeJob(job: GuidedJob | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}

function jobLabel(job: GuidedJob): string {
  const source = `${job.operation ?? ""} ${job.stage}`.toLowerCase();
  if (source.includes("theme")) return "正在优化主题";
  if (source.includes("recommend")) return "正在推荐知识与素材";
  if (source.includes("section")) return "正在重生成大纲段落";
  if (source.includes("script_block")) return "正在重生成脚本段落";
  if (source.includes("storyboard_scene")) return "正在重生成分镜片段";
  if (source.includes("outline")) return "正在生成直播大纲";
  if (source.includes("script")) return "正在生成直播脚本";
  if (source.includes("storyboard")) return "正在生成麦兔分镜";
  return "正在生成内容";
}

function workflowJob(workflow: GuidedWorkflow, predicate: (job: GuidedJob) => boolean): GuidedJob | undefined {
  return Object.values(workflow.jobs)
    .filter(predicate)
    .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))[0];
}

function outlineSectionJob(workflow: GuidedWorkflow, sectionKey: string): GuidedJob | undefined {
  return workflowJob(workflow, (job) => job.targetSectionKey === sectionKey);
}

function sameDraft(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function toggleCode(codes: string[], code: string): string[] {
  return codes.includes(code) ? codes.filter((item) => item !== code) : [...codes, code];
}

function selectedKnowledgeReferences(
  codes: string[],
  references: GuidedWorkflow["setup"]["knowledgeReferences"],
): Array<{ kind: "fact_card" | "fact_claim" | "content_rule"; code: string; version_number?: number }> {
  const byCode = new Map(references.map((reference) => [reference.knowledgeCode, reference]));
  return codes.flatMap((code) => {
    const reference = byCode.get(code);
    if (!reference?.kind) return [];
    return [{
      kind: reference.kind,
      code,
      ...(reference.kind === "fact_card" && reference.versionNumber ? { version_number: reference.versionNumber } : {}),
    }];
  });
}

function useDirtyEditor(dirty: boolean, onDirtyChange: (dirty: boolean) => void) {
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
}

function useWorkflowRefresh(projectCode: string) {
  const client = useQueryClient();
  return useCallback((workflow?: GuidedWorkflow) => {
    if (workflow) client.setQueryData(["guided-content-workflow", projectCode], workflow);
    void client.invalidateQueries({ queryKey: ["guided-content-workflow", projectCode] });
    void client.invalidateQueries({ queryKey: ["content-project", projectCode] });
    void client.invalidateQueries({ queryKey: ["content-project", projectCode, "workspace-summary"] });
    void client.invalidateQueries({ queryKey: ["content-projects"] });
  }, [client, projectCode]);
}

function activeStageNode(workflow: GuidedWorkflow, stage: GuidedWorkflowStage) {
  const active = new Set(workflow.tree.activePath);
  return [...workflow.tree.nodes].reverse().find((node) => node.stage === stage && active.has(node.nodeCode));
}

function treeNodeStatus(status: string, hasDraft: boolean): GuidedVersionNodeStatus {
  if (hasDraft && status === "confirmed") return "draft";
  if (status === "stale" || status === "needs_update") return "needs_update";
  if (["draft", "confirmed", "generating", "failed", "archived"].includes(status)) return status as GuidedVersionNodeStatus;
  return "draft";
}

function stageRevision(workflow: GuidedWorkflow, stage: Exclude<GuidedWorkflowStage, "setup">): number {
  return activeStageNode(workflow, stage)?.currentRevisionNumber
    ?? (stage === "outline" ? workflow.outline?.revisionNumber : stage === "script" ? workflow.script?.revisionNumber : 0)
    ?? 0;
}

function stageBranchIdentity(workflow: GuidedWorkflow, stage: GuidedWorkflowStage): string {
  const node = activeStageNode(workflow, stage);
  return [
    workflow.tree.activePath.join("\u0000"),
    stage,
    node?.nodeCode ?? "",
    node?.currentRevisionNumber ?? 0,
  ].join(":");
}

function versionSourceLabel(version: GuidedItemVersionRecord): string {
  if (version.guidance) return "引导重生成";
  const kind = version.producerKind.toLowerCase();
  if (kind.includes("manual") || kind.includes("operator")) return "人工编辑";
  if (kind.includes("regenerat")) return "重新生成";
  if (kind.includes("deepseek") || kind.includes("ai") || kind.includes("generate")) return "AI 生成";
  return version.producerRef || version.producerKind || "历史版本";
}

function versionPreviewText(content: Record<string, unknown>): string {
  const lines = [content.title, content.objective, content.content, content.script]
    .filter((value): value is string => typeof value === "string" && Boolean(value.trim()));
  const points = Array.isArray(content.key_points) ? content.key_points.flatMap((point) => {
    if (typeof point === "string") return [point];
    if (point && typeof point === "object" && "text" in point && typeof point.text === "string") return [point.text];
    return [];
  }) : [];
  return [...lines, ...points].join("\n") || "该版本没有可预览的文本内容。";
}

function ItemVersionPanel({
  workflow,
  stage,
  itemKey,
  itemVersionId,
  versionNumber,
  stale,
  missing,
  onRegenerate,
  onReaffirm,
  actionPending = false,
}: {
  workflow: GuidedWorkflow;
  stage: Exclude<GuidedWorkflowStage, "setup">;
  itemKey: string;
  itemVersionId?: string;
  versionNumber?: number;
  stale?: boolean;
  missing?: boolean;
  onRegenerate?: () => void;
  onReaffirm?: () => void;
  actionPending?: boolean;
}) {
  const refresh = useWorkflowRefresh(workflow.project.projectCode);
  const branchKey = workflow.tree.activePath.join("/");
  const versions = useQuery({
    queryKey: ["guided-item-versions", workflow.project.projectCode, branchKey, stage, itemKey],
    queryFn: () => guidedContentApi.getItemVersions(workflow.project.projectCode, stage, itemKey),
    retry: false,
  });
  const selected = useMutation({
    mutationFn: (candidate: GuidedItemVersionRecord) => guidedContentApi.selectItemVersion(
      workflow.project.projectCode,
      stage,
      itemKey,
      candidate.versionNumber,
      stageRevision(workflow, stage),
    ),
    onSuccess: (value) => refresh(value),
  });
  const active = versions.data?.find((item) => item.id === itemVersionId)
    ?? versions.data?.find((item) => item.versionNumber === versionNumber)
    ?? versions.data?.at(-1);
  const [previewId, setPreviewId] = useState("");
  useEffect(() => setPreviewId(active?.id ?? ""), [active?.id, branchKey]);
  const preview = versions.data?.find((item) => item.id === previewId) ?? active;
  const controls: GuidedItemVersion[] = (versions.data ?? []).map((item) => ({
    id: item.id,
    versionNumber: item.versionNumber,
    sourceLabel: versionSourceLabel(item),
    createdAt: item.createdAt,
  }));
  if (versions.isLoading) return <div className="guided-item-version-loading">正在读取条目版本...</div>;
  if (versions.error) return <InlineNotice tone="danger" title="条目版本无法读取">{mutationError(versions.error)}</InlineNotice>;
  return <div className="guided-item-version-panel">
    {missing ? <InlineNotice tone="warning" title="当前条目缺失">请选用历史版本，或通过当前阶段的生成流程补齐。</InlineNotice> : null}
    {missing && onRegenerate ? <div className="guided-missing-item-action">
      <button className="wb-button wb-button-primary" type="button" disabled={actionPending} onClick={onRegenerate}><Sparkles size={14} aria-hidden="true" />生成此条目</button>
    </div> : null}
    <GuidedVersionControls
      versions={controls}
      previewVersionId={preview?.id ?? ""}
      activeVersionId={active?.id ?? ""}
      pendingConfirmation={Boolean(activeStageNode(workflow, stage)?.hasDraft)}
      staleWarning={stale ? "上游对应条目已经变化，请检查后重新选用合适版本。" : undefined}
      disabled={selected.isPending || actionPending}
      onPreview={setPreviewId}
      onSelect={(id) => {
        const candidate = versions.data?.find((item) => item.id === id);
        if (candidate) selected.mutate(candidate);
      }}
      onRegenerate={onRegenerate ? () => onRegenerate() : undefined}
      onReaffirm={onReaffirm ? () => onReaffirm() : undefined}
    />
    {preview && preview.id !== active?.id ? <pre className="guided-item-version-preview">{versionPreviewText(preview.content)}</pre> : null}
    {selected.error ? <InlineNotice tone="danger" title="版本未切换">{mutationError(selected.error)}</InlineNotice> : null}
  </div>;
}

const DOWNSTREAM_STAGES: Record<GuidedWorkflowStage, string[]> = {
  setup: ["直播大纲", "直播脚本", "麦兔分镜"],
  outline: ["直播脚本", "麦兔分镜"],
  script: ["麦兔分镜"],
  storyboard: [],
};

function ConfirmationPreviewDialog({
  preview,
  open,
  pending,
  error,
  onOpenChange,
  onConfirm,
}: {
  preview?: GuidedConfirmationPreview;
  open: boolean;
  pending: boolean;
  error?: unknown;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const affected = preview?.affectedDownstream.length ? preview.affectedDownstream : preview?.changed ? DOWNSTREAM_STAGES[preview.stage] : [];
  return <Dialog.Root open={open} onOpenChange={(value) => { if (!pending) onOpenChange(value); }}><Dialog.Portal>
    <Dialog.Overlay className="product-dialog-overlay" />
    <Dialog.Content className="guided-confirmation-dialog">
      <header><div><Dialog.Title>确认本阶段版本</Dialog.Title><Dialog.Description>确认前检查内容变化及其对后续阶段的影响。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭" disabled={pending}><X size={18} aria-hidden="true" /></Dialog.Close></header>
      {preview ? <div className="guided-confirmation-summary">
        {preview.changed ? <InlineNotice tone="warning" title="检测到内容变化">
          {affected.length ? `确认后将影响：${affected.join("、")}。系统会按差异标记需要检查的下游内容。` : "这是当前阶段的新版本，不会影响其他已确认阶段。"}
        </InlineNotice> : <InlineNotice tone="success" title="内容未变化">确认不会创建重复版本，也不要求重新生成下游内容。</InlineNotice>}
        {preview.changed ? <dl>
          <div><dt>新增</dt><dd>{preview.added.length ? preview.added.join("、") : "无"}</dd></div>
          <div><dt>删除</dt><dd>{preview.removed.length ? preview.removed.join("、") : "无"}</dd></div>
          <div><dt>修改</dt><dd>{preview.changedItems.length ? preview.changedItems.join("、") : "无"}</dd></div>
          <div><dt>顺序</dt><dd>{preview.reordered ? "已调整" : "未调整"}</dd></div>
        </dl> : null}
      </div> : <LoadingBlock label="正在检查版本变化" />}
      {error ? <InlineNotice tone="danger" title="确认预览失败">{mutationError(error)}</InlineNotice> : null}
      <footer><button className="wb-button" type="button" disabled={pending} onClick={() => onOpenChange(false)}>取消</button><button className="wb-button wb-button-primary" type="button" disabled={!preview || pending} onClick={onConfirm}>{pending ? "正在确认" : preview?.changed ? "确认并更新下游状态" : "确认，无需重生成"}</button></footer>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}

function GenerationBanner({ projectCode, job, label }: { projectCode: string; job?: GuidedJob; label?: string }) {
  const refresh = useWorkflowRefresh(projectCode);
  const retry = useMutation({
    mutationFn: () => guidedContentApi.retryJob(projectCode, job?.jobCode ?? ""),
    onSuccess: refresh,
  });
  if (!job || job.status === "succeeded" || job.status === "stale") return null;
  if (job.status === "failed") {
    return <><InlineNotice tone="danger" title="生成失败">
      <span>{job.errorMessage || "DeepSeek 未能生成有效结果。"}</span>
      <button className="wb-button" type="button" disabled={retry.isPending} onClick={() => retry.mutate()}>
        <RefreshCw size={14} aria-hidden="true" />重试
      </button>
    </InlineNotice>{retry.error ? <InlineNotice tone="danger" title="重试未提交">{mutationError(retry.error)}</InlineNotice> : null}</>;
  }
  const percent = Math.round((job.completedItems / Math.max(job.totalItems, 1)) * 100);
  return <div className="guided-job" role="status">
    <LoaderCircle size={16} className="spin" aria-hidden="true" />
    <div><strong>{job.status === "queued" ? `等待${label ?? jobLabel(job).replace(/^正在/, "")}` : label ?? jobLabel(job)}</strong><span>{job.completedItems} / {job.totalItems}</span></div>
    <div className="guided-job-progress"><i style={{ width: `${percent}%` }} /></div>
  </div>;
}

function MaterialPicker({
  assets,
  selected,
  onChange,
  disabled = false,
  locked = [],
}: {
  assets: LibraryAsset[];
  selected: string[];
  onChange: (codes: string[]) => void;
  disabled?: boolean;
  locked?: string[];
}) {
  const [role, setRole] = useState("all");
  const groupedRoles = ROLE_ORDER.filter((value) => assets.some((asset) => asset.materialRoles.includes(value)));
  const visible = role === "all" ? assets : assets.filter((asset) => asset.materialRoles.includes(role));
  const toggle = (assetCode: string) => {
    if (disabled || locked.includes(assetCode)) return;
    onChange(selected.includes(assetCode) ? selected.filter((code) => code !== assetCode) : [...selected, assetCode]);
  };
  return <div className="guided-material-picker">
    <div className="guided-role-filter" role="group" aria-label="素材分类">
      <button type="button" className={role === "all" ? "active" : undefined} onClick={() => setRole("all")}>全部素材（{assets.length}）</button>
      {groupedRoles.map((value) => <button type="button" key={value} className={role === value ? "active" : undefined} onClick={() => setRole(value)}>{productLabel(value, value)}</button>)}
    </div>
    <div className="guided-material-count">当前显示 {visible.length} 份，已选 {selected.length} 份</div>
    <div className="guided-material-grid">
      {visible.map((asset) => {
        const checked = selected.includes(asset.assetCode);
        return <button type="button" key={asset.assetCode} className={checked ? "selected" : undefined} aria-pressed={checked} disabled={disabled || locked.includes(asset.assetCode)} onClick={() => toggle(asset.assetCode)}>
          <span className="guided-material-thumb"><img src={assetLibraryApi.previewUrl(asset.assetCode, "thumbnail")} alt="" loading="lazy" /></span>
          <span><strong>{asset.title}</strong><small>{asset.materialRoles.map((item) => productLabel(item, item)).join(" / ")}{asset.rightsStatus === "pending" ? " · 待审批" : ""}</small></span>
          <i>{checked ? <Check size={13} aria-hidden="true" /> : null}</i>
        </button>;
      })}
    </div>
    {!visible.length ? <EmptyBlock title="当前分类没有可用素材" /> : null}
  </div>;
}

function RoomHostStatus({ configuration, isLoading, hasError }: { configuration?: GuidedMaituRoomConfiguration; isLoading: boolean; hasError: boolean }) {
  if (isLoading) return <section className="guided-room-status" aria-live="polite"><strong>麦兔直播间配置</strong><span>正在读取数字人与音色配置...</span></section>;
  if (hasError || !configuration) return <section className="guided-room-status is-warning"><strong>麦兔直播间配置</strong><span>暂时无法读取。请在麦兔直播间中检查数字人与音色后重试。</span></section>;
  return <section className={`guided-room-status ${configuration.ready ? "is-ready" : "is-warning"}`}>
    <div><strong>麦兔直播间配置</strong><StatusBadge label={configuration.ready ? "已配置" : "待配置"} tone={configuration.ready ? "success" : "warning"} />{configuration.systemManaged ? <StatusBadge label="系统锁定" tone="neutral" /> : null}</div>
    <span>数字人：{configuration.hostName ?? "未选择"}</span>
    <span>音色：{configuration.voiceName ?? "未选择"}</span>
    {configuration.sceneName ? <span>场景：{configuration.sceneName}</span> : null}
    {configuration.boundSceneCount ? <span>绑定场景：{configuration.boundSceneCount} 个</span> : null}
    {configuration.sourceMaterialId ? <span>主播素材：{configuration.sourceMaterialId}</span> : null}
    {configuration.checkedAt ? <small>最近检查：{formatDate(configuration.checkedAt)}</small> : null}
    {configuration.message ? <small>{configuration.message}</small> : null}
  </section>;
}

function SetupRecommendations({
  recommendations,
  selectedKnowledge,
  onKnowledgeChange,
  selectedMaterials,
  onMaterialChange,
  knownAssetCodes,
  disabled,
}: {
  recommendations?: GuidedWorkflow["setup"]["recommendations"];
  selectedKnowledge: string[];
  onKnowledgeChange: (codes: string[]) => void;
  selectedMaterials: string[];
  onMaterialChange: (codes: string[]) => void;
  knownAssetCodes: Set<string>;
  disabled: boolean;
}) {
  if (!recommendations) return null;
  return <section className="guided-recommendations" aria-label="AI 推荐">
    <header><BookOpen size={15} aria-hidden="true" /><div><h3>AI 推荐上下文</h3><span>选择后随“保存”写入本项目，不会自动采用。</span></div></header>
    {recommendations.knowledge.length ? <div className="guided-recommendation-group"><strong>知识候选</strong>{recommendations.knowledge.map((item) => <label key={item.knowledgeCode} className="guided-recommendation-row">
      <input type="checkbox" checked={selectedKnowledge.includes(item.knowledgeCode)} disabled={disabled} onChange={() => onKnowledgeChange(toggleCode(selectedKnowledge, item.knowledgeCode))} />
      <span><b>{item.title}</b>{item.excerpt ? <small>{item.excerpt}</small> : null}{item.version ? <small>版本：{item.version}</small> : null}</span>
    </label>)}</div> : null}
    {recommendations.materials.length ? <div className="guided-recommendation-group"><strong>素材候选</strong>{recommendations.materials.map((item) => {
      const known = knownAssetCodes.has(item.assetCode);
      return <label key={item.assetCode} className="guided-recommendation-row">
        <input type="checkbox" checked={selectedMaterials.includes(item.assetCode)} disabled={disabled || !known} onChange={() => onMaterialChange(toggleCode(selectedMaterials, item.assetCode))} />
        <span><b>{item.title}</b><small>{item.assetCode}{item.rationale ? ` · ${item.rationale}` : ""}{!known ? " · 素材库中未找到" : ""}</small></span>
      </label>;
    })}</div> : null}
  </section>;
}

function SetupPanel({ workflow, assets, onDirtyChange }: { workflow: GuidedWorkflow; assets: LibraryAsset[]; onDirtyChange: (dirty: boolean) => void }) {
  const refresh = useWorkflowRefresh(workflow.project.projectCode);
  const setupBranch = stageBranchIdentity(workflow, "setup");
  const [theme, setTheme] = useState(workflow.project.theme);
  const [selected, setSelected] = useState(workflow.materialPool.selectedAssetCodes);
  const [selectedKnowledge, setSelectedKnowledge] = useState(workflow.setup.selectedKnowledgeCodes);
  const [themeCandidate, setThemeCandidate] = useState(workflow.setup.themeCandidate);
  const [recommendationCandidates, setRecommendationCandidates] = useState(workflow.setup.recommendations);
  const [localThemeJob, setLocalThemeJob] = useState<GuidedJob>();
  const [localRecommendationJobs, setLocalRecommendationJobs] = useState<GuidedJob[]>([]);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [confirmationPreview, setConfirmationPreview] = useState<GuidedConfirmationPreview>();
  const room = useQuery({
    queryKey: ["guided-maitu-room-configuration", workflow.project.projectCode],
    queryFn: () => guidedContentApi.getMaituRoomConfiguration(workflow.project.projectCode),
    retry: false,
    staleTime: 15_000,
  });
  useEffect(() => {
    setTheme(workflow.project.theme);
    setSelected(workflow.materialPool.selectedAssetCodes);
    setSelectedKnowledge(workflow.setup.selectedKnowledgeCodes);
    setThemeCandidate(workflow.setup.themeCandidate);
    setRecommendationCandidates(workflow.setup.recommendations);
    setLocalThemeJob(undefined);
    setLocalRecommendationJobs([]);
    setConfirmationOpen(false);
    setConfirmationPreview(undefined);
  }, [setupBranch]);
  useEffect(() => {
    if (workflow.setup.themeCandidate) {
      setThemeCandidate(workflow.setup.themeCandidate);
      setLocalThemeJob(undefined);
    }
  }, [workflow.setup.themeCandidate]);
  useEffect(() => {
    if (workflow.setup.recommendations) {
      setRecommendationCandidates(workflow.setup.recommendations);
      setLocalRecommendationJobs([]);
    }
  }, [workflow.setup.recommendations]);
  useEffect(() => {
    if (localThemeJob && Object.values(workflow.jobs).some((job) => job.jobCode === localThemeJob.jobCode)) setLocalThemeJob(undefined);
    setLocalRecommendationJobs((jobs) => jobs.filter((job) => !Object.values(workflow.jobs).some((current) => current.jobCode === job.jobCode)));
  }, [localThemeJob, workflow.jobs]);
  const save = useMutation({
    mutationFn: () => guidedContentApi.updateSetup(workflow.project.projectCode, {
      expected_project_revision: workflow.project.revisionNumber,
      expected_material_pool_revision: workflow.materialPool.revisionNumber,
      theme: theme.trim(),
      selected_asset_codes: selected,
      selected_knowledge_codes: selectedKnowledge,
      selected_knowledge_refs: selectedKnowledgeReferences(selectedKnowledge, [
        ...workflow.setup.knowledgeReferences,
        ...(recommendationCandidates?.knowledge ?? []),
      ]),
    }),
    onSuccess: refresh,
  });
  const optimizeTheme = useMutation({
    mutationFn: () => guidedContentApi.optimizeTheme(workflow.project.projectCode, { theme: theme.trim() }),
    onSuccess: (result) => {
      if (result.candidate) setThemeCandidate(result.candidate);
      if (result.job) setLocalThemeJob(result.job);
      refresh();
    },
  });
  const recommend = useMutation({
    mutationFn: () => Promise.all((["knowledge", "materials"] as const).map((kind) => guidedContentApi.recommendSetup(workflow.project.projectCode, {
      kind,
      theme: theme.trim(),
      selected_asset_codes: selected,
      selected_knowledge_codes: selectedKnowledge,
    }))),
    onSuccess: (results) => {
      const knowledge = results.flatMap((result) => result.recommendations?.knowledge ?? []);
      const materials = results.flatMap((result) => result.recommendations?.materials ?? []);
      if (knowledge.length || materials.length) setRecommendationCandidates({ knowledge, materials });
      setLocalRecommendationJobs(results.flatMap((result) => result.job ? [result.job] : []));
      refresh();
    },
  });
  const generate = useMutation({
    mutationFn: () => guidedContentApi.generateOutline(workflow.project.projectCode),
    onSuccess: () => refresh(),
  });
  const themeJob = workflowJob(workflow, (job) => `${job.operation ?? ""} ${job.stage}`.toLowerCase().includes("theme")) ?? localThemeJob;
  const recommendationJobs = [
    ...Object.values(workflow.jobs).filter((job) => `${job.operation ?? ""} ${job.stage}`.toLowerCase().includes("recommend")),
    ...localRecommendationJobs.filter((job) => !Object.values(workflow.jobs).some((current) => current.jobCode === job.jobCode)),
  ];
  const dirty = theme !== workflow.project.theme
    || selected.join("|") !== workflow.materialPool.selectedAssetCodes.join("|")
    || selectedKnowledge.join("|") !== workflow.setup.selectedKnowledgeCodes.join("|");
  const previewConfirmation = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return guidedContentApi.getConfirmationPreview(workflow.project.projectCode, "setup");
    },
    onSuccess: (value) => { setConfirmationPreview(value); setConfirmationOpen(true); },
  });
  const confirmSetup = useMutation({
    mutationFn: () => {
      if (!confirmationPreview) throw new Error("确认预览尚未就绪");
      return guidedContentApi.confirmSetup(workflow.project.projectCode, confirmationPreview.expectedRevision, confirmationPreview.previewFingerprint);
    },
    onSuccess: (value) => { setConfirmationOpen(false); setConfirmationPreview(undefined); refresh(value); },
  });
  useDirtyEditor(dirty, onDirtyChange);
  const canGenerate = workflow.gates.setupConfirmed && Boolean(workflow.project.theme.trim()) && !dirty && !activeJob(workflow.jobs.outline) && !activeJob(themeJob) && !recommendationJobs.some(activeJob);
  const knownAssetCodes = new Set(assets.map((item) => item.assetCode));
  return <section className="guided-panel guided-setup-panel">
    <header className="guided-panel-header">
      <div><h2>主题与素材</h2><span>已选 {selected.length} 份素材、{selectedKnowledge.length} 条知识</span></div>
      <div>
        <button className="wb-button" type="button" title="保存修改；已确认项目会创建新的主题与素材分支" disabled={!dirty || !theme.trim() || save.isPending} onClick={() => save.mutate()}><Save size={15} aria-hidden="true" />保存</button>
        {(dirty || activeStageNode(workflow, "setup")?.hasDraft) ? <button className="wb-button" type="button" disabled={!theme.trim() || previewConfirmation.isPending || confirmSetup.isPending} onClick={() => previewConfirmation.mutate()}><Check size={15} aria-hidden="true" />确认主题与素材</button> : null}
        <button className="wb-button wb-button-primary" type="button" disabled={!canGenerate} onClick={() => generate.mutate()}><Sparkles size={15} aria-hidden="true" />生成大纲</button>
      </div>
    </header>
    {!workflow.gates.setupEditable ? <InlineNotice tone="warning" title="编辑将创建新分支">当前主题与素材已经有下游内容；保存修改会创建新的主题与素材分支，不会覆盖原分支。</InlineNotice> : null}
    <RoomHostStatus configuration={room.data} isLoading={room.isLoading} hasError={Boolean(room.error)} />
    <div className="guided-theme-field"><span>直播主题</span><textarea aria-label="直播主题" rows={4} value={theme} onChange={(event) => setTheme(event.target.value)} /><div className="guided-theme-actions">
      <button className="wb-button" type="button" disabled={!theme.trim() || optimizeTheme.isPending || activeJob(themeJob)} onClick={() => optimizeTheme.mutate()}><Sparkles size={15} aria-hidden="true" />优化主题</button>
      <button className="wb-button" type="button" disabled={!theme.trim() || recommend.isPending || recommendationJobs.some(activeJob)} onClick={() => recommend.mutate()}><BookOpen size={15} aria-hidden="true" />推荐知识与素材</button>
    </div></div>
    {themeCandidate ? <section className="guided-theme-candidate"><header><strong>AI 主题候选</strong>{themeCandidate.rationale ? <small>{themeCandidate.rationale}</small> : null}</header><p>{themeCandidate.theme}</p><footer><button className="wb-button wb-button-primary" type="button" onClick={() => setTheme(themeCandidate.theme)}>应用到编辑框</button></footer></section> : null}
    <GenerationBanner projectCode={workflow.project.projectCode} job={themeJob} />
    {recommendationJobs.map((job) => <GenerationBanner key={job.jobCode} projectCode={workflow.project.projectCode} job={job} />)}
    {workflow.setup.knowledgeReferences.length ? <section className="guided-confirmed-knowledge"><header><BookOpen size={14} aria-hidden="true" /><strong>已确认知识</strong><span>{workflow.setup.knowledgeReferences.length} 条</span></header><div>{workflow.setup.knowledgeReferences.map((item) => <article key={item.knowledgeCode}><b>{item.title}</b>{item.excerpt ? <small>{item.excerpt}</small> : null}</article>)}</div></section> : null}
    <SetupRecommendations recommendations={recommendationCandidates} selectedKnowledge={selectedKnowledge} onKnowledgeChange={setSelectedKnowledge} selectedMaterials={selected} onMaterialChange={setSelected} knownAssetCodes={knownAssetCodes} disabled={false} />
    <MaterialPicker assets={assets} selected={selected} onChange={setSelected} />
    <GenerationBanner projectCode={workflow.project.projectCode} job={workflow.jobs.outline} />
    <ConfirmationPreviewDialog preview={confirmationPreview} open={confirmationOpen} pending={confirmSetup.isPending} error={previewConfirmation.error || confirmSetup.error} onOpenChange={setConfirmationOpen} onConfirm={() => confirmSetup.mutate()} />
    {save.error || generate.error || optimizeTheme.error || recommend.error ? <InlineNotice tone="danger" title="操作未完成">{mutationError(save.error || generate.error || optimizeTheme.error || recommend.error)}</InlineNotice> : null}
  </section>;
}

function CitationList({ citations }: { citations: GuidedCitation[] }) {
  if (!citations.length) return <small className="guided-no-citations">仅基于主题与项目上下文生成</small>;
  return <ul className="guided-citation-list" aria-label="引用内容">{citations.map((citation, index) => <li key={`${citation.citationCode ?? citation.title}-${index}`}>
    <strong>{citation.title}</strong>{citation.excerpt ? <span>{citation.excerpt}</span> : null}{citation.referenceCode ? <small>{citation.referenceCode}</small> : null}
  </li>)}</ul>;
}

function SortableOutlineSection({
  section,
  index,
  editable,
  canRegenerate,
  job,
  onChange,
  onDelete,
  onRegenerate,
  onGuidedRegenerate,
  versionPanel,
}: {
  section: GuidedOutlineSection;
  index: number;
  editable: boolean;
  canRegenerate: boolean;
  job?: GuidedJob;
  onChange: (section: GuidedOutlineSection) => void;
  onDelete: () => void;
  onRegenerate: () => void;
  onGuidedRegenerate: () => void;
  versionPanel?: ReactNode;
}) {
  const sortable = useSortable({ id: section.sectionKey, disabled: !editable });
  return <article className="guided-outline-section" ref={sortable.setNodeRef} style={{ transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition }}>
    <button className="guided-drag" type="button" disabled={!editable} {...sortable.attributes} {...sortable.listeners} title="调整顺序"><GripVertical size={17} aria-hidden="true" /></button>
    <b>{index + 1}</b>
    <div>
      <input aria-label={`第 ${index + 1} 段标题`} value={section.title} disabled={!editable} onChange={(event) => onChange({ ...section, title: event.target.value })} />
      <textarea aria-label={`第 ${index + 1} 段目标`} rows={2} value={section.objective} disabled={!editable} onChange={(event) => onChange({ ...section, objective: event.target.value })} />
      <div className="guided-outline-points"><strong>要点与引用</strong>{section.keyPoints.map((point, pointIndex) => <article key={`${section.sectionKey}-point-${pointIndex}`}>
        <textarea aria-label={`第 ${index + 1} 段第 ${pointIndex + 1} 个要点`} rows={2} value={point.text} disabled={!editable} onChange={(event) => onChange({ ...section, keyPoints: section.keyPoints.map((item, itemIndex) => itemIndex === pointIndex ? { ...item, text: event.target.value } : item) })} />
        <CitationList citations={point.citations} />
        {editable ? <button className="product-icon-button" type="button" title="删除要点" onClick={() => onChange({ ...section, keyPoints: section.keyPoints.filter((_, itemIndex) => itemIndex !== pointIndex) })}><Trash2 size={14} aria-hidden="true" /></button> : null}
      </article>)}
      {editable ? <button className="guided-regenerate" type="button" onClick={() => onChange({ ...section, keyPoints: [...section.keyPoints, { text: "", citations: [] }] })}><Plus size={14} aria-hidden="true" />添加要点</button> : null}</div>
      <footer className="guided-outline-actions">
        <button className="guided-regenerate" type="button" disabled={!canRegenerate || activeJob(job)} onClick={onRegenerate}><RefreshCw size={14} aria-hidden="true" />重新生成此段</button>
        <button className="guided-regenerate" type="button" disabled={!canRegenerate || activeJob(job)} onClick={onGuidedRegenerate}><Sparkles size={14} aria-hidden="true" />引导重生成</button>
      </footer>
      {versionPanel}
    </div>
    <div className="guided-outline-side-actions">
      {editable ? <button className="product-icon-button" type="button" title="删除段落" onClick={onDelete}><Trash2 size={15} aria-hidden="true" /></button> : null}
      {activeJob(job) ? <span className="guided-section-job"><LoaderCircle size={14} className="spin" aria-hidden="true" />{job?.status === "queued" ? "等待重生成" : "正在重生成"}</span> : job?.status === "failed" ? <span className="guided-section-job is-failed">重生成失败</span> : null}
    </div>
  </article>;
}

function OutlinePanel({ workflow, onDirtyChange }: { workflow: GuidedWorkflow; onDirtyChange: (dirty: boolean) => void }) {
  const refresh = useWorkflowRefresh(workflow.project.projectCode);
  const outlineBranch = stageBranchIdentity(workflow, "outline");
  const [sections, setSections] = useState(workflow.outline?.sections ?? []);
  const [guidanceSection, setGuidanceSection] = useState<GuidedOutlineSection>();
  const [guidance, setGuidance] = useState("");
  const [localSectionJobs, setLocalSectionJobs] = useState<Record<string, GuidedJob>>({});
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [confirmationPreview, setConfirmationPreview] = useState<GuidedConfirmationPreview>();
  const [manualEditing, setManualEditing] = useState(false);
  useEffect(() => {
    setSections(workflow.outline?.sections ?? []);
    setLocalSectionJobs({});
    setGuidanceSection(undefined);
    setGuidance("");
    setConfirmationOpen(false);
    setConfirmationPreview(undefined);
    setManualEditing(false);
  }, [outlineBranch]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const editable = workflow.gates.outlineCurrent && (workflow.outline?.status === "draft" || manualEditing);
  const dirty = !sameDraft(sections, workflow.outline?.sections ?? []);
  useDirtyEditor(dirty, onDirtyChange);
  const save = useMutation({
    mutationFn: () => guidedContentApi.reviseOutline(workflow.project.projectCode, workflow.outline?.revisionNumber ?? 0, sections),
    onSuccess: refresh,
  });
  const generate = useMutation({
    mutationFn: () => guidedContentApi.generateOutline(workflow.project.projectCode),
    onSuccess: () => refresh(),
  });
  const regenerate = useMutation({
    mutationFn: ({ sectionKey, prompt }: { sectionKey: string; prompt?: string }) => guidedContentApi.regenerateOutlineSection(workflow.project.projectCode, sectionKey, workflow.outline?.revisionNumber ?? 0, prompt),
    onSuccess: (job, variables) => {
      if (job) setLocalSectionJobs((items) => ({ ...items, [variables.sectionKey]: job }));
      setGuidanceSection(undefined);
      setGuidance("");
      refresh();
    },
  });
  const previewConfirmation = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return guidedContentApi.getConfirmationPreview(workflow.project.projectCode, "outline");
    },
    onSuccess: (value) => { setConfirmationPreview(value); setConfirmationOpen(true); },
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!confirmationPreview) throw new Error("确认预览尚未就绪");
      return guidedContentApi.confirmOutline(workflow.project.projectCode, confirmationPreview.expectedRevision, confirmationPreview.previewFingerprint);
    },
    onSuccess: (value) => { setConfirmationOpen(false); setConfirmationPreview(undefined); refresh(value); },
  });
  const dragEnd = (event: DragEndEvent) => {
    if (!event.over || event.active.id === event.over.id) return;
    setSections((items) => arrayMove(items, items.findIndex((item) => item.sectionKey === event.active.id), items.findIndex((item) => item.sectionKey === event.over?.id)));
  };
  useEffect(() => {
    if (!Object.values(localSectionJobs).some(activeJob)) return;
    const timer = window.setInterval(() => refresh(), 1_500);
    return () => window.clearInterval(timer);
  }, [localSectionJobs, refresh]);
  useEffect(() => {
    setLocalSectionJobs((items) => {
      const next = Object.fromEntries(Object.entries(items).filter(([, job]) => {
        const serverJob = Object.values(workflow.jobs).find((current) => current.jobCode === job.jobCode);
        return !serverJob || !serverJob.targetSectionKey;
      }));
      return sameDraft(items, next) ? items : next;
    });
  }, [workflow.jobs]);
  if (!workflow.outline) return <section className="guided-panel"><GenerationBanner projectCode={workflow.project.projectCode} job={workflow.jobs.outline} />{!activeJob(workflow.jobs.outline) ? <EmptyBlock icon={ListTree} title="还没有直播大纲" detail="主题与素材保存后可生成大纲。" /> : null}</section>;
  const sectionJobs = Object.fromEntries(sections.map((section) => {
    const localJob = localSectionJobs[section.sectionKey];
    const serverJobForLocal = localJob ? Object.values(workflow.jobs).find((job) => job.jobCode === localJob.jobCode) : undefined;
    return [section.sectionKey, outlineSectionJob(workflow, section.sectionKey) ?? serverJobForLocal ?? localJob];
  }));
  const hasActiveSectionJob = Object.values(sectionJobs).some(activeJob);
  return <section className="guided-panel">
    <header className="guided-panel-header">
      <div><h2>直播大纲</h2><StatusBadge label={workflow.outline.status} tone={editable ? "warning" : "success"} /></div>
      <div>
        {!workflow.gates.outlineCurrent ? <button className="wb-button wb-button-primary" type="button" disabled={activeJob(workflow.jobs.outline) || generate.isPending} onClick={() => generate.mutate()}><RefreshCw size={15} aria-hidden="true" />重新生成大纲</button> : editable ? <>
          <button className="wb-button" type="button" onClick={() => setSections((items) => [...items, { sectionKey: `manual-${Date.now()}`, title: "新段落", objective: "待补充", keyPoints: [] }])}><Plus size={15} aria-hidden="true" />添加段落</button>
          <button className="wb-button" type="button" disabled={!dirty || !sections.length || save.isPending || hasActiveSectionJob} onClick={() => save.mutate()}><Save size={15} aria-hidden="true" />保存版本</button>
          <button className="wb-button wb-button-primary" type="button" disabled={!sections.length || previewConfirmation.isPending || confirm.isPending || save.isPending || hasActiveSectionJob} onClick={() => previewConfirmation.mutate()}><Check size={15} aria-hidden="true" />确认大纲</button>
        </> : <>
          <button className="wb-button" type="button" onClick={() => setManualEditing(true)}><FilePenLine size={15} aria-hidden="true" />编辑当前大纲</button>
          <button className="wb-button wb-button-primary" type="button" disabled={activeJob(workflow.jobs.outline) || generate.isPending} onClick={() => generate.mutate()}><Plus size={15} aria-hidden="true" />生成大纲新分支</button>
        </>}
      </div>
    </header>
    {!workflow.gates.outlineCurrent ? <InlineNotice tone="warning" title="大纲输入已变化">请重新生成大纲。</InlineNotice> : null}
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dragEnd}>
      <SortableContext items={sections.map((section) => section.sectionKey)} strategy={verticalListSortingStrategy}>
        <div className="guided-outline-list">{sections.map((section, index) => <SortableOutlineSection key={section.sectionKey} section={section} index={index} editable={editable} canRegenerate={workflow.gates.outlineCurrent && !dirty && !hasActiveSectionJob && !activeJob(workflow.jobs.outline)} job={sectionJobs[section.sectionKey]} onChange={(next) => setSections((items) => items.map((item) => item.sectionKey === next.sectionKey ? next : item))} onDelete={() => setSections((items) => items.filter((item) => item.sectionKey !== section.sectionKey))} onRegenerate={() => regenerate.mutate({ sectionKey: section.sectionKey })} onGuidedRegenerate={() => { setGuidanceSection(section); setGuidance(""); }} versionPanel={<ItemVersionPanel workflow={workflow} stage="outline" itemKey={section.sectionKey} itemVersionId={section.itemVersionId} versionNumber={section.versionNumber} stale={section.stale} missing={section.missing} />} />)}</div>
      </SortableContext>
    </DndContext>
    <GenerationBanner projectCode={workflow.project.projectCode} job={workflow.jobs.outline} />
    <Dialog.Root open={Boolean(guidanceSection)} onOpenChange={(open) => { if (!open && !regenerate.isPending) { setGuidanceSection(undefined); setGuidance(""); } }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="guided-regeneration-dialog">
      <header><div><Dialog.Title>引导重生成</Dialog.Title><Dialog.Description>补充本段希望强化、删除或调整的方向。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭" disabled={regenerate.isPending}><X size={18} aria-hidden="true" /></Dialog.Close></header>
      <label><span>{guidanceSection?.title ?? "大纲段落"}</span><textarea autoFocus rows={6} value={guidance} placeholder="例如：突出主推商品的核心卖点，并加入适用人群说明。" onChange={(event) => setGuidance(event.target.value)} /></label>
      <footer><button className="wb-button" type="button" disabled={regenerate.isPending} onClick={() => { setGuidanceSection(undefined); setGuidance(""); }}>取消</button><button className="wb-button wb-button-primary" type="button" disabled={!guidance.trim() || regenerate.isPending || !guidanceSection} onClick={() => guidanceSection && regenerate.mutate({ sectionKey: guidanceSection.sectionKey, prompt: guidance })}>{regenerate.isPending ? "正在提交" : "按引导重生成"}</button></footer>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <ConfirmationPreviewDialog preview={confirmationPreview} open={confirmationOpen} pending={confirm.isPending} error={previewConfirmation.error || confirm.error} onOpenChange={setConfirmationOpen} onConfirm={() => confirm.mutate()} />
    {save.error || generate.error || confirm.error || regenerate.error ? <InlineNotice tone="danger" title="操作未完成">{mutationError(save.error || generate.error || confirm.error || regenerate.error)}</InlineNotice> : null}
  </section>;
}

function ScriptArchivesDialog({
  open,
  onOpenChange,
  projectCode,
  expectedCurrentRevision,
  onRestore,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  projectCode: string;
  expectedCurrentRevision?: number;
  onRestore: (workflow: GuidedWorkflow) => void;
}) {
  const revisions = useQuery({ queryKey: ["guided-content-revisions", projectCode], queryFn: () => guidedContentApi.getRevisions(projectCode), enabled: open, retry: false });
  const restore = useMutation({
    mutationFn: (revisionNumber: number) => guidedContentApi.restoreScriptRevision(projectCode, revisionNumber, expectedCurrentRevision),
    onSuccess: (workflow) => {
      onRestore(workflow);
      onOpenChange(false);
    },
  });
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="guided-archive-dialog">
    <header><div><Dialog.Title>脚本版本归档</Dialog.Title><Dialog.Description>恢复会创建新的可编辑草稿，不会修改原归档。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header>
    <div className="guided-archive-list">{revisions.isLoading ? <LoadingBlock label="正在读取归档版本" /> : revisions.data?.script.length ? revisions.data.script.map((revision) => <article key={revision.revisionCode}>
      <span><strong>{revision.title ?? `脚本 r${revision.revisionNumber}`}</strong><small>{revision.revisionCode}{revision.createdAt ? ` · ${formatDate(revision.createdAt)}` : ""}</small></span>
      <StatusBadge label={revision.compatible ? "上游兼容" : "上游已变化"} tone={revision.compatible ? "success" : "warning"} />
      <button className="wb-button" type="button" disabled={!revision.restorable || !revision.compatible || restore.isPending} onClick={() => restore.mutate(revision.revisionNumber)}>恢复为草稿</button>
    </article>) : <EmptyBlock icon={Archive} title="没有可查看的脚本归档" detail="重新生成脚本后，旧稿会出现在这里。" />}</div>
    {revisions.error || restore.error ? <InlineNotice tone="danger" title="归档操作未完成">{mutationError(revisions.error || restore.error)}</InlineNotice> : null}
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function ScriptPanel({ workflow, assets, onDirtyChange }: { workflow: GuidedWorkflow; assets: LibraryAsset[]; onDirtyChange: (dirty: boolean) => void }) {
  const refresh = useWorkflowRefresh(workflow.project.projectCode);
  const scriptBranch = stageBranchIdentity(workflow, "script");
  const [blocks, setBlocks] = useState(workflow.script?.blocks ?? []);
  const [selected, setSelected] = useState(workflow.materialPool.selectedAssetCodes);
  const [materialsOpen, setMaterialsOpen] = useState(false);
  const [archivesOpen, setArchivesOpen] = useState(false);
  const [localScriptJob, setLocalScriptJob] = useState<GuidedJob>();
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [confirmationPreview, setConfirmationPreview] = useState<GuidedConfirmationPreview>();
  const [manualEditing, setManualEditing] = useState(false);
  useEffect(() => {
    setBlocks(workflow.script?.blocks ?? []);
    setSelected(workflow.materialPool.selectedAssetCodes);
    setMaterialsOpen(false);
    setLocalScriptJob(undefined);
    setConfirmationOpen(false);
    setConfirmationPreview(undefined);
    setManualEditing(false);
  }, [scriptBranch]);
  const serverScriptJob = workflowJob(workflow, (job) => `${job.operation ?? ""} ${job.stage}`.toLowerCase().includes("script"));
  const scriptJob = serverScriptJob ?? localScriptJob;
  useEffect(() => {
    if (localScriptJob && Object.values(workflow.jobs).some((job) => job.jobCode === localScriptJob.jobCode)) setLocalScriptJob(undefined);
  }, [localScriptJob, workflow.jobs]);
  useEffect(() => {
    if (!activeJob(localScriptJob)) return;
    const timer = window.setInterval(() => refresh(), 1_500);
    return () => window.clearInterval(timer);
  }, [localScriptJob, refresh]);
  const visibleScript = workflow.script;
  const editable = workflow.gates.scriptCurrent && (visibleScript?.status === "draft" || manualEditing);
  const dirty = !sameDraft(blocks, visibleScript?.blocks ?? []);
  useDirtyEditor(dirty, onDirtyChange);
  const generate = useMutation({
    mutationFn: () => guidedContentApi.generateScript(workflow.project.projectCode),
    onSuccess: (job) => {
      if (job) setLocalScriptJob(job);
      refresh();
    },
  });
  const regenerateBlock = useMutation({
    mutationFn: (sectionKey: string) => guidedContentApi.regenerateScriptBlock(
      workflow.project.projectCode,
      sectionKey,
      stageRevision(workflow, "script"),
    ),
    onSuccess: (job) => {
      if (job) setLocalScriptJob(job);
      refresh();
    },
  });
  const reaffirmBlock = useMutation({
    mutationFn: (sectionKey: string) => guidedContentApi.reaffirmScriptBlock(
      workflow.project.projectCode,
      sectionKey,
      stageRevision(workflow, "script"),
    ),
    onSuccess: refresh,
  });
  const save = useMutation({ mutationFn: () => guidedContentApi.reviseScript(workflow.project.projectCode, visibleScript?.revisionNumber ?? 0, blocks), onSuccess: refresh });
  const pool = useMutation({ mutationFn: () => guidedContentApi.updateMaterialPool(workflow.project.projectCode, { expected_revision: workflow.materialPool.revisionNumber, selected_asset_codes: selected }), onSuccess: (value) => { refresh(value); setMaterialsOpen(false); } });
  const previewConfirmation = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return guidedContentApi.getConfirmationPreview(workflow.project.projectCode, "script");
    },
    onSuccess: (value) => { setConfirmationPreview(value); setConfirmationOpen(true); },
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!confirmationPreview) throw new Error("确认预览尚未就绪");
      return guidedContentApi.confirmScript(workflow.project.projectCode, confirmationPreview.expectedRevision, confirmationPreview.previewFingerprint);
    },
    onSuccess: (value) => { setConfirmationOpen(false); setConfirmationPreview(undefined); refresh(value); },
  });
  const waive = useMutation({ mutationFn: (code: string) => guidedContentApi.waiveRequirement(workflow.project.projectCode, code, visibleScript?.revisionNumber ?? 0), onSuccess: refresh });
  if (!workflow.gates.outlineConfirmed) return <EmptyBlock icon={FileText} title="直播脚本尚未解锁" detail="确认当前直播大纲后可生成脚本。" />;
  const regenerating = generate.isPending || activeJob(scriptJob);
  const unmetVisualRequirements = visibleScript?.requirements.filter((item) => item.priority === "required" && item.status === "missing" && item.materialRole !== "digital_human" && item.materialRole !== "voice").length ?? 0;
  const startGeneration = () => generate.mutate();
  if (!visibleScript) return <section className="guided-panel">
    <header className="guided-panel-header"><div><h2>直播脚本</h2></div><div><button className="wb-button" type="button" onClick={() => setArchivesOpen(true)}><Archive size={15} aria-hidden="true" />版本归档</button></div></header>
    <GenerationBanner projectCode={workflow.project.projectCode} job={scriptJob} />
    {!regenerating ? <EmptyBlock icon={FileText} title="还没有直播脚本" detail="脚本按已确认大纲逐段生成。" /> : null}
    {!regenerating ? <div className="guided-empty-action"><button className="wb-button wb-button-primary" type="button" disabled={generate.isPending} onClick={startGeneration}><Sparkles size={15} aria-hidden="true" />生成直播脚本</button></div> : null}
    <ScriptArchivesDialog open={archivesOpen} onOpenChange={setArchivesOpen} projectCode={workflow.project.projectCode} onRestore={refresh} />
    {generate.error ? <InlineNotice tone="danger" title="脚本未生成">{mutationError(generate.error)}</InlineNotice> : null}
  </section>;
  return <section className="guided-panel">
    <header className="guided-panel-header">
      <div><h2>{visibleScript.title}</h2><StatusBadge label={visibleScript.status} tone={editable ? "warning" : "success"} /></div>
      <div>
        <button className="wb-button" type="button" onClick={() => setArchivesOpen(true)}><Archive size={15} aria-hidden="true" />版本归档</button>
        {!workflow.gates.scriptCurrent ? <button className="wb-button wb-button-primary" type="button" disabled={!workflow.gates.outlineConfirmed || regenerating} onClick={startGeneration}><RefreshCw size={15} aria-hidden="true" />基于当前大纲重新生成</button> : editable ? <>
          <button className="wb-button" type="button" disabled={!workflow.gates.scriptCurrent} onClick={() => setMaterialsOpen((value) => !value)}><Image size={15} aria-hidden="true" />补充素材</button>
          <button className="wb-button" type="button" disabled={!dirty || !workflow.gates.scriptCurrent || save.isPending} onClick={() => save.mutate()}><Save size={15} aria-hidden="true" />保存版本</button>
          <button className="wb-button wb-button-primary" type="button" disabled={unmetVisualRequirements > 0 || previewConfirmation.isPending || confirm.isPending || save.isPending} onClick={() => previewConfirmation.mutate()}><Check size={15} aria-hidden="true" />确认脚本</button>
        </> : <>
          <button className="wb-button" type="button" onClick={() => setManualEditing(true)}><FilePenLine size={15} aria-hidden="true" />编辑当前脚本</button>
          <button className="wb-button wb-button-primary" type="button" disabled={regenerating} onClick={startGeneration}><Plus size={15} aria-hidden="true" />生成脚本新分支</button>
        </>}
      </div>
    </header>
    {!workflow.gates.scriptCurrent ? <InlineNotice tone="warning" title="脚本上游已变化">重新生成会创建当前大纲下的新脚本分支，旧脚本仍保留在版本树中。</InlineNotice> : null}
    {materialsOpen && editable ? <div className="guided-script-materials"><MaterialPicker assets={assets} selected={selected} locked={workflow.materialPool.selectedAssetCodes} onChange={setSelected} /><footer><button className="wb-button wb-button-primary" type="button" disabled={pool.isPending} onClick={() => pool.mutate()}>保存并重新匹配</button></footer></div> : null}
    <div className="guided-script-list">{blocks.map((block, index) => {
      const requirements = visibleScript.requirements.filter((item) => item.blockSortOrder === index && item.materialRole !== "digital_human" && item.materialRole !== "voice") ?? [];
      return <article key={block.blockCode || block.sectionKey}>
        <header><b>{index + 1}</b><strong>{workflow.outline?.sections.find((section) => section.sectionKey === block.sectionKey)?.title ?? `段落 ${index + 1}`}</strong></header>
        <textarea aria-label={`第 ${index + 1} 段直播话术`} rows={9} value={block.content} disabled={!editable} onChange={(event) => setBlocks((items) => items.map((item) => item.sectionKey === block.sectionKey ? { ...item, content: event.target.value } : item))} />
        <div className="guided-requirements">{requirements.map((item) => <div key={item.requirementCode} className={`is-${item.status}`}>
          <span><strong>{productLabel(item.materialRole, item.materialRole)}</strong><small>{item.description}</small></span>
          <StatusBadge label={item.status === "matched" ? item.matchedAssetCode ?? "已匹配" : item.status === "waived" ? "已豁免" : item.priority === "required" ? "必选缺失" : "可选缺失"} tone={item.status === "matched" ? "success" : item.status === "waived" ? "warning" : item.priority === "required" ? "danger" : "neutral"} />
          {editable && item.priority === "required" && item.status === "missing" ? <button className="wb-button" type="button" disabled={waive.isPending} onClick={() => waive.mutate(item.requirementCode)}>豁免</button> : null}
        </div>)}</div>
        <ItemVersionPanel
          workflow={workflow}
          stage="script"
          itemKey={block.sectionKey}
          itemVersionId={block.itemVersionId}
          versionNumber={block.versionNumber}
          stale={block.stale}
          missing={block.missing}
          onRegenerate={!dirty && !regenerating ? () => regenerateBlock.mutate(block.sectionKey) : undefined}
          onReaffirm={block.stale && !dirty && !regenerating ? () => reaffirmBlock.mutate(block.sectionKey) : undefined}
          actionPending={regenerateBlock.isPending || reaffirmBlock.isPending || regenerating}
        />
      </article>;
    })}</div>
    <GenerationBanner projectCode={workflow.project.projectCode} job={scriptJob} />
    <ScriptArchivesDialog open={archivesOpen} onOpenChange={setArchivesOpen} projectCode={workflow.project.projectCode} expectedCurrentRevision={visibleScript.revisionNumber} onRestore={refresh} />
    <ConfirmationPreviewDialog preview={confirmationPreview} open={confirmationOpen} pending={confirm.isPending} error={previewConfirmation.error || confirm.error} onOpenChange={setConfirmationOpen} onConfirm={() => confirm.mutate()} />
    {save.error || pool.error || confirm.error || waive.error || generate.error || regenerateBlock.error || reaffirmBlock.error ? <InlineNotice tone="danger" title="操作未完成">{mutationError(save.error || pool.error || confirm.error || waive.error || generate.error || regenerateBlock.error || reaffirmBlock.error)}</InlineNotice> : null}
  </section>;
}

function StoryboardPanel({ workflow, onDirtyChange }: { workflow: GuidedWorkflow; onDirtyChange: (dirty: boolean) => void }) {
  const refresh = useWorkflowRefresh(workflow.project.projectCode);
  const storyboardBranch = stageBranchIdentity(workflow, "storyboard");
  const templates = useQuery({ queryKey: ["guided-layout-templates"], queryFn: liveResearchApi.listTemplates });
  const room = useQuery({
    queryKey: ["guided-maitu-room-configuration", workflow.project.projectCode],
    queryFn: () => guidedContentApi.getMaituRoomConfiguration(workflow.project.projectCode),
    retry: false,
    staleTime: 15_000,
  });
  const published = (templates.data ?? []).filter((template) => template.templateKind === "layout_hypothesis" && template.published_revision);
  const [templateCode, setTemplateCode] = useState(workflow.storyboard?.templateCode ?? "");
  const projection = useQuery({ queryKey: ["guided-layout-projection", templateCode], queryFn: () => liveResearchApi.getProjection(templateCode), enabled: Boolean(templateCode) });
  const [scenes, setScenes] = useState<GuidedStoryboardScene[]>(workflow.storyboard?.scenes ?? []);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [confirmationPreview, setConfirmationPreview] = useState<GuidedConfirmationPreview>();
  const [confirmationPlanCode, setConfirmationPlanCode] = useState("");
  const [manualEditing, setManualEditing] = useState(false);
  useEffect(() => {
    setTemplateCode(workflow.storyboard?.templateCode ?? "");
    setScenes(workflow.storyboard?.scenes ?? []);
    setConfirmationOpen(false);
    setConfirmationPreview(undefined);
    setConfirmationPlanCode("");
    setManualEditing(false);
  }, [storyboardBranch]);
  const dirty = !sameDraft(scenes, workflow.storyboard?.scenes ?? []);
  useDirtyEditor(dirty, onDirtyChange);
  const storyboardJob = workflowJob(workflow, (job) => job.stage === "storyboard");
  const generate = useMutation({
    mutationFn: () => {
      if (!projection.data?.projection_fingerprint) throw new Error("模板投影尚未就绪");
      return guidedContentApi.generateStoryboard(workflow.project.projectCode, { template_code: templateCode, revision: projection.data.revision, projection_fingerprint: projection.data.projection_fingerprint });
    },
    onSuccess: () => refresh(),
  });
  const regenerateScene = useMutation({
    mutationFn: (sectionKey: string) => guidedContentApi.regenerateStoryboardScene(
      workflow.project.projectCode,
      sectionKey,
      stageRevision(workflow, "storyboard"),
    ),
    onSuccess: () => refresh(),
  });
  const reaffirmScene = useMutation({
    mutationFn: (sectionKey: string) => guidedContentApi.reaffirmStoryboardScene(
      workflow.project.projectCode,
      sectionKey,
      stageRevision(workflow, "storyboard"),
    ),
    onSuccess: refresh,
  });
  const save = useMutation({ mutationFn: () => guidedContentApi.reviseStoryboard(workflow.project.projectCode, workflow.storyboard?.planCode ?? "", scenes), onSuccess: refresh });
  const previewConfirmation = useMutation({
    mutationFn: async () => {
      let planCode = workflow.storyboard?.planCode ?? "";
      if (dirty) {
        const revised = await guidedContentApi.reviseStoryboard(workflow.project.projectCode, planCode, scenes);
        planCode = revised.storyboard?.planCode ?? "";
      }
      const preview = await guidedContentApi.getConfirmationPreview(workflow.project.projectCode, "storyboard");
      return { preview, planCode };
    },
    onSuccess: ({ preview, planCode }) => { setConfirmationPreview(preview); setConfirmationPlanCode(planCode); setConfirmationOpen(true); },
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!confirmationPreview) throw new Error("确认预览尚未就绪");
      return guidedContentApi.confirmStoryboard(workflow.project.projectCode, confirmationPlanCode, confirmationPreview.previewFingerprint);
    },
    onSuccess: (value) => { setConfirmationOpen(false); setConfirmationPreview(undefined); refresh(value); },
  });
  if (!workflow.gates.scriptConfirmed) return <EmptyBlock icon={Layers3} title="麦兔分镜尚未解锁" detail="确认直播脚本和素材需求后可生成分镜。" />;
  const editable = workflow.gates.storyboardCurrent && (workflow.storyboard?.reviewStatus === "draft" || manualEditing);
  const needsGeneration = !workflow.storyboard || !workflow.gates.storyboardCurrent;
  return <section className="guided-panel">
    <header className="guided-panel-header">
      <div><h2>麦兔直播间分镜</h2>{workflow.storyboard ? <StatusBadge label={workflow.storyboard.reviewStatus} tone={editable ? "warning" : "success"} /> : null}</div>
      <div>
        {workflow.storyboard && editable ? <>
          <button className="wb-button" type="button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}><Save size={15} aria-hidden="true" />保存版本</button>
          <button className="wb-button wb-button-primary" type="button" disabled={previewConfirmation.isPending || confirm.isPending || save.isPending} onClick={() => previewConfirmation.mutate()}><Check size={15} aria-hidden="true" />确认分镜</button>
        </> : workflow.storyboard && workflow.gates.storyboardCurrent ? <>
          <button className="wb-button" type="button" onClick={() => setManualEditing(true)}><FilePenLine size={15} aria-hidden="true" />编辑当前分镜</button>
          <button className="wb-button wb-button-primary" type="button" disabled={!templateCode || !projection.data?.projection_fingerprint || activeJob(storyboardJob) || generate.isPending} onClick={() => generate.mutate()}><Plus size={15} aria-hidden="true" />生成分镜新分支</button>
        </> : null}
        {workflow.gates.storyboardConfirmed && workflow.storyboard?.planCode ? <a className="wb-button wb-button-primary" href={`/console/production/live-rooms?project=${encodeURIComponent(workflow.project.projectCode)}&run=${encodeURIComponent(workflow.storyboard.planCode)}`}><ExternalLink size={15} aria-hidden="true" />写入麦兔草稿</a> : null}
      </div>
    </header>
    {workflow.gates.storyboardManualOnly || workflow.storyboard?.manualOnly ? <InlineNotice tone="warning" title="仅支持人工落地">该版本包含已豁免的必选素材需求。</InlineNotice> : null}
    {workflow.storyboard && !workflow.gates.storyboardCurrent ? <InlineNotice tone="warning" title="分镜上游已变化">请基于当前脚本和素材重新生成分镜。</InlineNotice> : null}
    <RoomHostStatus configuration={room.data} isLoading={room.isLoading} hasError={Boolean(room.error)} />
    {needsGeneration ? <div className="guided-template-select">
      <label><span>直播间模板</span><select value={templateCode} onChange={(event) => setTemplateCode(event.target.value)}><option value="">请选择已发布模板</option>{published.map((template) => <option key={template.template_code} value={template.template_code}>{template.title}</option>)}</select></label>
      <button className="wb-button wb-button-primary" type="button" disabled={!templateCode || !projection.data?.projection_fingerprint || activeJob(storyboardJob) || generate.isPending} onClick={() => generate.mutate()}><Sparkles size={15} aria-hidden="true" />生成分镜</button>
    </div> : null}
    <GenerationBanner projectCode={workflow.project.projectCode} job={storyboardJob} />
    {workflow.storyboard ? <div className="guided-storyboard-list">{scenes.map((scene, index) => <article key={scene.itemKey ?? scene.shotCode}>
      <header><b>{index + 1}</b><input aria-label={`第 ${index + 1} 个分镜标题`} value={scene.title} disabled={!editable} onChange={(event) => setScenes((items) => items.map((item) => item.shotCode === scene.shotCode ? { ...item, title: event.target.value } : item))} /></header>
      <textarea aria-label={`第 ${index + 1} 个分镜话术`} rows={7} value={scene.script} disabled={!editable} onChange={(event) => setScenes((items) => items.map((item) => item.shotCode === scene.shotCode ? { ...item, script: event.target.value } : item))} />
      <div className="guided-scene-layers">{scene.layers.map((layer) => <span key={`${layer.role}:${layer.assetCode}`}>{layer.systemManaged ? <LockKeyhole size={13} aria-hidden="true" /> : <Layers3 size={13} aria-hidden="true" />}{productLabel(layer.role, layer.role)} · {layer.assetCode}{layer.systemManaged ? " · 系统锁定" : ""}</span>)}</div>
      <ItemVersionPanel
        workflow={workflow}
        stage="storyboard"
        itemKey={scene.itemKey ?? scene.shotCode}
        itemVersionId={scene.itemVersionId}
        versionNumber={scene.versionNumber}
        stale={scene.stale}
        missing={scene.missing}
        onRegenerate={!dirty && !activeJob(storyboardJob) ? () => regenerateScene.mutate(scene.itemKey ?? scene.shotCode) : undefined}
        onReaffirm={scene.stale && !scene.missing && !dirty && !activeJob(storyboardJob) ? () => reaffirmScene.mutate(scene.itemKey ?? scene.shotCode) : undefined}
        actionPending={regenerateScene.isPending || reaffirmScene.isPending || activeJob(storyboardJob)}
      />
    </article>)}</div> : !activeJob(workflow.jobs.storyboard) ? <EmptyBlock icon={Layers3} title="还没有分镜" /> : null}
    <ConfirmationPreviewDialog preview={confirmationPreview} open={confirmationOpen} pending={confirm.isPending} error={previewConfirmation.error || confirm.error} onOpenChange={setConfirmationOpen} onConfirm={() => confirm.mutate()} />
    {templates.error || projection.error || generate.error || save.error || confirm.error || regenerateScene.error || reaffirmScene.error ? <InlineNotice tone="danger" title="操作未完成">{mutationError(templates.error || projection.error || generate.error || save.error || confirm.error || regenerateScene.error || reaffirmScene.error)}</InlineNotice> : null}
  </section>;
}

function ActivityPanel({ workflow }: { workflow: GuidedWorkflow }) {
  const stageLabels: Record<string, string> = { setup: "主题与素材", outline: "直播大纲", script: "直播脚本", storyboard: "麦兔分镜" };
  const kindLabels: Record<string, string> = { material_pool_revision: "素材池版本", outline_revision: "大纲版本", script_revision: "脚本版本", storyboard_revision: "分镜版本", generation_job: "生成任务", material_waiver: "素材豁免" };
  return <section className="guided-panel"><header className="guided-panel-header"><div><h2>项目动态</h2><span>{workflow.history.length} 条记录</span></div></header>{workflow.history.length ? <div className="guided-activity">{workflow.history.map((event) => <article key={event.eventCode}><time>{formatDate(event.occurredAt)}</time><span><strong>{stageLabels[event.stage] ?? event.stage} · {kindLabels[event.kind] ?? event.kind}{event.revisionNumber ? ` r${event.revisionNumber}` : ""}</strong><small>{event.referenceCode}{event.actor ? ` · ${event.actor}` : ""}</small></span><StatusBadge label={event.status} tone={event.status === "confirmed" || event.status === "succeeded" ? "success" : event.status === "failed" ? "danger" : event.status === "waived" ? "warning" : "neutral"} /></article>)}</div> : <EmptyBlock icon={Clock3} title="还没有项目动态" />}</section>;
}

function ActiveJobsPanel({ workflow }: { workflow: GuidedWorkflow }) {
  const jobs = Object.values(workflow.jobs).filter(activeJob);
  if (!jobs.length) return null;
  return <section className="guided-active-jobs" aria-label="进行中的生成任务">
    <header><LoaderCircle size={15} className="spin" aria-hidden="true" /><div><strong>进行中的生成任务</strong><span>{jobs.length} 项任务正在处理</span></div></header>
    <div>{jobs.map((job) => <GenerationBanner key={job.jobCode} projectCode={workflow.project.projectCode} job={job} />)}</div>
  </section>;
}

export function GuidedProjectCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [roomId, setRoomId] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(() => `guided-create:${crypto.randomUUID()}`);
  const create = useMutation({
    mutationFn: () => guidedContentApi.create({ title: title.trim(), target_live_room_id: roomId.trim() }, idempotencyKey),
    onSuccess: (workflow) => {
      onClose();
      window.history.pushState(null, "", `/console/projects?project=${encodeURIComponent(workflow.project.projectCode)}&tab=setup`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
  });
  useEffect(() => { if (!open) { setTitle(""); setRoomId(""); setIdempotencyKey(`guided-create:${crypto.randomUUID()}`); } }, [open]);
  return <Dialog.Root open={open} onOpenChange={(value) => { if (!value) onClose(); }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="guided-create-dialog">
    <header><div><Dialog.Title>新建直播项目</Dialog.Title></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header>
    <div><label><span>项目标题</span><input autoFocus value={title} maxLength={255} onChange={(event) => setTitle(event.target.value)} /></label><label><span>麦兔直播间号</span><input value={roomId} maxLength={128} onChange={(event) => setRoomId(event.target.value)} /></label>{create.error ? <InlineNotice tone="danger" title="项目未创建">{mutationError(create.error)}</InlineNotice> : null}</div>
    <footer><button className="wb-button" type="button" onClick={onClose}>取消</button><button className="wb-button wb-button-primary" type="button" disabled={!title.trim() || !roomId.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending ? "正在创建" : "创建项目"}</button></footer>
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}

export function GuidedProjectWorkspace({ projectCode, tab }: { projectCode: string; tab: string }) {
  const [editorDirty, setEditorDirty] = useState(false);
  const [versionTreeOpen, setVersionTreeOpen] = useState(false);
  const onDirtyChange = useCallback((dirty: boolean) => setEditorDirty(dirty), []);
  const activeTab = TABS.some((item) => item.value === tab) ? tab : "setup";
  const workflow = useQuery({
    queryKey: ["guided-content-workflow", projectCode],
    queryFn: () => guidedContentApi.get(projectCode),
    refetchInterval: (query) => {
      const value = query.state.data;
      return value && Object.values(value.jobs).some(activeJob) ? 1500 : false;
    },
  });
  const assets = useQuery({ queryKey: ["guided-content-assets"], queryFn: assetLibraryApi.listAssets });
  const summary = useQuery({ queryKey: ["content-project", projectCode, "workspace-summary"], queryFn: () => contentProjectsApi.workspaceSummary(projectCode) });
  const refresh = useWorkflowRefresh(projectCode);
  const selectBranch = useMutation({
    mutationFn: (nodeCode: string) => guidedContentApi.selectTreeNode(projectCode, nodeCode, workflow.data?.tree.headRevision ?? 0),
    onSuccess: () => {
      setVersionTreeOpen(false);
      refresh();
    },
  });
  const updateBranch = useMutation({
    mutationFn: ({ nodeCode, label, archived }: { nodeCode: string; label?: string; archived?: boolean }) => guidedContentApi.updateTreeNode(projectCode, nodeCode, { ...(label !== undefined ? { label } : {}), ...(archived !== undefined ? { archived } : {}) }),
    onSuccess: () => refresh(),
  });
  useEffect(() => {
    if (!editorDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [editorDirty]);
  if (workflow.isLoading || assets.isLoading || summary.isLoading) return <LoadingBlock label="正在打开直播项目" />;
  if (!workflow.data || !summary.data) return <EmptyBlock title="项目无法打开" />;
  const usableAssets = (assets.data ?? []).filter((asset) => (
    (asset.rightsStatus === "approved" || asset.rightsStatus === "pending")
    && asset.executionCapability === "maitu_bound"
    && !asset.materialRoles.some((role) => role === "digital_human" || role === "voice")
  ));
  const ready: Record<string, boolean> = {
    setup: workflow.data.gates.setupConfirmed,
    outline: workflow.data.gates.outlineCurrent,
    script: workflow.data.gates.scriptCurrent,
    storyboard: workflow.data.gates.storyboardCurrent,
    video: summary.data.video.available,
    delivery: summary.data.delivery.available,
    activity: true,
  };
  const treeNodes = workflow.data.tree.nodes.map((node) => ({
    nodeCode: node.nodeCode,
    parentNodeCode: node.parentNodeCode,
    title: node.label,
    stage: node.stage,
    status: treeNodeStatus(node.status, node.hasDraft),
    versionNumber: node.currentRevisionNumber,
  }));
  const activeBranch = treeNodes.find((node) => node.nodeCode === workflow.data.tree.activePath.at(-1));
  return <div className={`project-workspace guided-workspace is-${activeTab}`}>
    <a className="project-back" href="/console/projects"><ArrowLeft size={15} aria-hidden="true" />返回项目列表</a>
    <PageHeader eyebrow={`麦兔直播间 ${workflow.data.project.targetLiveRoomId}`} title={workflow.data.project.title} description={workflow.data.project.theme || "主题待填写"} actions={<><IconButton label="版本分支" pressed={versionTreeOpen} onClick={() => setVersionTreeOpen(true)}><ListTree size={17} aria-hidden="true" /></IconButton><StatusBadge label={workflow.data.project.status} tone="success" /></>} />
    <ActiveJobsPanel workflow={workflow.data} />
    <nav className="project-tabs guided-tabs" aria-label="直播项目流程">{TABS.map((item) => { const Icon = item.icon; const isReady = ready[item.value]; return <a key={item.value} aria-current={activeTab === item.value ? "step" : undefined} className={activeTab === item.value ? "active" : undefined} href={`/console/projects?project=${encodeURIComponent(projectCode)}&tab=${item.value}`} onClick={(event) => { if (activeTab !== item.value && editorDirty && !window.confirm("当前修改尚未保存，确定离开吗？")) event.preventDefault(); }}><Icon size={15} aria-hidden="true" /><span>{item.label}</span><i role="img" aria-label={isReady ? "已完成" : "待完成"} title={isReady ? "已完成" : "待完成"} className={isReady ? "ready" : undefined} /></a>; })}</nav>
    <div className="project-tab-content guided-version-stage-content">
      {activeTab === "setup" ? <SetupPanel workflow={workflow.data} assets={usableAssets} onDirtyChange={onDirtyChange} /> : null}
      {activeTab === "outline" ? <OutlinePanel workflow={workflow.data} onDirtyChange={onDirtyChange} /> : null}
      {activeTab === "script" ? <ScriptPanel workflow={workflow.data} assets={usableAssets} onDirtyChange={onDirtyChange} /> : null}
      {activeTab === "storyboard" ? <StoryboardPanel workflow={workflow.data} onDirtyChange={onDirtyChange} /> : null}
      {activeTab === "video" ? workflow.data.gates.storyboardConfirmed ? <VideoEditorProductPage search={`?project=${encodeURIComponent(projectCode)}${summary.data.video.referenceCode ? `&plan=${encodeURIComponent(summary.data.video.referenceCode)}` : ""}`} /> : <EmptyBlock icon={Clapperboard} title="成片尚未解锁" detail="确认当前麦兔分镜后可进入成片制作。" /> : null}
      {activeTab === "delivery" ? !workflow.data.gates.storyboardConfirmed ? <EmptyBlock icon={PackageCheck} title="交付尚未解锁" detail="请先确认分镜并完成成片制作。" /> : summary.data.delivery.referenceCode ? <DeliveryProductPanel search={`?release=${encodeURIComponent(summary.data.delivery.referenceCode)}`} projectCode={projectCode} /> : <EmptyBlock icon={PackageCheck} title="还没有可交付内容" /> : null}
      {activeTab === "activity" ? <ActivityPanel workflow={workflow.data} /> : null}
    </div>
    <Inspector
      open={versionTreeOpen}
      title="版本分支"
      description={`当前：${activeBranch?.title ?? "尚未建立分支"}`}
      onClose={() => setVersionTreeOpen(false)}
      className="guided-version-inspector"
    >
      <GuidedVersionTree
        nodes={treeNodes}
        activePath={workflow.data.tree.activePath}
        showHeader={false}
        onSelect={(nodeCode) => {
          if (editorDirty && !window.confirm("当前修改尚未保存，确定切换版本分支吗？")) return;
          selectBranch.mutate(nodeCode);
        }}
        onRename={(nodeCode, label) => updateBranch.mutate({ nodeCode, label })}
        onArchive={(nodeCode) => {
          if (window.confirm("归档后该分支将从默认版本树中隐藏，确定继续吗？")) updateBranch.mutate({ nodeCode, archived: true });
        }}
      />
    </Inspector>
    {workflow.error || assets.error || summary.error || selectBranch.error || updateBranch.error ? <div className="guided-page-error"><AlertTriangle size={16} aria-hidden="true" />{mutationError(workflow.error || assets.error || summary.error || selectBranch.error || updateBranch.error)}</div> : null}
  </div>;
}
