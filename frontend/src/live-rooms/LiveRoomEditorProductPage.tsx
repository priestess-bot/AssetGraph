import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  CheckCircle2,
  ChevronRight,
  CirclePlay,
  ClipboardCheck,
  Eye,
  Layers3,
  ListChecks,
  LoaderCircle,
  LockKeyhole,
  PackageCheck,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
} from "lucide-react";
import { assetLibraryApi, type LibraryAsset } from "../assets/api";
import { contentProjectsApi, type ContentProjectDetail } from "../content/api";
import { liveResearchApi } from "../live-research/api";
import { PageHeader } from "../product/components";
import { EmptyBlock, LoadingBlock, StatusBadge } from "../workbench/components";
import { productLabel } from "../workbench/productLanguage";
import {
  conservativeMaituCapabilityFallback,
  functionalLiveRoomsApi,
  type FunctionalLiveRoomBuildOperation,
  type FunctionalLiveRoomPlan,
  type LiveRoomDraftExecution,
  type LiveRoomInspection,
  type MaituCapabilityMatrix,
} from "./api";
import {
  LIVE_ROOM_ROLE_OPTIONS,
  assetSelectionStatus,
  canMoveLayer,
  designBriefInput,
  executionStageCopy,
  friendlyRequestError,
  generatedProjectTitle,
  geometryRange,
  isAllowedTestRoom,
  layerBandLabel,
  materialRolesForScene,
  materialUsageLabel,
  moveLayer,
  normalizeLayerOrder,
  pendingRightsAreOnlyBlocker,
  reconciliationWasRecorded,
  roomInspectionFailureMessage,
  stableIdempotencyKey,
  updateGeometry,
} from "./model";
import "./live-room.css";

type Geometry = { x: number; y: number; width: number; height: number };
type DraftLayer = { key: string; role: string; assetCode: string; executionCapability: string; geometry: Geometry; zOrder: number; systemManaged: boolean };
type DraftScene = { key: string; shotCode: string; title: string; script: string; layers: DraftLayer[] };
type WorkflowStage = "idle" | "project" | "brief" | "content" | "plan" | "done";

const terminalInspectionStatuses = new Set(["succeeded", "failed", "cancelled"]);
const terminalExecutionStatuses = new Set(["succeeded", "failed", "reconcile_required", "cancelled"]);

