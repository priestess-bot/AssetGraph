import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, ChevronRight, ExternalLink, Film, Layers3, LoaderCircle, Play, Save, Send, Sparkles } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, Metric, SectionHeader, StatusBadge, formatDate, formatDuration } from "../workbench/components";
import { liveResearchApi } from "./api";
import { DEMO_ANALYSIS_RUNS, DEMO_PROJECTION, DEMO_TEMPLATES } from "./demoData";
import type { AnalysisRun, RoomTemplate, TemplateProjection, TemplateScene } from "./types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未能完成";
}

export function productionHandoffHref(templateCode: string, projection: TemplateProjection): string | undefined {
  if (!projection.revision || !projection.projection_fingerprint) return undefined;
  const params = new URLSearchParams({
    reference_template_code: templateCode,
    reference_template_revision_number: String(projection.revision),
    reference_template_projection_fingerprint: projection.projection_fingerprint,
  });
  return `/production/live-rooms?${params.toString()}`;
}

function jobBadge(status: AnalysisRun["status"]) {
  const meta = status === "succeeded" ? { label: "分析完成", tone: "success" as const } : status === "failed" ? { label: "分析失败", tone: "danger" as const } : status === "running" ? { label: "分析中", tone: "info" as const } : { label: "等待分析", tone: "warning" as const };
  return <StatusBadge label={meta.label} tone={meta.tone} />;
}

function TemplateList({ templates, selected, published, onSelect }: { templates: RoomTemplate[]; selected: string; published: boolean; onSelect: (code: string) => void }) {
  if (!templates.length) return <EmptyBlock icon={Layers3} title="没有符合条件的模板" />;
  return <ul className="research-template-list wb-list">{templates.map((template) => <li key={template.template_code}><button type="button" className={selected === template.template_code ? "active" : undefined} onClick={() => onSelect(template.template_code)}><div><strong>{template.title}</strong><code>{template.template_code}</code><small>r{published ? template.published_revision ?? template.latest_revision : template.latest_revision} · {formatDate(template.updated_at)}</small></div><span><StatusBadge label={published ? "已发布" : "待审核"} tone={published ? "success" : "warning"} /><ChevronRight size={15} aria-hidden="true" /></span></button></li>)}</ul>;
}

function AnalysisQueue({ runs, onCreateTemplate }: { runs: AnalysisRun[]; onCreateTemplate: (run: AnalysisRun) => void }) {
  return <section className="wb-section"><SectionHeader kicker="MULTIMODAL PIPELINE" title="分析任务" />{runs.length ? <div className="wb-table-wrap"><table className="wb-table"><thead><tr><th>采集场次</th><th>总进度</th><th>ASR</th><th>视觉</th><th>结构</th><th>结果</th></tr></thead><tbody>{runs.map((run) => <tr key={run.analysis_run_code}><td><code>{run.session_code}</code><small>{run.analysis_run_code}</small></td><td>{jobBadge(run.status)}<small>{Math.round(run.progress_percent)}%</small></td><td><StatusBadge label={run.asr_status} tone={run.asr_status === "succeeded" ? "success" : "warning"} /></td><td><StatusBadge label={run.visual_status} tone={run.visual_status === "succeeded" ? "success" : run.visual_status === "failed" ? "danger" : "warning"} /></td><td><StatusBadge label={run.structure_status} tone={run.structure_status === "succeeded" ? "success" : run.structure_status === "failed" ? "danger" : "warning"} /></td><td>{run.result_template_code ? <code>{run.result_template_code}</code> : run.status === "succeeded" ? <button type="button" className="wb-button" onClick={() => onCreateTemplate(run)}><Sparkles size={14} aria-hidden="true" />生成草稿</button> : <span>等待结构分析</span>}</td></tr>)}</tbody></table></div> : <EmptyBlock icon={Sparkles} title="暂无分析任务" detail="录屏封装后会依次运行 ASR、视觉与结构分析。" />}</section>;
}

