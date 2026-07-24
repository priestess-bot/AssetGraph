import { type FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CheckCircle2, CircleX, Download, Film, RefreshCw, Send } from "lucide-react";
import { contentProjectsApi } from "../content/api";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge } from "../workbench/components";
import { functionalVideosApi, type FunctionalVideoPlan, type VideoTimelineRevision } from "./api";

function text(error: unknown): string { return error instanceof Error ? error.message : "操作未完成"; }
function bytes(value?: number): string { return typeof value === "number" ? value < 1024 * 1024 ? `${Math.round(value / 1024)} KB` : `${(value / (1024 * 1024)).toFixed(1)} MB` : "--"; }
function jobTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" { return status === "succeeded" ? "success" : status === "failed" ? "danger" : status === "running" ? "info" : "warning"; }
function jobLabel(status: string): string { return ({ queued: "等待渲染 Worker", running: "正在渲染", succeeded: "渲染完成", failed: "渲染失败" } as Record<string, string>)[status] ?? status; }
function stageLabel(stage: string): string { return ({ brief_generation: "内容摘要", script_generation: "脚本", shot_planning: "镜头规划", asset_selection: "素材选择", voice_synthesis: "配音", subtitle_generation: "字幕", rendering: "渲染", quality_check: "质量检查" } as Record<string, string>)[stage] ?? stage; }
function stageTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" { return status === "succeeded" ? "success" : status === "failed" ? "danger" : status === "running" ? "info" : "neutral"; }
function timelineClips(timeline: FunctionalVideoPlan["productionTimeline"]) { return timeline.tracks.find((track) => track.track_kind === "video")?.clips ?? []; }
function timelineDiff(current: FunctionalVideoPlan["productionTimeline"], previous?: VideoTimelineRevision["productionTimeline"]): string[] {
  if (!previous) return ["首个时间轴修订"];
  const currentCodes = timelineClips(current).map((clip) => clip.clip_code);
  const previousCodes = timelineClips(previous).map((clip) => clip.clip_code);
  const changes = [currentCodes.join(" / ") === previousCodes.join(" / ") ? "镜头顺序未变" : `镜头顺序 ${previousCodes.join(" / ")} -> ${currentCodes.join(" / ")}`];
  const durationDelta = current.global_end_ms - previous.global_end_ms;
  if (durationDelta) changes.push(`总时长 ${durationDelta > 0 ? "+" : ""}${(durationDelta / 1000).toFixed(1)} 秒`);
  return changes;
}

function TimelineRevisionHistory({ plan }: { plan: FunctionalVideoPlan }) {
  const revisions = useQuery({ queryKey: ["functional-video", plan.planCode, "timeline-revisions"], queryFn: () => functionalVideosApi.listTimelineRevisions(plan.planCode) });
  if (revisions.isLoading) return <div className="video-timeline-history"><small>正在读取修订历史</small></div>;
  if (revisions.error) return <div className="video-timeline-history"><InlineNotice tone="warning" title="时间轴历史不可用">{text(revisions.error)}</InlineNotice></div>;
  const history = revisions.data ?? [];
  const current = history.find((revision) => revision.revisionNumber === plan.timelineRevision);
  const previous = history.find((revision) => revision.revisionNumber === plan.timelineRevision - 1);
  return <div className="video-timeline-history"><div><strong>修订历史</strong><small>{timelineDiff(plan.productionTimeline, previous?.productionTimeline).join(" · ")}</small></div><ol>{history.map((revision) => <li key={revision.revisionNumber}><span><strong>r{revision.revisionNumber}</strong><small>{timelineClips(revision.productionTimeline).map((clip) => clip.clip_code).join(" / ")} · {(revision.productionTimeline.global_end_ms / 1000).toFixed(1)} 秒</small></span><StatusBadge label={revision.revisionNumber === current?.revisionNumber ? "当前" : revision.actorId} tone={revision.revisionNumber === current?.revisionNumber ? "info" : "neutral"} /></li>)}</ol></div>;
}