function replaceLiveRoomQuery(values: Record<string, string | undefined>): void {
  const query = new URLSearchParams(window.location.search);
  Object.entries(values).forEach(([key, value]) => value ? query.set(key, value) : query.delete(key));
  window.history.replaceState(null, "", `${window.location.pathname}${query.size ? `?${query.toString()}` : ""}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function toggle(items: string[], value: string): string[] {
  return items.includes(value) ? items.filter((item) => item !== value) : [...items, value];
}

function sameStrings(left: unknown, right: string[]): boolean {
  const values = Array.isArray(left) ? left.filter((item): item is string => typeof item === "string") : [];
  return values.length === right.length && [...values].sort().every((item, index) => item === [...right].sort()[index]);
}

function draftFromPlan(plan: FunctionalLiveRoomPlan): DraftScene[] {
  return plan.blueprint.scenes.map((scene, sceneIndex) => ({
    key: `${scene.scene_code}:${sceneIndex}`,
    shotCode: scene.shot_code,
    title: scene.title,
    script: scene.script,
    layers: normalizeLayerOrder(scene.layers.map((layer, layerIndex) => ({
      key: `${scene.scene_code}:${layer.role}:${layerIndex}`,
      role: layer.role,
      assetCode: layer.asset_code,
      executionCapability: layer.execution_capability,
      geometry: { ...layer.normalized_geometry },
      zOrder: layer.z_order,
      systemManaged: layer.system_managed,
    }))),
  }));
}

function operationTitle(operation: FunctionalLiveRoomBuildOperation): string {
  const kind = operation.kind.toLowerCase();
  if (kind.includes("preflight") || kind.includes("room") || kind.includes("title")) return "核对直播间";
  if (kind.includes("clear") || kind.includes("delete")) return "清理原有草稿";
  if (kind.includes("scene")) return operation.sceneIndex === undefined ? "创建直播场景" : `创建第 ${operation.sceneIndex + 1} 个场景`;
  if (kind.includes("layer") || kind.includes("asset") || kind.includes("material")) return `放置${productLabel(operation.role ?? operation.layerType, "画面素材")}`;
  if (kind.includes("script") || kind.includes("speech")) return "填写本场话术";
  if (kind.includes("speaker") || kind.includes("human")) return "设置主播形象与声音";
  if (kind.includes("verify") || kind.includes("readback")) return "刷新并核对结果";
  return "完成一项场景配置";
}

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" | "info" {
  if (["ready", "completed", "complete", "succeeded", "maitu_complete"].includes(status)) return "success";
  if (["failed", "maitu_failed"].includes(status)) return "danger";
  if (["reconcile_required", "maitu_reconcile_required"].includes(status)) return "warning";
  if (["queued", "requested", "running", "maitu_running"].includes(status)) return "info";
  return "neutral";
}

function executionStatusLabel(status: string): string {
  if (status === "not_requested") return "待写入";
  if (["requested", "queued"].includes(status)) return "排队中";
  if (["maitu_running", "running"].includes(status)) return "执行中";
  if (["maitu_failed", "failed"].includes(status)) return "执行失败";
  if (["maitu_reconcile_required", "reconcile_required"].includes(status)) return "需要核对";
  if (["maitu_complete", "succeeded"].includes(status)) return "已核对";
  return "状态待确认";
}

function blueprintRevisionScenes(draft: DraftScene[]) {
  return draft.map((item, index) => ({
    shot_code: item.shotCode || `shot-${index + 1}`,
    sort_order: index,
    title: item.title,
    script: item.script,
    layers: normalizeLayerOrder(item.layers).map((entry) => ({
      role: entry.role,
      asset_code: entry.assetCode,
      geometry: entry.geometry,
      z_order: entry.zOrder,
    })),
  }));
}

function useRoomInspection(roomId: string, expectedTitle: string, initialCode = "") {
  const client = useQueryClient();
  const [inspectionCode, setInspectionCode] = useState(initialCode);
  useEffect(() => { if (initialCode) setInspectionCode(initialCode); }, [initialCode]);
  const query = useQuery({
    queryKey: ["live-room-inspection", inspectionCode],
    queryFn: () => functionalLiveRoomsApi.getRoomInspection(inspectionCode),
    enabled: Boolean(inspectionCode),
    refetchInterval: (state) => {
      const current = state.state.data as LiveRoomInspection | undefined;
      return current && terminalInspectionStatuses.has(current.status) ? false : 1_500;
    },
  });
  const create = useMutation({
    mutationFn: () => functionalLiveRoomsApi.createRoomInspection({
      targetLiveRoomId: roomId.trim(),
      expectedTitle: expectedTitle.trim() || undefined,
      idempotencyKey: crypto.randomUUID(),
    }),
    onSuccess: (inspection) => {
      setInspectionCode(inspection.inspectionCode);
      replaceLiveRoomQuery({ inspection: inspection.inspectionCode });
      client.setQueryData(["live-room-inspection", inspection.inspectionCode], inspection);
    },
  });
  return {
    inspectionCode,
    inspection: query.data ?? create.data,
    isLoading: create.isPending || query.isLoading || Boolean(inspectionCode && query.data && !terminalInspectionStatuses.has(query.data.status)),
    error: create.error ?? query.error,
    inspect: () => create.mutate(),
    refresh: () => void query.refetch(),
  };
}

function RoomInspectionSummary({ inspection, loading, error, onInspect, compact = false }: {
  inspection?: LiveRoomInspection;
  loading: boolean;
  error: unknown;
  onInspect: () => void;
  compact?: boolean;
}) {
  const result = inspection?.result;
  const failure = error ? friendlyRequestError(error, "没有读到麦兔房间") : undefined;
  const inspectionFailed = inspection?.status === "failed";
  return <section className={`live-room-inspection ${compact ? "is-compact" : ""}`}>
    <header>
      <div><Eye size={17} aria-hidden="true" /><span><strong>麦兔房间现状</strong><small>只读取，不会修改草稿</small></span></div>
      <button className="product-secondary-button" type="button" disabled={loading} onClick={onInspect}>
        <RefreshCw size={15} className={loading ? "is-spinning" : ""} aria-hidden="true" />{inspection ? "重新读取" : "读取房间"}
      </button>
    </header>
    {loading ? <div className="live-inspection-loading"><LoaderCircle size={18} className="is-spinning" /><span>正在通过本地执行器读取麦兔房间</span></div> : failure ? <div className="live-friendly-error"><strong>{failure.title}</strong><span>{failure.detail}</span><small>{failure.nextStep}</small></div> : inspectionFailed ? <div className="live-friendly-error"><strong>房间读取失败</strong><span>{roomInspectionFailureMessage(inspection.errorMessage)}</span><small>确认麦兔已登录并打开目标房间，然后点击“重新读取”。</small></div> : result ? <div className="live-inspection-result">
      <dl>
        <div><dt>当前标题</dt><dd>{result.actualTitle || "未读取到标题"}</dd></div>
        <div><dt>直播状态</dt><dd className={result.isLive || result.hasLiveTrace ? "is-danger" : "is-safe"}>{result.isLive ? "正在直播" : result.hasLiveTrace ? "存在开播痕迹" : "离线草稿"}</dd></div>
        <div><dt>已有场景</dt><dd>{result.sceneCount} 个</dd></div>
      </dl>
      {result.scenes.length ? <ol>{result.scenes.map((scene) => <li key={scene.sceneId}><span>{scene.orderNumber}</span><strong>{scene.name}</strong><small>{scene.materialCount} 个素材</small></li>)}</ol> : <p>当前房间没有可列出的场景。</p>}
    </div> : <p className="live-inspection-empty">先读取一次，执行前会再次核对标题、直播状态和已有场景。</p>}
  </section>;
}

function assetHasPreview(asset: LibraryAsset | undefined): boolean {
  return Boolean(asset?.localRelativePath) || asset?.sourceSystem === "local_upload";
}

function AssetChoice({ asset, checked, onChange }: { asset: LibraryAsset; checked: boolean; onChange: () => void }) {
  const availability = assetSelectionStatus(asset);
  const hasPreview = assetHasPreview(asset);
  return <label className={`live-choice-row live-asset-choice ${checked ? "is-selected" : ""} ${!availability.selectable ? "is-disabled" : ""}`}>
    <input type="checkbox" checked={checked} disabled={!availability.selectable} onChange={onChange} />
    {hasPreview ? <img src={assetLibraryApi.previewUrl(asset.assetCode, "thumbnail")} alt="" /> : <span className="live-choice-preview-placeholder"><Layers3 size={17} aria-hidden="true" /></span>}
    <span><strong>{asset.title}</strong><small>{asset.materialRoles.map((role) => productLabel(role, "其他用途")).join("、") || "用途待复核"} · {materialUsageLabel(asset.materialRoles)}</small><em>{availability.reason}</em></span>
    <StatusBadge label={availability.label} tone={availability.tone} />
  </label>;
}

function workflowStep(stage: WorkflowStage): number {
  return ({ idle: 0, project: 1, brief: 2, content: 3, plan: 4, done: 5 } as const)[stage];
}

interface CreateResult {
  plan?: FunctionalLiveRoomPlan;
  project: ContentProjectDetail;
  blockers: NonNullable<ContentProjectDetail["designBrief"]>["open_questions"];
}

function CreatePlanPanel({ requestedProject, requestedRoomTitle, requestedInspection, requestedCreateKey, recentPlans, onCreated, onOpenPlan }: {
  requestedProject: string;
  requestedRoomTitle: string;
  requestedInspection: string;
  requestedCreateKey: string;
  recentPlans: FunctionalLiveRoomPlan[];
  onCreated: (plan: FunctionalLiveRoomPlan, inspectionCode?: string) => void;
  onOpenPlan: (planCode: string) => void;
}) {
  const templates = useQuery({ queryKey: ["live-research", "templates"], queryFn: liveResearchApi.listTemplates });
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const groups = useQuery({ queryKey: ["assets", "groups"], queryFn: assetLibraryApi.listGroups });
  const [projectCode, setProjectCode] = useState(requestedProject);
  const project = useQuery({ queryKey: ["content-project", projectCode], queryFn: () => contentProjectsApi.get(projectCode), enabled: Boolean(projectCode) });
  const [roomId, setRoomId] = useState("");
  const [roomTitle, setRoomTitle] = useState(requestedRoomTitle);
  const [goal, setGoal] = useState("");
  const [theme, setTheme] = useState("");
  const [story, setStory] = useState("");
  const [detailedDesign, setDetailedDesign] = useState("");
  const [primaryTemplate, setPrimaryTemplate] = useState("");
  const [secondaryTemplates, setSecondaryTemplates] = useState<string[]>([]);
  const [assetCodes, setAssetCodes] = useState<string[]>([]);
  const [groupCodes, setGroupCodes] = useState<string[]>([]);
  const [assetSearch, setAssetSearch] = useState("");
  const [stage, setStage] = useState<WorkflowStage>("idle");
  const [briefBlockers, setBriefBlockers] = useState<CreateResult["blockers"]>([]);
  const [briefAnswers, setBriefAnswers] = useState<Record<string, string>>({});
  const hydrated = useRef("");
  const projectCreation = useRef({ key: requestedCreateKey || crypto.randomUUID(), fingerprint: "" });
  const planCreation = useRef({ key: crypto.randomUUID(), fingerprint: "" });

  useEffect(() => {
    const detail = project.data;
    if (!detail || hydrated.current === detail.projectCode) return;
    const content = detail.content;
    setRoomId(typeof content.target_live_room_id === "string" ? content.target_live_room_id : "");
    setGoal(detail.generationGoal);
    setTheme(typeof content.theme === "string" ? content.theme : "");
    setStory(typeof content.story === "string" ? content.story : "");
    setDetailedDesign(typeof content.detailed_design === "string" ? content.detailed_design : "");
    setPrimaryTemplate(typeof content.primary_template_code === "string" ? content.primary_template_code : "");
    setSecondaryTemplates(Array.isArray(content.secondary_template_codes) ? content.secondary_template_codes.filter((item): item is string => typeof item === "string") : []);
    setAssetCodes(Array.isArray(content.selected_asset_codes) ? content.selected_asset_codes.filter((item): item is string => typeof item === "string") : []);
    setGroupCodes(Array.isArray(content.selected_group_codes) ? content.selected_group_codes.filter((item): item is string => typeof item === "string") : []);
    hydrated.current = detail.projectCode;
  }, [project.data]);

  const inspection = useRoomInspection(roomId, roomTitle, requestedInspection);
  const publishedTemplates = (templates.data ?? []).filter((item) => item.status === "published" && item.contentReadiness === "ready");
  const filteredAssets = (assets.data ?? []).filter((asset) => `${asset.title} ${asset.originalFilename} ${asset.materialRoles.join(" ")}`.toLowerCase().includes(assetSearch.trim().toLowerCase()));
  const projectTitle = project.data?.title ?? generatedProjectTitle(theme, goal);

  const create = useMutation({
    mutationFn: async (): Promise<CreateResult> => {
      setBriefBlockers([]);
      setStage("project");
      let detail: ContentProjectDetail;
      if (projectCode) {
        detail = await contentProjectsApi.get(projectCode);
        const content = detail.content;
        const changed = detail.generationGoal !== goal.trim()
          || content.target_live_room_id !== roomId.trim()
          || (content.theme ?? "") !== theme.trim()
          || (content.story ?? "") !== story.trim()
          || (content.detailed_design ?? "") !== detailedDesign.trim()
          || (content.primary_template_code ?? "") !== primaryTemplate
          || !sameStrings(content.secondary_template_codes, secondaryTemplates)
          || !sameStrings(content.selected_group_codes, groupCodes)
          || !sameStrings(content.selected_asset_codes, assetCodes);
        if (changed) {
          detail = await contentProjectsApi.update(projectCode, {
            expected_revision: detail.revisionNumber,
            generation_goal: goal.trim(),
            target_live_room_id: roomId.trim(),
            theme: theme.trim() || undefined,
            story: story.trim() || undefined,
            detailed_design: detailedDesign.trim() || undefined,
            primary_template_code: primaryTemplate || undefined,
            secondary_template_codes: secondaryTemplates,
            selected_group_codes: groupCodes,
            selected_asset_codes: assetCodes,
          });
        }
      } else {
        const createPayload = {
          title: projectTitle,
          target_live_room_id: roomId.trim(),
          generation_goal: goal.trim(),
          theme: theme.trim() || undefined,
          story: story.trim() || undefined,
          detailed_design: detailedDesign.trim() || undefined,
          target_duration_seconds: 180,
          platform: "maitu",
          primary_template_code: primaryTemplate || undefined,
          secondary_template_codes: secondaryTemplates,
          selected_group_codes: groupCodes,
          selected_asset_codes: assetCodes,
        };
        const createFingerprint = JSON.stringify(createPayload);
        if (projectCreation.current.fingerprint && projectCreation.current.fingerprint !== createFingerprint) projectCreation.current.key = crypto.randomUUID();
        projectCreation.current.fingerprint = createFingerprint;
        replaceLiveRoomQuery({ createKey: projectCreation.current.key });
        const created = await contentProjectsApi.create(createPayload, { idempotencyKey: projectCreation.current.key });
        setProjectCode(created.projectCode);
        replaceLiveRoomQuery({ project: created.projectCode, roomTitle: roomTitle.trim(), run: undefined });
        detail = await contentProjectsApi.get(created.projectCode);
      }
      if (detail.status !== "confirmed") detail = await contentProjectsApi.confirm(detail.projectCode, detail.revisionNumber);
      setStage("brief");
      if (!detail.designBrief) detail = await contentProjectsApi.parseBrief(detail.projectCode, detail.revisionNumber, designBriefInput({ goal, theme, story, detailedDesign }));
      let blockers = (detail.designBrief?.open_questions ?? []).filter((question) => question.blocking);
      if (blockers.length && blockers.every((question) => briefAnswers[question.field]?.trim())) {
        detail = await contentProjectsApi.reviseBrief(
          detail.projectCode,
          detail.revisionNumber,
          Object.fromEntries(blockers.map((question) => [question.field, briefAnswers[question.field].trim()])),
        );
        blockers = (detail.designBrief?.open_questions ?? []).filter((question) => question.blocking);
      }
      if (blockers.length) return { project: detail, blockers };
      if (detail.designBrief?.status !== "confirmed") detail = await contentProjectsApi.confirmBrief(detail.projectCode, detail.revisionNumber);
      setStage("content");
      if (!detail.generated) detail = await contentProjectsApi.generate(detail.projectCode);
      const groupAssetCodes = (groups.data ?? []).filter((group) => groupCodes.includes(group.groupCode)).flatMap((group) => group.assetCodes);
      const selectedCodes = new Set([...assetCodes, ...groupAssetCodes]);
      const selectedAssets = (assets.data ?? []).filter((asset) => selectedCodes.has(asset.assetCode) && asset.executionCapability === "maitu_bound");
      const availableRoles = [...new Set(selectedAssets.flatMap((asset) => asset.materialRoles))];
      if (detail.program?.segments.length && detail.shotList?.shots.length) {
        const revisedRoles = detail.shotList.shots.map((shot, index) => materialRolesForScene(shot.material_role_requirements, availableRoles, index));
        const rolesChanged = revisedRoles.some((roles, index) => !sameStrings(detail.shotList?.shots[index]?.material_role_requirements, roles));
        if (rolesChanged) {
          detail = await contentProjectsApi.reviseProgramAndShots(
            detail.projectCode,
            detail.revisionNumber,
            detail.program.segments.map((segment) => ({
              semantic_goal: segment.semantic_goal,
              program_phase: segment.program_phase,
              estimated_duration_ms: segment.estimated_duration_ms,
              entry_condition: segment.entry_condition,
              exit_condition: segment.exit_condition,
              product_refs: segment.product_refs,
              interaction_actions: segment.interaction_actions,
              cta_actions: segment.cta_actions,
              branch_applicability: segment.branch_applicability,
              metadata: segment.metadata,
              script_block_codes: segment.script_block_codes,
            })),
            detail.shotList.shots.map((shot, index) => ({
              program_segment_index: Math.max(0, detail.program!.segments.findIndex((segment) => segment.segment_code === shot.program_segment_code)),
              shot_goal: shot.shot_goal,
              composition_intent: shot.composition_intent,
              material_role_requirements: revisedRoles[index],
              audio_actions: shot.audio_actions,
              continuity: shot.continuity,
              acceptance_criteria: shot.acceptance_criteria,
              estimated_duration_ms: shot.estimated_duration_ms,
              branch_applicability: shot.branch_applicability,
              must_include: shot.must_include,
              must_avoid: shot.must_avoid,
              script_block_codes: shot.script_block_codes,
            })),
          );
        }
      }
      setStage("plan");
      const roleOverrides = Object.fromEntries(LIVE_ROOM_ROLE_OPTIONS.flatMap((role) => {
        const selected = (assets.data ?? []).find((asset) => assetCodes.includes(asset.assetCode) && asset.executionCapability === "maitu_bound" && asset.materialRoles.includes(role));
        return selected ? [[role, selected.assetCode]] : [];
      }));
      const explicitlyProjectedAssetCodes = [...new Set(Object.values(roleOverrides))];
      const planInput = {
        project_code: detail.projectCode,
        target_live_room_id: roomId.trim(),
        expected_title: roomTitle.trim(),
        primary_template_code: primaryTemplate || undefined,
        secondary_template_codes: secondaryTemplates,
        asset_codes: assetCodes,
        required_loose_asset_codes: explicitlyProjectedAssetCodes,
        group_codes: groupCodes,
        material_pack_codes: [],
        asset_gap_codes: [],
        material_role_overrides: roleOverrides,
        material_role_modes: {},
        room_constraint_overrides: {},
      };
      const planFingerprint = JSON.stringify(planInput);
      const plan = await functionalLiveRoomsApi.create({
        ...planInput,
        idempotency_key: stableIdempotencyKey(planCreation.current, planFingerprint),
      });
      setStage("done");
      return { project: detail, blockers: [], plan };
    },
    onSuccess: (result) => {
      setBriefBlockers(result.blockers);
      if (result.blockers.length) {
        setBriefAnswers((current) => Object.fromEntries(result.blockers.map((question) => [
          question.field,
          current[question.field] || question.recommended_answer,
        ])));
      }
      if (result.plan) onCreated(result.plan, inspection.inspectionCode);
    },
  });

  const invalid = !roomId.trim() || !roomTitle.trim() || goal.trim().length < 10 || (!assetCodes.length && !groupCodes.length);
  const failure = create.error ? friendlyRequestError(create.error, "直播间方案没有生成") : undefined;
  const currentWorkflowStep = workflowStep(stage);

  return <div className="live-room-start">
    <PageHeader eyebrow="直播间制作" title="生成直播间方案" description="在一个页面完成内容输入、参考选择、素材选择和麦兔草稿准备。" />
    <div className="live-room-start-layout">
      <main className="live-room-builder">
        <section className="live-builder-section live-builder-intent">
          <header><span>01</span><div><h2>房间与生成目标</h2><p>麦兔当前标题只用于核对目标房间，内容项目名称由系统单独生成。</p></div></header>
          <div className="live-intent-grid">
            <label className="product-field"><span>直播间 ID *</span><input aria-label="直播间 ID" value={roomId} onChange={(event) => setRoomId(event.target.value)} placeholder="例如 41172" /></label>
            <label className="product-field"><span>麦兔当前标题 *</span><input aria-label="麦兔当前标题" value={roomTitle} onChange={(event) => setRoomTitle(event.target.value)} placeholder="例如 asser测试" /></label>
            <label className="product-field is-wide"><span>生成目标 *</span><textarea aria-label="生成目标" rows={3} value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="说明希望这场直播完成什么，例如介绍产品卖点并引导观众了解品鉴方法" /></label>
            <label className="product-field"><span>主题</span><input aria-label="主题" value={theme} onChange={(event) => setTheme(event.target.value)} placeholder="例如 介绍张裕品酒大师PRO" /></label>
            <label className="product-field"><span>故事</span><input aria-label="故事" value={story} onChange={(event) => setStory(event.target.value)} placeholder="可选：补充叙事线索" /></label>
            <label className="product-field is-wide"><span>详细设计</span><textarea aria-label="详细设计" rows={4} value={detailedDesign} onChange={(event) => setDetailedDesign(event.target.value)} placeholder="可选：补充场景、节奏、商品露出和互动要求" /></label>
          </div>
          <div className="live-project-name"><span>内容项目名称</span><strong>{projectTitle}</strong><small>不会覆盖或误用麦兔当前标题</small></div>
          <RoomInspectionSummary inspection={inspection.inspection} loading={inspection.isLoading} error={inspection.error} onInspect={inspection.inspect} compact />
        </section>

        <section className="live-builder-section">
          <header><span>02</span><div><h2>参考模板</h2><p>主模板提供结构骨架，次要模板只补充内容策略，不复制错误图层顺序。</p></div></header>
          <div className="live-reference-columns">
            <div><h3>主参考 <small>最多一个</small></h3>{publishedTemplates.length ? publishedTemplates.map((template) => <label className={`live-choice-row ${primaryTemplate === template.template_code ? "is-selected" : ""}`} key={`primary:${template.template_code}`}><input type="radio" name="primary-template" checked={primaryTemplate === template.template_code} onChange={() => { setPrimaryTemplate(template.template_code); setSecondaryTemplates((current) => current.filter((code) => code !== template.template_code)); }} /><span><strong>{template.title}</strong><small>{template.templateKind === "content_strategy" ? "内容策略模板" : "画面结构参考"}</small></span></label>) : <EmptyBlock title="暂无可选模板" detail="不选模板也可以从生成目标开始。" />}</div>
            <div><h3>次要参考 <small>可多选</small></h3>{publishedTemplates.filter((template) => template.template_code !== primaryTemplate).map((template) => <label className={`live-choice-row ${secondaryTemplates.includes(template.template_code) ? "is-selected" : ""}`} key={`secondary:${template.template_code}`}><input type="checkbox" checked={secondaryTemplates.includes(template.template_code)} onChange={() => setSecondaryTemplates((current) => toggle(current, template.template_code))} /><span><strong>{template.title}</strong><small>补充节奏、表达或互动方式</small></span></label>)}</div>
          </div>
        </section>

        <section className="live-builder-section">
          <header><span>03</span><div><h2>选择素材</h2><p>素材组和零散素材独立选择；不可执行原因直接显示在素材旁。</p></div></header>
          <div className="live-material-columns">
            <div className="live-choice-list"><h3>素材组 <small>已选 {groupCodes.length} 个</small></h3>{groups.data?.length ? groups.data.map((group) => <label className={`live-choice-row ${groupCodes.includes(group.groupCode) ? "is-selected" : ""}`} key={group.groupCode}><input type="checkbox" checked={groupCodes.includes(group.groupCode)} onChange={() => setGroupCodes((current) => toggle(current, group.groupCode))} /><span><strong>{group.title}</strong><small>{group.assetCount} 份素材</small></span></label>) : <EmptyBlock title="暂无素材组" />}</div>
            <div className="live-choice-list live-loose-assets"><div className="live-list-heading"><h3>零散素材 <small>已选 {assetCodes.length} 份</small></h3><label><Search size={14} aria-hidden="true" /><input aria-label="搜索零散素材" value={assetSearch} onChange={(event) => setAssetSearch(event.target.value)} placeholder="搜索素材" /></label></div>{filteredAssets.length ? filteredAssets.map((asset) => <AssetChoice key={asset.assetCode} asset={asset} checked={assetCodes.includes(asset.assetCode)} onChange={() => setAssetCodes((current) => toggle(current, asset.assetCode))} />) : <EmptyBlock title="没有符合条件的素材" />}</div>
          </div>
        </section>

        {briefBlockers.length ? <section className="live-brief-questions"><header><AlertTriangle size={17} /><span><strong>生成简报还需要补充信息</strong><small>采用建议或直接修改，随后继续生成，不需要离开当前页面。</small></span></header>{briefBlockers.map((question) => <label key={question.field}><span>{question.question}</span><textarea aria-label={question.question} rows={2} value={briefAnswers[question.field] ?? ""} onChange={(event) => setBriefAnswers((current) => ({ ...current, [question.field]: event.target.value }))} placeholder={question.recommended_answer || "请补充这个问题"} /></label>)}</section> : null}
        {failure ? <section className="live-friendly-error"><strong>{failure.title}</strong><span>{failure.detail}</span><small>{failure.nextStep}</small></section> : null}
        <footer className="live-builder-submit">
          <div><strong>{assetCodes.length + groupCodes.length}</strong><span>项素材选择</span><i /> <strong>{primaryTemplate ? 1 : 0}</strong><span>个主参考</span><i /><strong>{secondaryTemplates.length}</strong><span>个次参考</span></div>
          <button className="product-primary-button" type="button" disabled={invalid || create.isPending || briefBlockers.some((question) => !briefAnswers[question.field]?.trim())} onClick={() => create.mutate()}><CirclePlay size={16} aria-hidden="true" />{create.isPending ? "正在生成" : briefBlockers.length ? "采用补充并继续" : projectCode ? "继续并生成方案" : "生成直播间方案"}</button>
        </footer>
        {create.isPending ? <div className="live-workflow-progress" role="status"><ol>{["创建内容项目", "整理生成简报", "生成三段内容", "编译场景与图层", "方案已就绪"].map((label, index) => <li key={label} className={index < currentWorkflowStep ? "is-complete" : index === currentWorkflowStep ? "is-active" : ""}>{index < currentWorkflowStep ? <Check size={14} /> : <span>{index + 1}</span>}<strong>{label}</strong></li>)}</ol></div> : null}
      </main>
      <aside className="live-recent-plans"><header><h2>最近方案</h2><span>{recentPlans.length} 份</span></header>{recentPlans.length ? recentPlans.slice(0, 8).map((plan) => <button key={plan.planCode} type="button" onClick={() => onOpenPlan(plan.planCode)}><span><strong>{plan.expectedTitle}</strong><small>直播间 {plan.targetLiveRoomId}</small></span><StatusBadge label={executionStatusLabel(plan.executionStatus)} tone={statusTone(plan.executionStatus)} /><ChevronRight size={15} /></button>) : <EmptyBlock title="还没有直播间方案" detail="第一份方案会出现在这里。" />}</aside>
    </div>
  </div>;
}

function ExecutionProgress({ execution, onRetry, retrying, onReconcile, reconciling }: {
  execution: LiveRoomDraftExecution;
  onRetry: () => void;
  retrying: boolean;
  onReconcile: () => void;
  reconciling: boolean;
}) {
  const stage = executionStageCopy(execution.stage, execution.status);
  const progress = execution.progressTotal ? Math.min(100, Math.round((execution.progressCurrent / execution.progressTotal) * 100)) : execution.status === "succeeded" ? 100 : 0;
  const customerError = execution.error?.customerMessage && /[\u3400-\u9fff]/u.test(execution.error.customerMessage) ? execution.error.customerMessage : stage.detail;
  const nextStep = execution.error?.nextStep && /[\u3400-\u9fff]/u.test(execution.error.nextStep) ? execution.error.nextStep : "检查房间现场和页面提示后再继续。";
  return <section className={`live-execution-progress is-${execution.status}`}>
    <header><div>{execution.status === "succeeded" ? <CheckCircle2 size={20} /> : execution.status === "cancelled" ? <ClipboardCheck size={20} /> : execution.status === "running" || execution.status === "queued" ? <LoaderCircle size={20} className="is-spinning" /> : <AlertTriangle size={20} />}<span><strong>{stage.title}</strong><small>{stage.detail}</small></span></div><StatusBadge label={execution.status === "succeeded" ? "执行成功" : execution.status === "failed" ? "执行失败" : execution.status === "reconcile_required" ? "需要核对" : execution.status === "cancelled" ? "已核对并关闭" : "执行中"} tone={statusTone(execution.status)} /></header>
    <div className="live-progress-bar"><span><i style={{ width: `${progress}%` }} /></span><small>{execution.progressTotal ? `${execution.progressCurrent}/${execution.progressTotal}` : `${progress}%`}</small></div>
    <ol>{execution.stageEvents.map((event, index) => { const copy = executionStageCopy(event.stage, event.status); return <li key={`${event.stage}:${index}`} className={event.status === "succeeded" || event.status === "completed" ? "is-complete" : event.stage === execution.stage ? "is-active" : ""}><span>{event.status === "succeeded" || event.status === "completed" ? <Check size={13} /> : index + 1}</span><div><strong>{copy.title}</strong><small>{copy.detail}</small></div></li>; })}</ol>
    {execution.status === "failed" ? <div className="live-execution-failure"><strong>{customerError}</strong><span>{nextStep}</span>{execution.retryable ? <button className="product-secondary-button" type="button" disabled={retrying} onClick={onRetry}><RotateCcw size={15} />{retrying ? "正在重试" : "重试失败步骤"}</button> : null}</div> : null}
    {execution.status === "reconcile_required" ? <div className="live-execution-failure"><strong>{customerError}</strong><span>{nextStep}</span><button className="product-secondary-button" type="button" disabled={reconciling} onClick={onReconcile}><ClipboardCheck size={15} />{reconciling ? "正在核对" : "重新读取并核对"}</button></div> : null}
    {execution.status === "succeeded" ? <div className="live-test-only-result"><ShieldAlert size={16} /><span><strong>仅完成离线测试草稿</strong><small>结果不可发布，系统没有排播或开播。</small></span></div> : null}
  </section>;
}

function LiveRoomEditor({ plan, matrix, initialInspection, onPlan, onNew }: {
  plan: FunctionalLiveRoomPlan;
  matrix: MaituCapabilityMatrix;
  initialInspection: string;
  onPlan: (plan: FunctionalLiveRoomPlan) => void;
  onNew: () => void;
}) {
  const client = useQueryClient();
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const [draft, setDraft] = useState<DraftScene[]>(() => draftFromPlan(plan));
  const [sceneIndex, setSceneIndex] = useState(0);
  const [layerIndex, setLayerIndex] = useState<number | undefined>();
  const [panel, setPanel] = useState<"properties" | "build" | "execute">("properties");
  const [confirmedSceneIds, setConfirmedSceneIds] = useState<string[]>([]);
  const [testUseAcknowledged, setTestUseAcknowledged] = useState(false);
  const [reconciliationAcknowledged, setReconciliationAcknowledged] = useState(false);
  const [terminalSyncError, setTerminalSyncError] = useState(false);
  const terminalRefresh = useRef("");
  const revisionCreation = useRef({ key: crypto.randomUUID(), fingerprint: "" });
  const executionCreation = useRef({ key: crypto.randomUUID(), fingerprint: "" });
  const inspection = useRoomInspection(plan.targetLiveRoomId, plan.expectedTitle, initialInspection || plan.roomInspectionCode);

  useEffect(() => { setDraft(draftFromPlan(plan)); setSceneIndex(0); setLayerIndex(undefined); }, [plan.planCode]);
  useEffect(() => {
    const scenes = inspection.inspection?.result?.scenes;
    if (inspection.inspection?.status === "succeeded" && scenes) setConfirmedSceneIds(scenes.map((scene) => scene.sceneId));
  }, [inspection.inspection?.inspectionCode, inspection.inspection?.status]);

  const shouldPollExecution = Boolean(plan.executionJobCode) || ["requested", "maitu_running", "maitu_failed", "maitu_reconcile_required"].includes(plan.executionStatus);
  const execution = useQuery({
    queryKey: ["functional-live-room-plan", plan.planCode, "execution"],
    queryFn: () => functionalLiveRoomsApi.getExecution(plan.planCode),
    enabled: shouldPollExecution,
    refetchInterval: (state) => {
      const current = state.state.data as LiveRoomDraftExecution | undefined;
      if (!current || !terminalExecutionStatuses.has(current.status)) return 1_500;
      const key = `${current.executionJobCode}:${current.status}`;
      return terminalRefresh.current === key ? false : 1_500;
    },
  });
  useEffect(() => setTerminalSyncError(false), [execution.data?.executionJobCode]);
  useEffect(() => {
    const status = execution.data?.status;
    if (!status || !terminalExecutionStatuses.has(status) || terminalRefresh.current === `${execution.data?.executionJobCode}:${status}`) return;
    const terminalKey = `${execution.data?.executionJobCode}:${status}`;
    const refreshPlan = status === "succeeded"
      ? functionalLiveRoomsApi.syncExecution(plan.planCode)
      : functionalLiveRoomsApi.get(plan.planCode);
    void refreshPlan.then((next) => {
      terminalRefresh.current = terminalKey;
      setTerminalSyncError(false);
      onPlan(next);
    }).catch(() => setTerminalSyncError(true));
  }, [execution.data?.executionJobCode, execution.data?.status, execution.dataUpdatedAt, onPlan, plan.planCode]);

  const scene = draft[sceneIndex];
  const layer = layerIndex === undefined ? undefined : scene?.layers[layerIndex];
  const asset = (code: string) => assets.data?.find((item) => item.assetCode === code);
  const updateScene = (next: Partial<DraftScene>) => setDraft((current) => current.map((item, index) => index === sceneIndex ? { ...item, ...next } : item));
  const updateLayer = (next: Partial<DraftLayer>) => setDraft((current) => current.map((item, index) => {
    if (index !== sceneIndex) return item;
    const layers = item.layers.map((entry, position) => position === layerIndex ? { ...entry, ...next } : entry);
    const normalized = normalizeLayerOrder(layers);
    const selectedKey = layer?.key;
    if (selectedKey) queueMicrotask(() => setLayerIndex(normalized.findIndex((entry) => entry.key === selectedKey)));
    return { ...item, layers: normalized };
  }));
  const moveScene = (offset: -1 | 1) => setDraft((current) => { const target = sceneIndex + offset; if (target < 0 || target >= current.length) return current; const next = [...current]; [next[sceneIndex], next[target]] = [next[target], next[sceneIndex]]; setSceneIndex(target); return next; });
  const moveSelectedLayer = (direction: -1 | 1) => {
    if (!scene || !layer || layer.systemManaged) return;
    const moved = moveLayer(scene.layers, layer.key, direction);
    updateScene({ layers: moved });
    setLayerIndex(moved.findIndex((entry) => entry.key === layer.key));
  };

  const revisionScenes = blueprintRevisionScenes(draft);
  const hasUnsavedChanges = JSON.stringify(revisionScenes) !== JSON.stringify(
    blueprintRevisionScenes(draftFromPlan(plan)),
  );
  const revisionPayload = () => ({
    idempotency_key: stableIdempotencyKey(
      revisionCreation.current,
      JSON.stringify({ sourcePlanCode: plan.planCode, scenes: revisionScenes }),
    ),
    scenes: revisionScenes,
  });

  const save = useMutation({
    mutationFn: () => functionalLiveRoomsApi.reviseBlueprint(plan.planCode, revisionPayload()),
    onSuccess: (next) => { onPlan(next); client.setQueryData(["functional-live-room-plan", next.planCode], next); void client.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); },
  });
  const execute = useMutation({
    mutationFn: async () => {
      const targetPlan = hasUnsavedChanges
        ? await functionalLiveRoomsApi.reviseBlueprint(plan.planCode, revisionPayload())
        : plan;
      const identity = JSON.stringify({
        planCode: targetPlan.planCode,
        roomInspectionCode: inspection.inspection!.inspectionCode,
        roomFingerprint: inspection.inspection!.roomFingerprint!,
        confirmedSceneIds: [...confirmedSceneIds].sort(),
      });
      return functionalLiveRoomsApi.confirmExecution(targetPlan.planCode, {
        draftMode: "replace_test_draft",
        roomInspectionCode: inspection.inspection!.inspectionCode,
        expectedRoomFingerprint: inspection.inspection!.roomFingerprint!,
        confirmedSceneIds,
        idempotencyKey: stableIdempotencyKey(executionCreation.current, identity),
        testUseAcknowledged: true,
      });
    },
    onSuccess: (next) => { setReconciliationAcknowledged(false); client.setQueryData(["functional-live-room-plan", next.planCode], next); onPlan(next); setPanel("execute"); void client.invalidateQueries({ queryKey: ["functional-live-room-plan", next.planCode, "execution"] }); },
  });
  const retry = useMutation({ mutationFn: () => functionalLiveRoomsApi.retryExecution(plan.planCode), onSuccess: (job) => client.setQueryData(["functional-live-room-plan", plan.planCode, "execution"], job) });
  const reconcile = useMutation({
    mutationFn: () => functionalLiveRoomsApi.reconcileExecution(plan.planCode),
    onSuccess: (job) => {
      client.setQueryData(["functional-live-room-plan", plan.planCode, "execution"], job);
      setReconciliationAcknowledged(true);
      setTestUseAcknowledged(false);
      inspection.inspect();
    },
  });
  const releaseCandidate = useMutation({
    mutationFn: () => functionalLiveRoomsApi.createReleaseCandidate(plan.planCode),
    onSuccess: (next) => onPlan(next),
  });

  const result = inspection.inspection?.result;
  const roomMatches = Boolean(result && result.actualTitle === plan.expectedTitle);
  const roomOffline = Boolean(result && !result.isLive && !result.hasLiveTrace);
  const allScenesConfirmed = Boolean(result && result.scenes.length === confirmedSceneIds.length && result.scenes.every((item) => confirmedSceneIds.includes(item.sceneId)));
  const testRoomAllowed = isAllowedTestRoom(plan.targetLiveRoomId, plan.expectedTitle);
  const pendingRightsOnly = pendingRightsAreOnlyBlocker(plan.blockedReasons);
  const planAllowedForTest = plan.status === "ready" || (plan.status === "blocked" && pendingRightsOnly);
  const reconciliationRecorded = reconciliationAcknowledged || reconciliationWasRecorded(execution.data);
  const executionCanBeCreated = plan.executionStatus === "not_requested" || reconciliationRecorded;
  const hasFreshRecoveryInspection = !reconciliationRecorded || inspection.inspection?.inspectionCode !== plan.roomInspectionCode;
  const canExecute = planAllowedForTest && executionCanBeCreated && hasFreshRecoveryInspection && !inspection.isLoading && inspection.inspection?.status === "succeeded" && Boolean(inspection.inspection.roomFingerprint) && roomMatches && roomOffline && allScenesConfirmed && testUseAcknowledged && testRoomAllowed;
  const executeFailure = execute.error ? friendlyRequestError(execute.error, "草稿任务没有启动") : undefined;

  return <div className="live-room-editor-v2">
    <header className="live-editor-header">
      <div><button type="button" onClick={onNew}>直播间方案</button><ChevronRight size={14} /><strong>{plan.expectedTitle}</strong></div>
      <div><span>直播间 {plan.targetLiveRoomId}</span><StatusBadge label={plan.status === "ready" ? "方案可检查" : pendingRightsOnly ? "仅限离线测试" : "方案待完善"} tone={pendingRightsOnly ? "warning" : statusTone(plan.status)} /><button className="product-secondary-button" type="button" onClick={onNew}><Plus size={15} />新建方案</button></div>
    </header>

    <aside className="live-editor-outline">
      <header><div><span>场景与图层</span><strong>{draft.length} 个场景</strong></div><StatusBadge label="结构由剧本生成" tone="neutral" /></header>
      <div className="live-scene-outline">{draft.map((item, index) => <section key={item.key} className={index === sceneIndex ? "active" : ""}><button type="button" onClick={() => { setSceneIndex(index); setLayerIndex(undefined); }}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.title || "未命名场景"}</strong><small>{item.layers.length} 个图层</small></button>{index === sceneIndex ? <div>{[...item.layers].sort((left, right) => right.zOrder - left.zOrder).map((entry) => { const actualIndex = item.layers.findIndex((candidate) => candidate.key === entry.key); return <button key={entry.key} type="button" className={actualIndex === layerIndex ? "selected" : ""} onClick={() => setLayerIndex(actualIndex)}>{entry.systemManaged ? <LockKeyhole size={13} /> : <Layers3 size={13} />}<span><strong>{asset(entry.assetCode)?.title ?? productLabel(entry.role, "画面素材")}</strong><small>{entry.systemManaged ? "麦兔系统锁定" : layerBandLabel(entry.role)} · 第 {entry.zOrder} 层</small></span></button>; })}</div> : null}</section>)}</div>
      <footer><button type="button" title="上移场景" disabled={sceneIndex === 0} onClick={() => moveScene(-1)}><ArrowUp size={15} /></button><button type="button" title="下移场景" disabled={sceneIndex >= draft.length - 1} onClick={() => moveScene(1)}><ArrowDown size={15} /></button></footer>
    </aside>

    <main className="live-editor-canvas-area">
      <div className="live-canvas-toolbar"><span>9:16 直播画面</span><small>图层从底到顶按素材约束自动排序</small></div>
      <div className="live-canvas-stage"><div className="live-phone-canvas"><div className="live-safe-top">标题安全区</div>{scene?.layers.map((entry) => { const source = asset(entry.assetCode); const selected = entry.key === layer?.key; return <button key={entry.key} type="button" className={selected ? "selected" : ""} style={{ left: `${entry.geometry.x * 100}%`, top: `${entry.geometry.y * 100}%`, width: `${entry.geometry.width * 100}%`, height: `${entry.geometry.height * 100}%`, zIndex: entry.zOrder + 20 }} onClick={() => setLayerIndex(scene.layers.findIndex((item) => item.key === entry.key))}>{assetHasPreview(source) ? <img src={assetLibraryApi.previewUrl(entry.assetCode, source?.mediaKind === "video" ? "poster" : "thumbnail")} alt={source?.title ?? "场景素材"} style={{ objectFit: entry.role === "background" ? "cover" : "contain" }} /> : <span className="live-canvas-preview-placeholder"><Layers3 size={22} aria-hidden="true" /><small>{source?.title ?? productLabel(entry.role, "画面素材")}</small></span>}</button>; })}<div className="live-canvas-table">建议桌面区域</div><div className="live-canvas-caption">{scene?.script || "当前场景还没有话术"}</div></div></div>
      <div className="live-scene-script"><label className="product-field"><span>当前场景话术</span><textarea rows={3} value={scene?.script ?? ""} onChange={(event) => updateScene({ script: event.target.value })} placeholder="输入主播在这个场景中的主要话术" /></label></div>
    </main>

    <aside className="live-editor-properties">
      <nav><button type="button" className={panel === "properties" ? "active" : ""} onClick={() => setPanel("properties")}>属性</button><button type="button" className={panel === "build" ? "active" : ""} onClick={() => setPanel("build")}>搭建清单</button><button type="button" className={panel === "execute" ? "active" : ""} onClick={() => setPanel("execute")}>写入草稿</button></nav>
      {panel === "properties" ? <div className="live-properties-body">{layer ? <>
        <div className="live-properties-heading"><span>图层属性</span><h3>{asset(layer.assetCode)?.title ?? "画面素材"}</h3>{layer.systemManaged ? <StatusBadge label="麦兔系统锁定" tone="neutral" /> : null}</div>
        <label className="product-field"><span>使用素材</span><select aria-label="使用素材" value={layer.assetCode} disabled={layer.systemManaged} onChange={(event) => { const selected = asset(event.target.value); updateLayer({ assetCode: event.target.value, executionCapability: selected?.executionCapability ?? layer.executionCapability }); }}>{assets.data?.filter((item) => item.materialRoles.includes(layer.role) || (layer.role === "product_image" && item.materialRoles.includes("product_display"))).map((item) => <option key={item.assetCode} value={item.assetCode} disabled={!assetSelectionStatus(item).selectable}>{item.title}{assetSelectionStatus(item).readyForDraft ? "" : `（${assetSelectionStatus(item).label}）`}</option>)}</select></label>
        <div className="live-readonly-role"><span>画面用途</span><strong>{productLabel(layer.role, layer.role === "set_surface" ? "桌面与底图" : "其他图层")}</strong><small>用途来自剧本与素材约束，不能在场景中绕过。</small></div>
        <div className="live-layer-order-control"><header><span>图层层级</span><StatusBadge label={layer.systemManaged ? "系统固定" : layerBandLabel(layer.role)} tone={["background", "brand_title", "promotion_text", "decoration_foreground"].includes(layer.role) ? "warning" : "neutral"} /></header><div><button type="button" title="在当前层级区下移" disabled={layer.systemManaged || !canMoveLayer(scene.layers, layer.key, -1)} onClick={() => moveSelectedLayer(-1)}><ArrowDown size={16} /></button><strong>底到顶第 {layer.zOrder} 层</strong><button type="button" title="在当前层级区上移" disabled={layer.systemManaged || !canMoveLayer(scene.layers, layer.key, 1)} onClick={() => moveSelectedLayer(1)}><ArrowUp size={16} /></button></div><p>{layer.systemManaged ? "主播图层与目标直播间绑定，只能在麦兔中调整。" : "只能在同一层级区内移动，固定置顶和置底规则不能绕过。"}</p></div>
        <div className="live-geometry-controls">{(["x", "y", "width", "height"] as const).map((key) => { const range = geometryRange(layer.geometry, key); return <label key={key}><span>{({ x: "左侧位置", y: "顶部位置", width: "画面宽度", height: "画面高度" } as const)[key]} <strong>{Math.round(layer.geometry[key] * 100)}%</strong></span><input type="range" min={range.min} max={range.max} step="0.01" value={layer.geometry[key]} disabled={layer.systemManaged} onChange={(event) => updateLayer({ geometry: updateGeometry(layer.geometry, key, Number(event.target.value)) })} /></label>; })}</div>
      </> : scene ? <><div className="live-properties-heading"><span>场景属性</span><h3>{scene.title}</h3></div><label className="product-field"><span>场景名称</span><input value={scene.title} onChange={(event) => updateScene({ title: event.target.value })} /></label><div className="live-scene-summary"><span><strong>{scene.layers.length}</strong>个图层</span><span><strong>{scene.script.length}</strong>字话术</span></div><p className="live-structure-note">场景和图层集合来自已确认的剧本。需要增删时，请重新生成内容结构。</p></> : <EmptyBlock icon={Layers3} title="选择一个场景" />}</div> : null}
      {panel === "build" ? <div className="live-build-body"><section className="live-build-boundary"><header><strong>草稿执行边界</strong><StatusBadge label={matrix.canExecuteDraft ? "本地执行器可用" : "以任务状态为准"} tone={matrix.canExecuteDraft ? "success" : "warning"} /></header><p>只写入离线测试草稿，不排播、不开播。最终是否可执行由房间检查和真实任务队列决定。</p></section><section className="live-build-list"><header><h3>搭建步骤</h3><p>执行器会按以下顺序完成并逐步回读。</p></header><ol>{plan.buildPlan.operations.map((operation, index) => <li key={`${operation.kind}:${index}`}><span>{index + 1}</span><div><strong>{operationTitle(operation)}</strong><small>{operation.sceneIndex !== undefined ? `场景 ${operation.sceneIndex + 1}` : "按当前方案配置"}</small></div></li>)}</ol></section></div> : null}
      {panel === "execute" ? <div className="live-execute-body">
        {execution.data ? <ExecutionProgress execution={execution.data} onRetry={() => retry.mutate()} retrying={retry.isPending} onReconcile={() => reconcile.mutate()} reconciling={reconcile.isPending} /> : null}
        {terminalSyncError ? <section className="live-recovery-notice"><RotateCcw size={17} /><span><strong>执行结果暂未同步</strong><small>系统会继续读取最终回读结果，无需重新执行草稿任务。</small></span></section> : null}
        {!execution.data || reconciliationRecorded ? <>
          {reconciliationRecorded ? <section className="live-recovery-notice"><ClipboardCheck size={17} /><span><strong>旧任务已停止，不会自动重放</strong><small>已记录人工核对。请等待房间重新读取完成，再确认最新场景清单并创建一个新任务。</small></span></section> : null}
          <RoomInspectionSummary inspection={inspection.inspection} loading={inspection.isLoading} error={inspection.error} onInspect={inspection.inspect} />
          {result ? <section className="live-delete-confirm"><header><div><strong>清空当前测试草稿并重新生成</strong><small>以下场景会在同一任务中清空后重建</small></div><StatusBadge label={testRoomAllowed ? "测试房" : "当前房间不可覆盖"} tone={testRoomAllowed ? "warning" : "danger"} /></header><div>{result.scenes.map((item) => <label key={item.sceneId}><input type="checkbox" checked={confirmedSceneIds.includes(item.sceneId)} onChange={() => setConfirmedSceneIds((current) => toggle(current, item.sceneId))} /><span><strong>{item.name}</strong><small>{item.materialCount} 个素材</small></span></label>)}</div>{!testRoomAllowed ? <p className="is-danger">测试覆盖仅开放直播间 41172，且麦兔当前标题必须为 asser测试。</p> : null}{!roomMatches ? <p className="is-danger">页面填写的标题与麦兔当前标题不一致，请确认房间后重新读取。</p> : null}{!roomOffline ? <p className="is-danger">检测到正在直播或存在开播痕迹，已禁止修改。</p> : null}</section> : null}
          <label className="live-test-use-ack"><input type="checkbox" checked={testUseAcknowledged} onChange={(event) => setTestUseAcknowledged(event.target.checked)} /><span><strong>仅用于离线测试草稿，我确认有权将所选素材写入该测试房</strong><small>这不会把素材状态标记为版权已确认，也不会允许发布或开播。</small></span></label>
          {executeFailure ? <div className="live-friendly-error"><strong>{executeFailure.title}</strong><span>{executeFailure.detail}</span><small>{executeFailure.nextStep}</small></div> : null}
          <button className="product-primary-button live-execute-button" type="button" disabled={!canExecute || execute.isPending} onClick={() => execute.mutate()}><Check size={16} />{execute.isPending ? (hasUnsavedChanges ? "正在保存并创建草稿任务" : "正在创建草稿任务") : reconciliationRecorded ? "按最新现场重新创建任务" : hasUnsavedChanges ? "保存修改并写入麦兔测试草稿" : "写入麦兔测试草稿"}</button>
        </> : null}
      </div> : null}
    </aside>

    <footer className="live-editor-actions"><div><span>{releaseCandidate.error ? friendlyRequestError(releaseCandidate.error, "交付候选没有创建").detail : hasUnsavedChanges ? "有未保存的画面修改，写入时会先保存并重新编译" : save.isSuccess ? "场景修改已保存，并重新编译了图层顺序" : save.error ? "修改没有保存，请检查场景和素材" : "保存时会重新应用素材约束并生成连续图层顺序"}</span></div><StatusBadge label={executionStatusLabel(plan.executionStatus)} tone={statusTone(plan.executionStatus)} />{plan.release ? <a className="product-secondary-button" href={`/console/projects?project=${encodeURIComponent(plan.projectCode)}&tab=delivery`}><PackageCheck size={16} />查看交付</a> : plan.executionStatus === "maitu_complete" ? <button className="product-secondary-button" type="button" disabled={releaseCandidate.isPending} onClick={() => releaseCandidate.mutate()}><PackageCheck size={16} />创建交付候选</button> : null}<button className="product-secondary-button" type="button" onClick={() => setPanel("build")}><ListChecks size={16} />搭建清单</button><button className="product-secondary-button" type="button" disabled={save.isPending || !hasUnsavedChanges} onClick={() => save.mutate()}><Save size={16} />保存场景</button><button className="product-primary-button" type="button" onClick={() => setPanel("execute")}><CirclePlay size={16} />写入草稿</button></footer>
  </div>;
}

export function LiveRoomEditorProductPage({ search = window.location.search }: { search?: string }) {
  const params = new URLSearchParams(search);
  const requestedPlan = params.get("run") ?? "";
  const requestedProject = params.get("project") ?? "";
  const requestedRoomTitle = params.get("roomTitle") ?? "";
  const requestedInspection = params.get("inspection") ?? "";
  const requestedCreateKey = params.get("createKey") ?? "";
  const [selectedPlan, setSelectedPlan] = useState(requestedPlan);
  const [localPlan, setLocalPlan] = useState<FunctionalLiveRoomPlan>();
  const [inspectionCode, setInspectionCode] = useState(requestedInspection);
  const plans = useQuery({ queryKey: ["functional-live-room-plans"], queryFn: functionalLiveRoomsApi.list });
  const capability = useQuery({ queryKey: ["functional-live-room-plans", "maitu-capabilities"], queryFn: functionalLiveRoomsApi.maituCapabilities });
  useEffect(() => { if (requestedPlan) setSelectedPlan(requestedPlan); }, [requestedPlan]);
  const detail = useQuery({ queryKey: ["functional-live-room-plan", selectedPlan], queryFn: () => functionalLiveRoomsApi.get(selectedPlan), enabled: Boolean(selectedPlan) });
  useEffect(() => { if (detail.data) setLocalPlan(detail.data); }, [detail.data]);
  if (plans.isLoading || (selectedPlan && detail.isLoading && !localPlan)) return <LoadingBlock label="正在打开直播间方案" />;
  const plan = localPlan ?? detail.data;
  if (!plan) return <CreatePlanPanel requestedProject={requestedProject} requestedRoomTitle={requestedRoomTitle} requestedInspection={requestedInspection} requestedCreateKey={requestedCreateKey} recentPlans={plans.data ?? []} onOpenPlan={(code) => { setSelectedPlan(code); setLocalPlan(undefined); replaceLiveRoomQuery({ run: code }); }} onCreated={(created, nextInspection) => { setSelectedPlan(created.planCode); setLocalPlan(created); setInspectionCode(nextInspection ?? ""); replaceLiveRoomQuery({ project: created.projectCode, run: created.planCode, inspection: nextInspection, roomTitle: created.expectedTitle, createKey: undefined }); }} />;
  return <LiveRoomEditor plan={plan} matrix={capability.data ?? conservativeMaituCapabilityFallback} initialInspection={inspectionCode || requestedInspection} onPlan={(next) => { setSelectedPlan(next.planCode); setLocalPlan(next); if (next.roomInspectionCode) setInspectionCode(next.roomInspectionCode); replaceLiveRoomQuery({ project: next.projectCode, run: next.planCode, inspection: next.roomInspectionCode || inspectionCode || requestedInspection, roomTitle: next.expectedTitle, createKey: undefined }); }} onNew={() => { setSelectedPlan(""); setLocalPlan(undefined); setInspectionCode(""); replaceLiveRoomQuery({ run: undefined, project: undefined, inspection: undefined, roomTitle: undefined, createKey: undefined }); }} />;
}