function LayoutPreview({ template, sceneIndex, videoRef }: { template: RoomTemplate; sceneIndex: number; videoRef: RefObject<HTMLVideoElement | null> }) {
  const scene = template.scenes[sceneIndex];
  const seek = () => {
    if (!scene || !videoRef.current) return;
    videoRef.current.currentTime = scene.start_seconds;
    void videoRef.current.play().catch(() => undefined);
  };
  return <div className="research-template-preview">
    <div className="research-source-video">
      {template.source_playback_url ? <video ref={videoRef} src={template.source_playback_url} controls playsInline preload="metadata" aria-label="模板来源录屏" /> : <div className="research-template-placeholder"><Film size={30} strokeWidth={1.4} aria-hidden="true" /><strong>来源录屏</strong><span>{template.source_session_code}</span><button type="button" className="wb-button" disabled><Play size={14} aria-hidden="true" />播放流待接入</button></div>}
      {scene?.components.map((component, index) => <span key={component.component_code ?? `${component.role}-${index}`} className={`research-layout-box role-${component.role}`} style={{ left: `${component.x * 100}%`, top: `${component.y * 100}%`, width: `${component.width * 100}%`, height: `${component.height * 100}%` }} title={`${component.label} · 置信度 ${Math.round((component.confidence ?? 0) * 100)}%`}><b>{component.label}</b></span>)}
    </div>
    {scene ? <button type="button" className="research-preview-caption" onClick={seek}><span>{formatDuration(scene.start_seconds)} - {formatDuration(scene.end_seconds)}</span><strong>{scene.title}</strong><small>{scene.purpose}</small></button> : null}
  </div>;
}

function SceneEditor({ scene, index, active, readOnly = false, onActivate, onChange }: { scene: TemplateScene; index: number; active: boolean; readOnly?: boolean; onActivate: () => void; onChange: (scene: TemplateScene) => void }) {
  const fieldId = `scene-${index}`;
  return <article className={`research-scene-editor ${active ? "active" : ""}`} onClick={onActivate}>
    <div className="research-scene-number">{String(index + 1).padStart(2, "0")}</div>
    <div className="research-scene-fields">
      <div className="research-scene-row"><div className="wb-field"><label htmlFor={`${fieldId}-title`}>场景名称</label><input id={`${fieldId}-title`} className="wb-input" value={scene.title} disabled={readOnly} onChange={(event) => onChange({ ...scene, title: event.target.value })} /></div><div className="research-bound-fields"><div className="wb-field"><label htmlFor={`${fieldId}-in`}>IN</label><input id={`${fieldId}-in`} className="wb-input" type="number" step="0.1" value={scene.start_seconds} disabled={readOnly} onChange={(event) => onChange({ ...scene, start_seconds: Number(event.target.value) })} /></div><div className="wb-field"><label htmlFor={`${fieldId}-out`}>OUT</label><input id={`${fieldId}-out`} className="wb-input" type="number" step="0.1" value={scene.end_seconds} disabled={readOnly} onChange={(event) => onChange({ ...scene, end_seconds: Number(event.target.value) })} /></div></div></div>
      <div className="wb-field"><label htmlFor={`${fieldId}-purpose`}>场景目的</label><input id={`${fieldId}-purpose`} className="wb-input" value={scene.purpose} disabled={readOnly} onChange={(event) => onChange({ ...scene, purpose: event.target.value })} /></div>
      <div className="research-scene-row"><div className="wb-field"><label htmlFor={`${fieldId}-script`}>话术模式</label><textarea id={`${fieldId}-script`} className="wb-textarea" value={scene.script_pattern ?? ""} disabled={readOnly} onChange={(event) => onChange({ ...scene, script_pattern: event.target.value })} /></div><div className="wb-field"><label htmlFor={`${fieldId}-cue`}>互动提示</label><textarea id={`${fieldId}-cue`} className="wb-textarea" value={scene.interaction_cue ?? ""} disabled={readOnly} onChange={(event) => onChange({ ...scene, interaction_cue: event.target.value })} /></div></div>
      <div className="research-component-summary"><span>{scene.components.length} 个近似组件</span><span>{scene.material_slots.length} 个素材槽位</span>{scene.components.some((component) => (component.confidence ?? 0) < .75) ? <StatusBadge label="含低置信度推断" tone="warning" /> : <StatusBadge label="构图待人工确认" tone="info" />}</div>
    </div>
  </article>;
}

