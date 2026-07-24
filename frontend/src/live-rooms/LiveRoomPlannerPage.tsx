import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Copy, FileCheck2, GitFork, MonitorUp, Send, WandSparkles } from "lucide-react";
import { assetLibraryApi } from "../assets/api";
import { contentProjectsApi } from "../content/api";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge } from "../workbench/components";
import { functionalLiveRoomsApi, type FunctionalLiveRoomPlan } from "./api";

function message(error: unknown): string { return error instanceof Error ? error.message : "操作未完成"; }
function toggle(values: string[], value: string): string[] { return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]; }

function tone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "ready" || status === "maitu_complete") return "success";
  if (status === "blocked") return "danger";
  if (status === "requested") return "warning";
  return "neutral";
}

function label(status: string): string {
  return ({ ready: "可生成草稿", blocked: "素材或约束阻断", not_requested: "尚未请求", requested: "等待麦兔 Worker", maitu_complete: "已由麦兔完成" } as Record<string, string>)[status] ?? status;
}

function gateTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "pass") return "success";
  if (status === "blocked") return "danger";
  if (status === "warning") return "warning";
  return "neutral";
}

function PlanDetail({ plan }: { plan: FunctionalLiveRoomPlan }) {
  const queryClient = useQueryClient();
  const [confirmed, setConfirmed] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneRoomId, setCloneRoomId] = useState("");
  const [cloneTitle, setCloneTitle] = useState("");
  const [traceVisible, setTraceVisible] = useState(false);
  const request = useMutation({ mutationFn: () => functionalLiveRoomsApi.confirmExecution(plan.planCode), onSuccess: (next) => { queryClient.setQueryData(["functional-live-room-plan", plan.planCode], next); void queryClient.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); } });
  const release = useMutation({ mutationFn: () => functionalLiveRoomsApi.createReleaseCandidate(plan.planCode), onSuccess: (next) => { queryClient.setQueryData(["functional-live-room-plan", plan.planCode], next); void queryClient.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); } });
  const clone = useMutation({ mutationFn: () => functionalLiveRoomsApi.clone(plan.planCode, { target_live_room_id: cloneRoomId, expected_title: cloneTitle }), onSuccess: (next) => { setCloneOpen(false); setCloneRoomId(""); setCloneTitle(""); queryClient.setQueryData(["functional-live-room-plan", next.planCode], next); void queryClient.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); } });
  const trace = useQuery({ queryKey: ["functional-live-room-trace", plan.planCode], queryFn: () => functionalLiveRoomsApi.getTrace(plan.planCode), enabled: traceVisible });
  return <div className="live-plan-detail">
    <section className="wb-section"><SectionHeader kicker={plan.planCode} title={plan.expectedTitle} actions={<div className="live-plan-badges"><StatusBadge label={label(plan.status)} tone={tone(plan.status)} /><StatusBadge label={label(plan.executionStatus)} tone={tone(plan.executionStatus)} /></div>} />
      <div className="live-plan-summary"><div><span>目标直播间</span><strong>{plan.targetLiveRoomId}</strong></div><div><span>生产变体</span><code>{plan.variantCode}</code></div><div><span>直播间配置</span><code>{plan.configurationCode}</code></div><div><span>开播动作</span><strong>已关闭</strong></div></div>
      {plan.blockedReasons.length ? <InlineNotice tone="danger" title="BuildPlan 已阻断">{plan.blockedReasons.join("；")}</InlineNotice> : <InlineNotice tone="info" title="当前计划仅生成草稿">计划中不包含开播操作。请求后仍须由已配置的麦兔 Worker 校验空白草稿并写入。</InlineNotice>}
    </section>
    <section className="wb-section"><SectionHeader kicker="STATIC GATES" title="输入与分支质量" /><div className="live-plan-summary">{plan.gateResults.map((gate) => <div key={gate.gate}><span>{gate.gate}</span><strong>{gate.ruleCode}</strong><StatusBadge label={gate.status} tone={gateTone(gate.status)} /></div>)}<div><span>预计时长</span><strong>{typeof plan.qualityReport.estimated_total_duration_ms === "number" ? `${Math.round(plan.qualityReport.estimated_total_duration_ms / 1000)} 秒` : "未计算"}</strong></div></div></section>
    <section className="wb-section"><SectionHeader kicker="MAITU SCENE BLUEPRINT" title="场景与图层" />
      <div className="live-scene-list">{plan.blueprint.scenes.map((scene) => <article key={scene.scene_code}><header><span>{scene.scene_code}</span><strong>{scene.title}</strong><code>{scene.shot_code}</code></header><p>{scene.script}</p><div>{scene.layers.map((layer) => <span key={`${scene.scene_code}:${layer.role}:${layer.asset_code}`}><b>{layer.z_order}</b>{layer.role}<code>{layer.asset_code}</code></span>)}</div></article>)}</div>
    </section>
    <section className="wb-section"><SectionHeader kicker={plan.buildPlan.build_plan_code ?? "BUILD PLAN"} title="麦兔草稿操作" actions={<StatusBadge label={plan.buildPlan.go_live ? "包含开播" : "不含开播"} tone={plan.buildPlan.go_live ? "danger" : "success"} />} />
      <ol className="live-operation-list">{plan.buildPlan.operations.map((operation, index) => <li key={`${operation.kind}:${index}`}><b>{index + 1}</b><span>{operation.kind}</span><code>{operation.scene_code ?? operation.asset_code ?? operation.script_block_code ?? ""}</code></li>)}</ol>
    </section>
    <section className="wb-section"><SectionHeader kicker="PROVENANCE" title="操作来源追溯" actions={<button type="button" className="wb-icon-button" aria-label="加载操作来源追溯" title="加载操作来源追溯" onClick={() => setTraceVisible((visible) => !visible)}><GitFork size={15} aria-hidden="true" /></button>} />
      {traceVisible && trace.isLoading ? <LoadingBlock label="正在加载操作来源" /> : null}
      {traceVisible && trace.data ? <div className="live-trace-list">{trace.data.operations.map((operation) => <article key={operation.operationId}><header><b>{operation.sortOrder}</b><strong>{operation.operationType}</strong><span>{operation.operationName}</span></header>{operation.targets.map((target) => <div key={`${operation.operationId}:${target.targetType}:${target.targetCode}`}><code>{target.targetCode}</code><span>{target.relationType}</span>{target.shot ? <small>{target.shot.shotCode}</small> : null}{target.programSegment ? <small>{target.programSegment.segmentCode}</small> : null}{target.scriptBlocks.map((block) => <small key={block.blockCode}>{block.blockCode}</small>)}</div>)}</article>)}</div> : null}
    </section>
    {trace.error ? <InlineNotice tone="danger" title="操作来源无法加载">{message(trace.error)}</InlineNotice> : null}
    <section className="live-request-panel"><div><span>发布候选</span><strong>{plan.release ? `${plan.release.releaseCode} · ${plan.release.status}` : "尚未创建"}</strong><small>{plan.release ? `Manifest ${plan.release.manifestCode}；仍待权利、执行授权和现场回读。` : "创建后固定内容链、素材快照、Blueprint、BuildPlan 和当前质量结果。"}</small></div>{plan.release ? <div className="live-plan-badges"><StatusBadge label={plan.release.status} tone="warning" /><code>{plan.release.snapshotArtifactCode}</code></div> : <button type="button" className="wb-button wb-button-secondary" disabled={plan.status !== "ready" || release.isPending} onClick={() => release.mutate()}><FileCheck2 size={15} aria-hidden="true" />创建发布候选</button>}</section>
    {release.error ? <InlineNotice tone="danger" title="发布候选未创建">{message(release.error)}</InlineNotice> : null}
    <section className="live-request-panel"><div><span>克隆到新草稿房间</span><strong>{plan.clonedFromPlanCode ? `来自 ${plan.clonedFromPlanCode}` : "复制业务输入，重新编译"}</strong><small>不会复制旧房间的现场、授权、执行、发布或交付状态。</small></div><button type="button" className="wb-button wb-button-secondary" onClick={() => setCloneOpen((open) => !open)}><Copy size={15} aria-hidden="true" />克隆</button></section>
    {cloneOpen ? <section className="live-request-panel"><div className="live-clone-fields"><label className="wb-field"><span>新直播间 ID</span><input className="wb-input" value={cloneRoomId} onChange={(event) => setCloneRoomId(event.target.value)} /></label><label className="wb-field"><span>新直播间标题</span><input className="wb-input" value={cloneTitle} onChange={(event) => setCloneTitle(event.target.value)} /></label></div><button type="button" className="wb-button wb-button-primary" disabled={clone.isPending || !cloneRoomId.trim() || !cloneTitle.trim()} onClick={() => clone.mutate()}><Copy size={15} aria-hidden="true" />创建新计划</button></section> : null}
    {clone.error ? <InlineNotice tone="danger" title="克隆计划未创建">{message(clone.error)}</InlineNotice> : null}
    <section className="live-request-panel"><div><span>人工确认后的 Worker 请求</span><strong>{plan.executionStatus === "requested" ? "已提交，等待麦兔 Worker 回读" : "尚未请求"}</strong><small>{typeof plan.executionEvidence.message === "string" ? plan.executionEvidence.message : "仅在指定空白、未开播草稿中执行。"}</small></div>{plan.executionStatus === "not_requested" ? <div className="live-request-action"><label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我已确认该目标是指定的空白未开播草稿</label><button type="button" className="wb-button wb-button-primary" disabled={!confirmed || request.isPending || plan.status !== "ready"} onClick={() => request.mutate()}><Send size={15} aria-hidden="true" />请求写入草稿</button></div> : null}</section>
    {request.error ? <InlineNotice tone="danger" title="草稿请求未提交">{message(request.error)}</InlineNotice> : null}
  </div>;
}