function TimelineEditor({ plan }: { plan: FunctionalVideoPlan }) {
  const queryClient = useQueryClient();
  const videoTrack = plan.productionTimeline.tracks.find((track) => track.track_kind === "video");
  const [clips, setClips] = useState(() => videoTrack?.clips.map((clip) => ({ clipCode: clip.clip_code, durationMs: clip.timeline_range.duration_ms, transition: clip.transition ?? "cut" })) ?? []);
  useEffect(() => setClips(videoTrack?.clips.map((clip) => ({ clipCode: clip.clip_code, durationMs: clip.timeline_range.duration_ms, transition: clip.transition ?? "cut" })) ?? []), [plan.timelineRevision, videoTrack]);
  const update = useMutation({ mutationFn: () => functionalVideosApi.updateTimeline(plan.planCode, { expected_revision: plan.timelineRevision, video_clips: clips.map((clip) => ({ clip_code: clip.clipCode, duration_ms: clip.durationMs, transition: clip.transition })) }), onSuccess: (next) => { queryClient.setQueryData(["functional-video", plan.planCode], next); void queryClient.invalidateQueries({ queryKey: ["functional-videos"] }); void queryClient.invalidateQueries({ queryKey: ["functional-video", plan.planCode, "timeline-revisions"] }); } });
  const totalSeconds = clips.reduce((sum, clip) => sum + clip.durationMs, 0) / 1000;
  const updateClip = (index: number, changes: Partial<(typeof clips)[number]>) => setClips((current) => current.map((clip, clipIndex) => clipIndex === index ? { ...clip, ...changes } : clip));
  const moveClip = (index: number, offset: number) => setClips((current) => {
    const destination = index + offset;
    if (destination < 0 || destination >= current.length) return current;
    const next = [...current];
    [next[index], next[destination]] = [next[destination]!, next[index]!];
    return next;
  });
  return <section className="wb-section"><SectionHeader kicker={`TIMELINE r${plan.timelineRevision}`} title="时间轴" actions={<StatusBadge label={`${totalSeconds.toFixed(1)} 秒`} tone="info" />} /><div className="video-timeline">{clips.map((clip) => <div key={clip.clipCode} style={{ flexGrow: Math.max(1, clip.durationMs) }}><span>{clip.clipCode}</span><strong>{(clip.durationMs / 1000).toFixed(1)}s</strong><small>{videoTrack?.clips.find((item) => item.clip_code === clip.clipCode)?.source_range?.asset_code ?? "voice"} · {clip.transition}</small></div>)}</div><div className="video-timeline-editor">{clips.map((clip, index) => <div key={clip.clipCode}><code>{clip.clipCode}</code><div className="video-clip-order"><button type="button" className="wb-icon-button" title="上移镜头" aria-label={`上移 ${clip.clipCode}`} disabled={plan.jobStatus !== "queued" || index === 0} onClick={() => moveClip(index, -1)}><ArrowUp size={14} aria-hidden="true" /></button><button type="button" className="wb-icon-button" title="下移镜头" aria-label={`下移 ${clip.clipCode}`} disabled={plan.jobStatus !== "queued" || index === clips.length - 1} onClick={() => moveClip(index, 1)}><ArrowDown size={14} aria-hidden="true" /></button></div><label className="wb-field"><span>时长（毫秒）</span><input className="wb-input" type="number" min="250" max="120000" value={clip.durationMs} disabled={plan.jobStatus !== "queued"} onChange={(event) => updateClip(index, { durationMs: Number(event.target.value) })} /></label><label className="wb-field"><span>转场</span><select className="wb-input" value={clip.transition} disabled={plan.jobStatus !== "queued"} onChange={(event) => updateClip(index, { transition: event.target.value })}><option value="cut">cut</option><option value="fade">fade</option><option value="fade_out">fade_out</option></select></label></div>)}</div><TimelineRevisionHistory plan={plan} />{plan.jobStatus === "queued" ? <div className="wb-form-actions"><button type="button" className="wb-button wb-button-primary" disabled={update.isPending || totalSeconds < 30 || totalSeconds > 120} onClick={() => update.mutate()}>保存时间轴修订</button></div> : <InlineNotice tone="warning" title="时间轴已锁定">渲染任务已被领取或结束。请创建新的成片分支进行调整。</InlineNotice>}{update.error ? <InlineNotice tone="danger" title="时间轴未保存">{text(update.error)}</InlineNotice> : null}</section>;
}