function ProjectionPanel({ template, projection }: { template: RoomTemplate; projection?: TemplateProjection }) {
  const referenceCapabilities = projection?.reference_capabilities ?? ["场景顺序", "时长节奏", "素材槽位需求"];
  const blocked = projection?.blocked_operations ?? ["insert_template_component", "set_exact_geometry"];
  const handoffHref = projection ? productionHandoffHref(template.template_code, projection) : undefined;
  return <section className="wb-section"><SectionHeader kicker="PRODUCTION HANDOFF" title="生产工作台投影" actions={<StatusBadge label={template.buildability === "executable" ? "可执行布局" : "仅参考"} tone={template.buildability === "executable" ? "success" : "warning"} />} /><div className="wb-section-body"><div className="research-projection-columns"><div><strong>允许参与规划</strong><ul>{referenceCapabilities.map((item) => <li key={item}><CheckCircle2 size={14} aria-hidden="true" />{item}</li>)}</ul></div><div><strong>明确禁止</strong><ul>{blocked.map((item) => <li key={item}><AlertTriangle size={14} aria-hidden="true" /><code>{item}</code></li>)}</ul></div></div>{projection?.warnings.map((warning) => <InlineNotice key={warning} tone="warning" title="投影约束">{warning}</InlineNotice>)}{handoffHref ? <a className="wb-button wb-button-primary research-production-link" href={handoffHref}><ExternalLink size={14} aria-hidden="true" />在生产工作台使用固定版本</a> : null}</div></section>;
}

