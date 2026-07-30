import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronRight,
  CirclePlay,
  Layers3,
  ListChecks,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { assetLibraryApi } from "../assets/api";
import { contentProjectsApi } from "../content/api";
import { PageHeader } from "../product/components";
import { EmptyBlock, LoadingBlock, StatusBadge } from "../workbench/components";
import { productCopy, productLabel } from "../workbench/productLanguage";
import {
  conservativeMaituCapabilityFallback,
  functionalLiveRoomsApi,
  type FunctionalLiveRoomBuildOperation,
  type FunctionalLiveRoomPlan,
  type MaituCapabilityMatrix,
} from "./api";

type Geometry = { x: number; y: number; width: number; height: number };
type DraftLayer = { key: string; role: string; assetCode: string; executionCapability: string; geometry: Geometry; zOrder: number };
type DraftScene = { key: string; shotCode: string; title: string; script: string; layers: DraftLayer[] };

const defaultGeometry: Geometry = { x: .12, y: .12, width: .76, height: .32 };
const roleOptions = ["background", "product_display", "digital_human", "brand_title", "promotion_text", "decoration_foreground", "supporting_video"];

function draftFromPlan(plan: FunctionalLiveRoomPlan): DraftScene[] {
  return plan.blueprint.scenes.map((scene, sceneIndex) => ({
    key: `${scene.scene_code}:${sceneIndex}`,
    shotCode: scene.shot_code,
    title: scene.title,
    script: scene.script,
    layers: scene.layers.map((layer, layerIndex) => ({
      key: `${scene.scene_code}:${layer.role}:${layerIndex}`,
      role: layer.role,
      assetCode: layer.asset_code,
      executionCapability: layer.execution_capability,
      geometry: { ...layer.normalized_geometry },
      zOrder: layer.z_order,
    })),
  }));
}

function capabilityStatus(status: string): { label: string; tone: "success" | "warning" | "neutral" } {
  if (status === "verified") return { label: "可自动完成", tone: "success" };
  if (status === "manual_only") return { label: "需人工完成", tone: "warning" };
  return { label: "暂不支持", tone: "neutral" };
}

function operationTitle(operation: FunctionalLiveRoomBuildOperation): string {
  const kind = operation.kind.toLowerCase();
  if (kind.includes("room") || kind.includes("title")) return "核对直播间与标题";
  if (kind.includes("scene")) return operation.sceneIndex === undefined ? "创建直播场景" : `创建第 ${operation.sceneIndex + 1} 个场景`;
  if (kind.includes("layer") || kind.includes("asset") || kind.includes("material")) return `放置${productLabel(operation.role ?? operation.layerType, "画面素材")}`;
  if (kind.includes("script") || kind.includes("speech")) return "填写本场话术";
  if (kind.includes("speaker") || kind.includes("human")) return "设置主播形象与声音";
  return productCopy(operation.operationName, "完成一项场景配置");
}

function CapabilityPanel({ matrix }: { matrix: MaituCapabilityMatrix }) {
  const visible = matrix.capabilities.filter((item) => item.requiredForDraft || ["read_room", "create_scene", "verify_reload_persistence"].includes(item.key));
  return <section className="live-capability-product">
    <header><div><span className="product-section-kicker">麦兔承接边界</span><h3>草稿能力</h3></div><StatusBadge label={matrix.canExecuteDraft ? "自动草稿可用" : "以人工交接为主"} tone={matrix.canExecuteDraft ? "success" : "warning"} /></header>
    <div>{visible.length ? visible.map((item) => { const status = capabilityStatus(item.status); return <article key={item.key}><span><strong>{productCopy(item.title, "草稿操作")}</strong><small>{item.requiredForDraft ? "生成草稿所需" : "辅助检查"}</small></span><StatusBadge label={status.label} tone={status.tone} /></article>; }) : <article><span><strong>自动写入能力尚未验证</strong><small>仍可生成完整人工操作清单</small></span><StatusBadge label="需人工完成" tone="warning" /></article>}</div>
  </section>;
}