function WorkflowPanel({ plan }: { plan: FunctionalVideoPlan }) {
  if (!plan.workflowStages.length) return null;
  return <section className="wb-section"><SectionHeader kicker="WORKFLOW RUN" title="生产阶段" actions={<StatusBadge label={`${plan.workflowStages.filter((stage) => stage.status === "succeeded").length}/${plan.workflowStages.length}`} tone="info" />} /><ol className="video-workflow">{plan.workflowStages.map((stage) => <li key={`${stage.stageOrder}:${stage.stageName}`}><span>{stage.stageOrder}</span><div><strong>{stageLabel(stage.stageName)}</strong><small>attempt {stage.attempt}{stage.errorCode ? ` · ${stage.errorCode}` : ""}</small>{stage.errorMessage ? <small className="video-stage-error">{stage.errorMessage}</small> : null}</div><StatusBadge label={stage.status} tone={stageTone(stage.status)} /></li>)}</ol></section>;
}

function QualityPanel({ plan }: { plan: FunctionalVideoPlan }) {
  const checks = Object.entries(plan.qualityReport.checks);
  if (!checks.length) return null;
  const passed = plan.qualityReport.passed === true;
  return <section className="wb-section"><SectionHeader kicker="QC REPORT" title="质量检查" actions={<StatusBadge label={passed ? "通过" : "未通过"} tone={passed ? "success" : "danger"} />} /><ul className="video-quality-checks">{checks.map(([key, passedCheck]) => <li key={key}>{passedCheck ? <CheckCircle2 size={15} aria-hidden="true" /> : <CircleX size={15} aria-hidden="true" />}<code>{key}</code><StatusBadge label={passedCheck ? "pass" : "blocked"} tone={passedCheck ? "success" : "danger"} /></li>)}</ul></section>;
}

function Detail({ plan }: { plan: FunctionalVideoPlan }) {
  const queryClient = useQueryClient();
  const retry = useMutation({ mutationFn: () => functionalVideosApi.retry(plan.planCode), onSuccess: (next) => { queryClient.setQueryData(["functional-video", plan.planCode], next); void queryClient.invalidateQueries({ queryKey: ["functional-videos"] }); } });
  const videoUrl = plan.artifacts.find((artifact) => artifact.artifact_key === "video")?.download_url;
  return <div className="video-plan-detail"><section className="wb-section"><SectionHeader kicker={plan.planCode} title={plan.title} actions={<StatusBadge label={jobLabel(plan.jobStatus)} tone={jobTone(plan.jobStatus)} />} /><div className="video-plan-summary"><div><span>渲染任务</span><code>{plan.videoJobCode}</code></div><div><span>当前阶段</span><strong>{plan.currentStage ? stageLabel(plan.currentStage) : "等待 Worker"}</strong></div><div><span>进度</span><strong>{plan.progressPercent}%</strong></div><div><span>画布</span><strong>{plan.renderProfile.canvas ? `${plan.renderProfile.canvas.width}x${plan.renderProfile.canvas.height}` : "--"}</strong></div></div><div className="video-progress"><i style={{ width: `${plan.progressPercent}%` }} /></div>{plan.errorMessage ? <InlineNotice tone="danger" title="渲染任务失败">{plan.errorMessage}</InlineNotice> : <InlineNotice tone="info" title="已固定内容项目输入">剧本与镜头来自内容项目；当前视觉源为已验证的基线素材，等待本地渲染 Worker 执行。</InlineNotice>}</section>{videoUrl ? <section className="wb-section"><SectionHeader kicker="RENDER PREVIEW" title="成片预览" /><video className="video-render-preview" controls playsInline src={videoUrl} /></section> : null}<WorkflowPanel plan={plan} /><TimelineEditor plan={plan} /><QualityPanel plan={plan} /><section className="wb-section"><SectionHeader kicker="ARTIFACTS" title="成片与产物" actions={plan.jobStatus === "failed" ? <button type="button" className="wb-button" disabled={retry.isPending} onClick={() => retry.mutate()}><RefreshCw size={14} aria-hidden="true" />重新入队</button> : undefined} />{plan.artifacts.length ? <div className="video-artifacts">{plan.artifacts.map((artifact) => <div key={artifact.artifact_key}><a className="wb-button" href={artifact.download_url}><Download size={14} aria-hidden="true" />{artifact.artifact_key}</a><small>{artifact.stage_name ? stageLabel(artifact.stage_name) : "--"} · {artifact.mime_type ?? "--"} · {bytes(artifact.file_size)}{artifact.checksum_sha256 ? ` · ${artifact.checksum_sha256.slice(0, 12)}` : ""}</small></div>)}</div> : <EmptyBlock icon={Film} title="尚无渲染产物" detail="Worker 完成后会在此提供视频、海报、字幕和质量报告。" />}</section>{retry.error ? <InlineNotice tone="danger" title="重新入队失败">{text(retry.error)}</InlineNotice> : null}</div>;
}