function TemplateReview({ template, projection, readOnly = false, onChanged }: { template: RoomTemplate; projection?: TemplateProjection; readOnly?: boolean; onChanged: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [scenes, setScenes] = useState(template.scenes);
  const [activeScene, setActiveScene] = useState(0);
  const [reviewerNote, setReviewerNote] = useState("已核对场景边界、内容目的、素材槽位和推断构图");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setScenes(template.scenes); setActiveScene(0); setConfirmed(false); }, [template.template_code, template.latest_revision, template.scenes]);
  const invalidBoundaries = scenes.some((scene, index) => scene.start_seconds < 0 || scene.end_seconds <= scene.start_seconds || (index > 0 && scene.start_seconds < scenes[index - 1].end_seconds));
  const revisionMutation = useMutation({ mutationFn: () => liveResearchApi.createTemplateRevision(template.template_code, { expected_revision: template.latest_revision, reviewer_note: reviewerNote.trim(), source_session_code: template.source_session_code, scenes }), onSuccess: onChanged });
  const publishMutation = useMutation({ mutationFn: () => liveResearchApi.publishTemplate(template.template_code, template.latest_revision), onSuccess: onChanged });
  const updateScene = (index: number, value: TemplateScene) => setScenes((current) => current.map((scene, sceneIndex) => sceneIndex === index ? value : scene));

  return <div className="research-template-review">
    <section className="wb-section">
      <SectionHeader kicker={`${template.template_code} · r${template.latest_revision}`} title={template.title} actions={<><StatusBadge label="近似布局" tone="warning" /><StatusBadge label="reference_only" tone="info" /></>} />
      <div className="wb-section-body"><InlineNotice tone="warning" title="外部平面视频不能恢复真实图层">框选区域是归一化近似推断，不包含麦兔 layer ID、material ID、精确 z-index 或可替换关系。发布后仍只能指导结构与风格。</InlineNotice><LayoutPreview template={{ ...template, scenes }} sceneIndex={activeScene} videoRef={videoRef} /></div>
    </section>
    <section className="wb-section">
      <SectionHeader kicker="HUMAN REVIEW" title={`场景边界与结构 · ${scenes.length} 段`} />
      <div className="wb-section-body research-scene-list">{scenes.length ? scenes.map((scene, index) => <SceneEditor key={scene.scene_code ?? index} scene={scene} index={index} active={activeScene === index} readOnly={readOnly} onActivate={() => setActiveScene(index)} onChange={(value) => updateScene(index, value)} />) : <EmptyBlock icon={Layers3} title="结构分析尚未生成场景" />}</div>
    </section>
    {readOnly ? <section className="wb-section"><SectionHeader kicker="IMMUTABLE PUBLICATION" title="发布版本只读" /><div className="wb-section-body"><InlineNotice title="修改从草稿开始">此处固定展示已发布 projection。需要调整时请进入模板草稿创建新修订，当前发布版本不会改变。</InlineNotice></div></section> : <section className="wb-section">
      <SectionHeader kicker="REVIEW GATE" title="保存与发布" />
      <div className="wb-section-body research-publish-gate">
        <div className="research-gate-checks"><span className={scenes.length ? "passed" : "blocked"}>{scenes.length ? <Check size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}至少一个场景</span><span className={!invalidBoundaries ? "passed" : "blocked"}>{!invalidBoundaries ? <Check size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}时间边界有效且不重叠</span><span className="passed"><Check size={14} aria-hidden="true" />固定为 approximate / reference_only</span><span className="passed"><Check size={14} aria-hidden="true" />未包含原始互动内容</span></div>
        <div className="wb-field"><label htmlFor="reviewer-note">审核说明</label><textarea id="reviewer-note" className="wb-textarea" value={reviewerNote} onChange={(event) => setReviewerNote(event.target.value)} /></div>
        <div className="research-save-row"><button type="button" className="wb-button" disabled={!scenes.length || invalidBoundaries || !reviewerNote.trim() || revisionMutation.isPending} onClick={() => revisionMutation.mutate()}>{revisionMutation.isPending ? <LoaderCircle className="wb-spin" size={14} aria-hidden="true" /> : <Save size={14} aria-hidden="true" />}保存新修订</button><label className="research-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>我已确认场景边界、角色和近似布局边界</span></label><button type="button" className="wb-button wb-button-primary" disabled={!confirmed || invalidBoundaries || template.status === "published" || publishMutation.isPending} onClick={() => publishMutation.mutate()}><Send size={14} aria-hidden="true" />发布参考模板</button></div>
        {revisionMutation.error || publishMutation.error ? <InlineNotice tone="danger" title="模板操作失败">{errorMessage(revisionMutation.error ?? publishMutation.error)}</InlineNotice> : null}
      </div>
    </section>}
    <ProjectionPanel template={template} projection={projection} />
  </div>;
}