function CreatePlanPanel({ requestedProject, onCreated }: { requestedProject: string; onCreated: (code: string) => void }) {
  const client = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: contentProjectsApi.list });
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const groups = useQuery({ queryKey: ["assets", "groups"], queryFn: assetLibraryApi.listGroups });
  const [projectCode, setProjectCode] = useState(requestedProject);
  const project = useQuery({ queryKey: ["project", projectCode], queryFn: () => contentProjectsApi.get(projectCode), enabled: Boolean(projectCode) });
  const [roomId, setRoomId] = useState("");
  const [title, setTitle] = useState("");
  const [assetCodes, setAssetCodes] = useState<string[]>([]);
  const [groupCodes, setGroupCodes] = useState<string[]>([]);
  useEffect(() => { if (!projectCode && projects.data?.[0]) setProjectCode(projects.data[0].projectCode); }, [projectCode, projects.data]);
  useEffect(() => {
    const content = project.data?.content;
    if (!content) return;
    if (!roomId && typeof content.target_live_room_id === "string") setRoomId(content.target_live_room_id);
    if (!title && project.data?.title) setTitle(project.data.title);
    if (!assetCodes.length && Array.isArray(content.selected_asset_codes)) setAssetCodes(content.selected_asset_codes.filter((item): item is string => typeof item === "string"));
    if (!groupCodes.length && Array.isArray(content.selected_group_codes)) setGroupCodes(content.selected_group_codes.filter((item): item is string => typeof item === "string"));
  }, [assetCodes.length, groupCodes.length, project.data, roomId, title]);
  const refs = project.data?.templateContributionDecisions ?? [];
  const primary = refs.find((item) => item.selectionRole === "primary");
  const create = useMutation({
    mutationFn: () => functionalLiveRoomsApi.create({
      project_code: projectCode, target_live_room_id: roomId.trim(), expected_title: title.trim(),
      primary_template_code: primary?.templateCode,
      secondary_template_codes: refs.filter((item) => item.selectionRole === "secondary").map((item) => item.templateCode),
      asset_codes: assetCodes, required_loose_asset_codes: assetCodes, group_codes: groupCodes,
      material_pack_codes: [], asset_gap_codes: [], material_role_overrides: {}, material_role_modes: {}, room_constraint_overrides: {},
    }),
    onSuccess: (plan) => { void client.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); onCreated(plan.planCode); },
  });
  const toggle = (items: string[], value: string) => items.includes(value) ? items.filter((item) => item !== value) : [...items, value];
  return <div className="live-create-product">
    <div className="live-create-heading"><div><span className="product-section-kicker">从内容项目生成</span><h2>创建直播间方案</h2><p>房间 ID 和标题来自项目，也可以在这里调整。至少选择一个素材组或零散素材。</p></div><div className="live-create-number"><strong>01</strong><span>方案输入</span></div></div>
    <div className="live-create-form">
      <label className="product-field"><span>内容项目</span><select value={projectCode} onChange={(event) => setProjectCode(event.target.value)}><option value="">选择项目</option>{projects.data?.map((item) => <option key={item.projectCode} value={item.projectCode}>{item.title}</option>)}</select></label>
      <label className="product-field"><span>直播间 ID</span><input value={roomId} onChange={(event) => setRoomId(event.target.value)} placeholder="麦兔中的目标草稿房间 ID" /></label>
      <label className="product-field wide"><span>直播间标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
    </div>
    <div className="live-create-assets"><section><header><strong>素材组</strong><span>选择 {groupCodes.length} 个</span></header><div>{groups.data?.map((item) => <label key={item.groupCode}><input type="checkbox" checked={groupCodes.includes(item.groupCode)} onChange={() => setGroupCodes((current) => toggle(current, item.groupCode))} /><span><strong>{item.title}</strong><small>{item.assetCount} 份素材</small></span></label>)}</div></section><section><header><strong>零散素材</strong><span>选择 {assetCodes.length} 份</span></header><div>{assets.data?.map((item) => <label key={item.assetCode}><input type="checkbox" checked={assetCodes.includes(item.assetCode)} onChange={() => setAssetCodes((current) => toggle(current, item.assetCode))} /><img src={assetLibraryApi.previewUrl(item.assetCode, "thumbnail")} alt="" /><span><strong>{item.title}</strong><small>{item.materialRoles.map((role) => productLabel(role, "素材")).join("、") || "待设置用途"}</small></span></label>)}</div></section></div>
    {create.error ? <div className="product-inline-error">方案没有生成，请检查项目、房间和素材是否完整。</div> : null}
    <footer><a className="product-secondary-button" href="/assets">管理素材</a><button className="product-primary-button" type="button" disabled={!projectCode || !roomId.trim() || !title.trim() || (!assetCodes.length && !groupCodes.length) || create.isPending} onClick={() => create.mutate()}><CirclePlay size={16} />{create.isPending ? "正在生成" : "生成直播间方案"}</button></footer>
  </div>;
}