export function VideoProductionPage() {
  const queryClient = useQueryClient(); const [projectCode, setProjectCode] = useState(""); const [duration, setDuration] = useState(55); const [selected, setSelected] = useState("");
  const projects = useQuery({ queryKey: ["content-projects"], queryFn: contentProjectsApi.list }); const plans = useQuery({ queryKey: ["functional-videos"], queryFn: functionalVideosApi.list });
  useEffect(() => { if (!projectCode && projects.data?.[0]) setProjectCode(projects.data[0].projectCode); }, [projectCode, projects.data]);
  const active = plans.data?.some((plan) => plan.planCode === selected) ? selected : plans.data?.[0]?.planCode ?? "";
  useEffect(() => { if (selected !== active) setSelected(active); }, [active, selected]);
  const detail = useQuery({ queryKey: ["functional-video", active], queryFn: () => functionalVideosApi.get(active), enabled: Boolean(active), refetchInterval: (query) => ["queued", "running"].includes(query.state.data?.jobStatus ?? "") ? 2500 : false });
  const create = useMutation({ mutationFn: () => functionalVideosApi.create({ project_code: projectCode, target_duration_seconds: duration }), onSuccess: (plan) => { setSelected(plan.planCode); void queryClient.invalidateQueries({ queryKey: ["functional-videos"] }); } });
  const submit = (event: FormEvent) => { event.preventDefault(); if (projectCode) create.mutate(); };
  return <div className="video-plan-layout"><aside className="wb-section video-plan-rail"><SectionHeader kicker="RENDERED VIDEO" title="成片生产" /><form className="video-plan-form" onSubmit={submit}><label className="wb-field"><span>内容项目</span><select className="wb-input" value={projectCode} onChange={(event) => setProjectCode(event.target.value)}>{projects.data?.map((project) => <option key={project.projectCode} value={project.projectCode}>{project.title}</option>)}</select></label><label className="wb-field"><span>目标时长（秒）</span><input className="wb-input" type="number" min="30" max="120" value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></label><button className="wb-button wb-button-primary" disabled={!projectCode || create.isPending}><Send size={15} aria-hidden="true" />创建渲染任务</button>{create.error ? <InlineNotice tone="danger" title="无法创建成片任务">{text(create.error)}</InlineNotice> : null}</form><div className="video-plan-list">{plans.data?.map((plan) => <button type="button" key={plan.planCode} className={plan.planCode === active ? "active" : undefined} onClick={() => setSelected(plan.planCode)}><span><strong>{plan.title}</strong><code>{plan.planCode}</code><small>{plan.progressPercent}% · {plan.currentStage ?? "queued"}</small></span><StatusBadge label={jobLabel(plan.jobStatus)} tone={jobTone(plan.jobStatus)} /></button>)}</div></aside><main className="video-plan-main">{plans.isLoading || projects.isLoading ? <LoadingBlock /> : detail.data ? <Detail plan={detail.data} /> : <EmptyBlock icon={Film} title="创建第一个成片任务" detail="内容项目会被编译为垂直视频时间轴并提交给渲染 Worker。" />}</main></div>;
}