export function TemplatesPage({ published }: { published: boolean }) {
  const queryClient = useQueryClient();
  const [templateCode, setTemplateCode] = useState(new URLSearchParams(window.location.search).get("template")?.trim() ?? "");
  const analysisQuery = useQuery({ queryKey: ["live-research", "analysis-runs"], queryFn: liveResearchApi.listAnalysisRuns, refetchInterval: (query) => query.state.data?.some((item) => ["queued", "running"].includes(item.status)) ? 1800 : false });
  const templatesQuery = useQuery({ queryKey: ["live-research", "templates"], queryFn: liveResearchApi.listTemplates });
  const demoMode = analysisQuery.isError && templatesQuery.isError;
  const analyses = analysisQuery.data ?? (demoMode ? DEMO_ANALYSIS_RUNS : []);
  const templates = templatesQuery.data ?? (demoMode ? DEMO_TEMPLATES : []);
  const filtered = useMemo(() => templates.filter((template) => published ? Boolean(template.published_revision) : template.status !== "published"), [published, templates]);
  const selectedTemplateCode = filtered.some((item) => item.template_code === templateCode) ? templateCode : filtered[0]?.template_code ?? "";
  useEffect(() => {
    if (templateCode !== selectedTemplateCode) setTemplateCode(selectedTemplateCode);
  }, [selectedTemplateCode, templateCode]);
  const summary = filtered.find((item) => item.template_code === selectedTemplateCode);
  const detailQuery = useQuery({ queryKey: ["live-research", "template", selectedTemplateCode], queryFn: () => liveResearchApi.getTemplate(selectedTemplateCode), enabled: Boolean(summary) && !demoMode });
  const projectionQuery = useQuery({ queryKey: ["live-research", "projection", selectedTemplateCode], queryFn: () => liveResearchApi.getProjection(selectedTemplateCode), enabled: Boolean(summary?.published_revision) && !demoMode, retry: false });
  const template = detailQuery.data ?? summary;
  const projection = projectionQuery.data ?? (demoMode && template?.published_revision ? { ...DEMO_PROJECTION, template_code: template.template_code, revision: template.published_revision } : undefined);
  const sourceSessionCode = published ? projection?.source_session_code ?? template?.source_session_code : template?.source_session_code;
  const sourceSessionQuery = useQuery({ queryKey: ["live-research", "session", sourceSessionCode], queryFn: () => liveResearchApi.getCaptureSession(sourceSessionCode ?? ""), enabled: Boolean(sourceSessionCode) && !demoMode });
  const reviewTemplate = template && (!published || projection) ? {
    ...template,
    latest_revision: published ? projection!.revision : template.latest_revision,
    status: published ? "published" as const : template.status,
    source_session_code: sourceSessionCode ?? template.source_session_code,
    scenes: published ? projection!.scenes ?? [] : template.scenes,
    source_playback_url: template.source_playback_url ?? sourceSessionQuery.data?.playback_url,
  } : undefined;
  const createMutation = useMutation({
    mutationFn: liveResearchApi.materializeAnalysisTemplate,
    onSuccess: (created) => { setTemplateCode(created.template_code); void queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }); },
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] });
    void queryClient.invalidateQueries({ queryKey: ["live-research", "template", selectedTemplateCode] });
    void queryClient.invalidateQueries({ queryKey: ["live-research", "projection", selectedTemplateCode] });
  };
  const publishedCount = useMemo(() => templates.filter((item) => item.published_revision).length, [templates]);
  const draftCount = useMemo(() => templates.filter((item) => item.status !== "published").length, [templates]);

  return <div>
    {demoMode ? <InlineNotice tone="warning" title="当前展示模板工坊演示数据">真实分析结果和模板修订会在采集 Worker 完成后自动出现。</InlineNotice> : null}
    {!published ? <><div className="wb-metrics research-analysis-metrics"><Metric label="分析任务" value={analyses.length} /><Metric label="执行中" value={analyses.filter((item) => item.status === "running").length} /><Metric label="模板草稿" value={draftCount} /><Metric label="已发布参考模板" value={publishedCount} /></div><AnalysisQueue runs={analyses} onCreateTemplate={(run) => createMutation.mutate(run)} />{createMutation.error ? <InlineNotice tone="danger" title="无法生成模板草稿">{errorMessage(createMutation.error)}</InlineNotice> : null}</> : <InlineNotice title="发布版本不可变">已发布模板只作为固定版本投影到生产工作台；任何修改都会创建新的草稿修订。</InlineNotice>}
    <div className="wb-grid research-template-grid">
      <aside className="wb-section research-template-rail"><SectionHeader kicker={published ? "PUBLISHED" : "DRAFTS"} title={published ? "已发布模板" : "模板草稿"} /><TemplateList templates={filtered} selected={selectedTemplateCode} published={published} onSelect={setTemplateCode} /></aside>
      <div>{detailQuery.isLoading || (published && projectionQuery.isLoading) ? <section className="wb-section"><LoadingBlock label="正在读取固定模板版本" /></section> : published && projectionQuery.isError ? <section className="wb-section"><InlineNotice tone="danger" title="发布投影不可用">无法验证固定发布版本，已关闭展示与生产交接。</InlineNotice></section> : reviewTemplate ? <TemplateReview template={reviewTemplate} projection={projection} readOnly={published} onChanged={refresh} /> : <section className="wb-section"><EmptyBlock icon={Layers3} title={published ? "尚无已发布模板" : "尚无模板草稿"} detail={published ? "草稿通过人工审核后会产生不可变发布版本。" : "ASR、视觉和结构分析完成后生成草稿。"} /></section>}</div>
    </div>
  </div>;
}