export function LiveRoomPlannerPage() {
  const queryClient = useQueryClient();
  const [selectedPlan, setSelectedPlan] = useState(""); const [projectCode, setProjectCode] = useState(""); const [roomId, setRoomId] = useState(""); const [title, setTitle] = useState(""); const [assetCodes, setAssetCodes] = useState<string[]>([]); const [groupCodes, setGroupCodes] = useState<string[]>([]); const [materialPackCodes, setMaterialPackCodes] = useState<string[]>([]);
  const projects = useQuery({ queryKey: ["content-projects"], queryFn: contentProjectsApi.list });
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const groups = useQuery({ queryKey: ["assets", "groups"], queryFn: assetLibraryApi.listGroups });
  const materialPacks = useQuery({ queryKey: ["assets", "packs"], queryFn: assetLibraryApi.listPacks });
  const plans = useQuery({ queryKey: ["functional-live-room-plans"], queryFn: functionalLiveRoomsApi.list });
  const usableProjects = useMemo(() => projects.data ?? [], [projects.data]);
  useEffect(() => { if (!projectCode && usableProjects[0]) setProjectCode(usableProjects[0].projectCode); }, [projectCode, usableProjects]);
  const activePlanCode = plans.data?.some((item) => item.planCode === selectedPlan) ? selectedPlan : plans.data?.[0]?.planCode ?? "";
  useEffect(() => { if (selectedPlan !== activePlanCode) setSelectedPlan(activePlanCode); }, [activePlanCode, selectedPlan]);
  const detail = useQuery({ queryKey: ["functional-live-room-plan", activePlanCode], queryFn: () => functionalLiveRoomsApi.get(activePlanCode), enabled: Boolean(activePlanCode) });
  const create = useMutation({ mutationFn: () => functionalLiveRoomsApi.create({ project_code: projectCode, target_live_room_id: roomId, expected_title: title, secondary_template_codes: [], asset_codes: assetCodes, group_codes: groupCodes, material_pack_codes: materialPackCodes }), onSuccess: (plan) => { setSelectedPlan(plan.planCode); void queryClient.invalidateQueries({ queryKey: ["functional-live-room-plans"] }); } });
  const submit = (event: FormEvent) => { event.preventDefault(); if (projectCode && roomId.trim() && title.trim() && (assetCodes.length || groupCodes.length || materialPackCodes.length)) create.mutate(); };
  const loading = projects.isLoading || assets.isLoading || groups.isLoading || materialPacks.isLoading || plans.isLoading;
  const problem = projects.error ?? assets.error ?? groups.error ?? materialPacks.error ?? plans.error;
  return <div className="live-room-layout"><aside className="wb-section live-plan-rail"><SectionHeader kicker="LIVE ROOM PLANS" title="直播间配置" />
    <form className="live-plan-form" onSubmit={submit}><label className="wb-field"><span>内容项目</span><select className="wb-input" value={projectCode} onChange={(event) => setProjectCode(event.target.value)}><option value="">选择已创建内容项目</option>{usableProjects.map((project) => <option key={project.projectCode} value={project.projectCode}>{project.title} · {project.projectCode}</option>)}</select></label><label className="wb-field"><span>直播间 ID</span><input className="wb-input" value={roomId} onChange={(event) => setRoomId(event.target.value)} required /></label><label className="wb-field"><span>直播间标题</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} required /></label><div className="live-selection"><span>已发布素材包</span>{materialPacks.data?.filter((pack) => pack.status === "published").map((pack) => <label key={pack.packCode}><input type="checkbox" checked={materialPackCodes.includes(pack.packCode)} onChange={() => setMaterialPackCodes((current) => toggle(current, pack.packCode))} /><span><strong>{pack.title}</strong><small>{pack.role} · r{pack.revisionNumber} · {pack.resolvedAssetCodes.length} 项</small></span></label>)}</div><div className="live-selection"><span>零散素材</span>{assets.data?.map((asset) => <label key={asset.assetCode}><input type="checkbox" checked={assetCodes.includes(asset.assetCode)} onChange={() => setAssetCodes((current) => toggle(current, asset.assetCode))} /><span><strong>{asset.title}</strong><small>{asset.materialRoles.join(" / ") || "未分类"} · {asset.executionCapability}</small></span></label>)}</div><div className="live-selection"><span>素材分组</span>{groups.data?.map((group) => <label key={group.groupCode}><input type="checkbox" checked={groupCodes.includes(group.groupCode)} onChange={() => setGroupCodes((current) => toggle(current, group.groupCode))} /><span><strong>{group.title}</strong><small>{group.assetCount} 项 · {group.groupCode}</small></span></label>)}</div>{create.error ? <InlineNotice tone="danger" title="无法生成 BuildPlan">{message(create.error)}</InlineNotice> : null}<button className="wb-button wb-button-primary" disabled={create.isPending || !projectCode || !roomId.trim() || !title.trim() || (!assetCodes.length && !groupCodes.length && !materialPackCodes.length)}><WandSparkles size={15} aria-hidden="true" />生成场景与 BuildPlan</button></form>
    <div className="live-plan-list">{plans.data?.map((plan) => <button key={plan.planCode} type="button" className={plan.planCode === activePlanCode ? "active" : undefined} onClick={() => setSelectedPlan(plan.planCode)}><span><strong>{plan.expectedTitle}</strong><code>{plan.planCode}</code><small>{plan.targetLiveRoomId}</small></span><StatusBadge label={label(plan.status)} tone={tone(plan.status)} /></button>)}</div></aside>
    <main className="live-room-main">{loading ? <LoadingBlock label="正在读取直播间配置数据" /> : problem ? <InlineNotice tone="danger" title="直播间工作台无法加载">{message(problem)}</InlineNotice> : detail.data ? <PlanDetail plan={detail.data} /> : <EmptyBlock icon={plans.data?.length ? CircleAlert : MonitorUp} title={plans.data?.length ? "选择一个直播间计划" : "创建第一个直播间计划"} detail="先完成内容项目和素材选择，系统会生成场景蓝图与草稿操作序列。" />}</main></div>;
}