function LiveRoomEditor({ plan, matrix, onPlan }: { plan: FunctionalLiveRoomPlan; matrix: MaituCapabilityMatrix; onPlan: (plan: FunctionalLiveRoomPlan) => void }) {
  const client = useQueryClient();
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const [draft, setDraft] = useState<DraftScene[]>(() => draftFromPlan(plan));
  const [sceneIndex, setSceneIndex] = useState(0);
  const [layerIndex, setLayerIndex] = useState<number | undefined>();
  const [panel, setPanel] = useState<"properties" | "build">("properties");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setDraft(draftFromPlan(plan)); setSceneIndex(0); setLayerIndex(undefined); }, [plan.planCode]);
  const scene = draft[sceneIndex];
  const layer = layerIndex === undefined ? undefined : scene?.layers[layerIndex];
  const asset = (code: string) => assets.data?.find((item) => item.assetCode === code);
  const updateScene = (next: Partial<DraftScene>) => setDraft((current) => current.map((item, index) => index === sceneIndex ? { ...item, ...next } : item));
  const updateLayer = (next: Partial<DraftLayer>) => setDraft((current) => current.map((item, index) => index === sceneIndex ? { ...item, layers: item.layers.map((entry, position) => position === layerIndex ? { ...entry, ...next } : entry) } : item));
  const moveScene = (offset: -1 | 1) => setDraft((current) => { const target = sceneIndex + offset; if (target < 0 || target >= current.length) return current; const next = [...current]; [next[sceneIndex], next[target]] = [next[target], next[sceneIndex]]; setSceneIndex(target); return next; });
  const save = useMutation({
    mutationFn: () => functionalLiveRoomsApi.reviseBlueprint(plan.planCode, { scenes: draft.map((item, index) => ({ shot_code: item.shotCode || `shot-${index + 1}`, sort_order: index, title: item.title, script: item.script, layers: item.layers.map((entry) => ({ role: entry.role, asset_code: entry.assetCode, geometry: entry.geometry, z_order: entry.zOrder })) })) }),
    onSuccess: (next) => { onPlan(next); client.setQueryData(["functional-live-room-plan", next.planCode], next); void client.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); },
  });
  const execute = useMutation({ mutationFn: () => functionalLiveRoomsApi.confirmExecution(plan.planCode), onSuccess: onPlan });
  const sync = useMutation({ mutationFn: () => functionalLiveRoomsApi.syncExecution(plan.planCode), onSuccess: onPlan });
  const addScene = () => { const next: DraftScene = { key: crypto.randomUUID(), shotCode: `shot-${draft.length + 1}`, title: `新场景 ${draft.length + 1}`, script: "", layers: [] }; setDraft((current) => [...current, next]); setSceneIndex(draft.length); setLayerIndex(undefined); };
  const addLayer = () => { if (!scene || !assets.data?.[0]) return; const selected = assets.data[0]; const next: DraftLayer = { key: crypto.randomUUID(), role: selected.materialRoles[0] ?? "product_display", assetCode: selected.assetCode, executionCapability: selected.executionCapability, geometry: defaultGeometry, zOrder: (scene.layers.at(-1)?.zOrder ?? 0) + 1 }; updateScene({ layers: [...scene.layers, next] }); setLayerIndex(scene.layers.length); };
  const status = plan.executionStatus;
  return <div className="live-editor-product">
    <header className="live-editor-topbar"><div><a href="/projects">内容项目</a><ChevronRight size={14} /><span>{plan.expectedTitle}</span></div><div><span>直播间 ID：<strong>{plan.targetLiveRoomId}</strong></span><StatusBadge label={productLabel(plan.status, "方案编辑中")} tone={plan.status === "ready" ? "success" : "warning"} /></div></header>
    <aside className="live-editor-outline">
      <header><div><span>场景与图层</span><strong>{draft.length} 个场景</strong></div><button className="product-icon-button" type="button" title="新增场景" onClick={addScene}><Plus size={16} /></button></header>
      <div className="live-scene-outline">{draft.map((item, index) => <section key={item.key} className={index === sceneIndex ? "active" : ""}><button type="button" onClick={() => { setSceneIndex(index); setLayerIndex(undefined); }}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.title || "未命名场景"}</strong><small>{item.layers.length} 个图层</small></button>{index === sceneIndex ? <div>{item.layers.slice().sort((a,b) => b.zOrder-a.zOrder).map((entry) => { const actualIndex = item.layers.findIndex((candidate) => candidate.key === entry.key); return <button key={entry.key} type="button" className={actualIndex === layerIndex ? "selected" : ""} onClick={() => setLayerIndex(actualIndex)}><Layers3 size={13} /><span><strong>{asset(entry.assetCode)?.title ?? productLabel(entry.role, "画面素材")}</strong><small>{productLabel(entry.role, "图层")}</small></span></button>; })}<button className="add-layer" type="button" onClick={addLayer}><Plus size={13} />添加图层</button></div> : null}</section>)}</div>
      <footer><button type="button" title="上移场景" disabled={sceneIndex === 0} onClick={() => moveScene(-1)}><ArrowUp size={15} /></button><button type="button" title="下移场景" disabled={sceneIndex >= draft.length - 1} onClick={() => moveScene(1)}><ArrowDown size={15} /></button><button type="button" title="删除场景" disabled={draft.length <= 1} onClick={() => { setDraft((current) => current.filter((_, index) => index !== sceneIndex)); setSceneIndex(Math.max(0, sceneIndex - 1)); setLayerIndex(undefined); }}><Trash2 size={15} /></button></footer>
    </aside>
    <main className="live-editor-canvas-area">
      <div className="live-canvas-toolbar"><span>9:16 直播画面</span><small>拖动数值时画布实时更新</small></div>
      <div className="live-canvas-stage"><div className="live-phone-canvas"><div className="live-safe-top">标题安全区</div>{scene?.layers.slice().sort((a,b) => a.zOrder-b.zOrder).map((entry) => { const source = asset(entry.assetCode); const selected = entry.key === layer?.key; return <button key={entry.key} type="button" className={selected ? "selected" : ""} style={{ left: `${entry.geometry.x*100}%`, top: `${entry.geometry.y*100}%`, width: `${entry.geometry.width*100}%`, height: `${entry.geometry.height*100}%`, zIndex: entry.zOrder + 20 }} onClick={() => setLayerIndex(scene.layers.findIndex((item) => item.key === entry.key))}>{source?.mediaKind === "image" ? <img src={assetLibraryApi.previewUrl(entry.assetCode, "thumbnail")} alt={source.title} /> : <span>{source?.title ?? productLabel(entry.role, "素材")}</span>}</button>; })}<div className="live-canvas-table">建议桌面区域</div><div className="live-canvas-caption">{scene?.script || "当前场景还没有话术"}</div></div></div>
      <div className="live-scene-script"><label className="product-field"><span>当前场景话术</span><textarea rows={3} value={scene?.script ?? ""} onChange={(event) => updateScene({ script: event.target.value })} placeholder="输入主播在这个场景中的主要话术" /></label></div>
    </main>
    <aside className="live-editor-properties">
      <nav><button type="button" className={panel === "properties" ? "active" : ""} onClick={() => setPanel("properties")}>属性</button><button type="button" className={panel === "build" ? "active" : ""} onClick={() => setPanel("build")}>操作清单</button></nav>
      {panel === "properties" ? <div className="live-properties-body">{layer ? <>
        <div className="live-properties-heading"><span className="product-section-kicker">图层属性</span><h3>{asset(layer.assetCode)?.title ?? "画面素材"}</h3></div>
        <label className="product-field"><span>使用素材</span><select value={layer.assetCode} onChange={(event) => { const selected = asset(event.target.value); updateLayer({ assetCode: event.target.value, role: selected?.materialRoles[0] ?? layer.role, executionCapability: selected?.executionCapability ?? layer.executionCapability }); }}>{assets.data?.map((item) => <option key={item.assetCode} value={item.assetCode}>{item.title}</option>)}</select></label>
        <label className="product-field"><span>画面用途</span><select value={layer.role} onChange={(event) => updateLayer({ role: event.target.value })}>{roleOptions.map((item) => <option key={item} value={item}>{productLabel(item, "其他图层")}</option>)}</select></label>
        <div className="live-geometry-grid">{(["x","y","width","height"] as const).map((key) => <label key={key}><span>{({ x: "左侧", y: "顶部", width: "宽度", height: "高度" } as const)[key]}</span><input type="number" min="0" max="1" step="0.01" value={layer.geometry[key]} onChange={(event) => updateLayer({ geometry: { ...layer.geometry, [key]: Math.max(0, Math.min(1, Number(event.target.value))) } })} /></label>)}</div>
        <label className="product-field"><span>图层顺序</span><input type="number" min="0" max="100" value={layer.zOrder} onChange={(event) => updateLayer({ zOrder: Number(event.target.value) })} /></label>
        <div className="live-layer-actions"><button className="product-secondary-button" type="button" onClick={() => { updateScene({ layers: scene.layers.filter((_, index) => index !== layerIndex) }); setLayerIndex(undefined); }}><Trash2 size={15} />移除图层</button></div>
      </> : scene ? <>
        <div className="live-properties-heading"><span className="product-section-kicker">场景属性</span><h3>{scene.title}</h3></div>
        <label className="product-field"><span>场景名称</span><input value={scene.title} onChange={(event) => updateScene({ title: event.target.value })} /></label>
        <div className="live-scene-summary"><span><strong>{scene.layers.length}</strong>个图层</span><span><strong>{scene.script.length}</strong>字话术</span></div>
        <button className="product-secondary-button" type="button" onClick={addLayer}><Plus size={15} />添加图层</button>
      </> : <EmptyBlock icon={Layers3} title="选择一个场景" />}</div> : <div className="live-build-body"><CapabilityPanel matrix={matrix} /><section className="live-build-list"><header><span className="product-section-kicker">搭建步骤</span><h3>麦兔操作清单</h3><p>按顺序完成以下步骤；自动能力不可用时，可直接交给搭建人员执行。</p></header><ol>{plan.buildPlan.operations.map((operation,index) => <li key={`${operation.kind}:${index}`}><span>{index+1}</span><div><strong>{operationTitle(operation)}</strong><small>{operation.sceneIndex !== undefined ? `场景 ${operation.sceneIndex+1}` : operation.assetOriginalFilename ? `素材：${operation.assetOriginalFilename}` : "按当前方案配置"}</small></div><StatusBadge label={productLabel(operation.status, "待处理")} tone={operation.status === "completed" ? "success" : "neutral"} /></li>)}</ol></section></div>}
    </aside>
    <footer className="live-editor-actions"><div><span>{save.isSuccess ? "场景修改已保存为新版本" : save.error ? "修改没有保存，请检查场景和素材" : "修改会保存为新的方案版本"}</span></div><StatusBadge label={productLabel(status, status === "not_requested" ? "尚未写入草稿" : "正在处理草稿")} tone={status === "maitu_succeeded" ? "success" : status === "maitu_failed" || status === "maitu_reconcile_required" ? "warning" : "neutral"} /><button className="product-secondary-button" type="button" onClick={() => setPanel("build")}><ListChecks size={16} />查看操作清单</button>{["requested","maitu_running","maitu_reconcile_required","maitu_failed"].includes(status) ? <button className="product-secondary-button" type="button" disabled={sync.isPending} onClick={() => sync.mutate()}><RefreshCw size={16} />同步草稿结果</button> : null}<button className="product-secondary-button" type="button" disabled={save.isPending} onClick={() => save.mutate()}><Save size={16} />保存场景</button>{status === "not_requested" ? <label className="live-execution-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>目标是空白未开播草稿</span></label> : null}<button className="product-primary-button" type="button" disabled={!matrix.canExecuteDraft || status !== "not_requested" || !confirmed || execute.isPending || plan.status !== "ready"} onClick={() => execute.mutate()}><Check size={16} />{matrix.canExecuteDraft ? "写入麦兔草稿" : "自动写入暂不可用"}</button></footer>
  </div>;
}

export function LiveRoomEditorProductPage({ search = window.location.search }: { search?: string }) {
  const params = new URLSearchParams(search);
  const requestedPlan = params.get("run") ?? "";
  const requestedProject = params.get("project") ?? "";
  const [selectedPlan, setSelectedPlan] = useState(requestedPlan);
  const plans = useQuery({ queryKey: ["functional-live-room-plans"], queryFn: functionalLiveRoomsApi.list });
  const capability = useQuery({ queryKey: ["functional-live-room-plans", "maitu-capabilities"], queryFn: functionalLiveRoomsApi.maituCapabilities });
  useEffect(() => { if (requestedPlan) setSelectedPlan(requestedPlan); }, [requestedPlan]);
  const matching = useMemo(() => (plans.data ?? []).filter((item) => !requestedProject || item.projectCode === requestedProject), [plans.data, requestedProject]);
  useEffect(() => { if (!selectedPlan && matching[0]) setSelectedPlan(matching[0].planCode); }, [matching, selectedPlan]);
  const detail = useQuery({ queryKey: ["functional-live-room-plan", selectedPlan], queryFn: () => functionalLiveRoomsApi.get(selectedPlan), enabled: Boolean(selectedPlan) });
  const [localPlan, setLocalPlan] = useState<FunctionalLiveRoomPlan>();
  useEffect(() => { if (detail.data) setLocalPlan(detail.data); }, [detail.data]);
  if (plans.isLoading || (selectedPlan && detail.isLoading)) return <LoadingBlock label="正在打开直播间方案" />;
  const plan = localPlan ?? detail.data;
  if (!plan) return <div className="product-page live-room-product-page"><PageHeader eyebrow="直播间制作" title="直播间配置" description="从内容项目和选定素材生成可编辑的 9:16 场景，并交付为麦兔草稿或人工操作清单。" /><CreatePlanPanel requestedProject={requestedProject} onCreated={(code) => { setSelectedPlan(code); setLocalPlan(undefined); }} /></div>;
  return <LiveRoomEditor plan={plan} matrix={capability.data ?? conservativeMaituCapabilityFallback} onPlan={setLocalPlan} />;
}
