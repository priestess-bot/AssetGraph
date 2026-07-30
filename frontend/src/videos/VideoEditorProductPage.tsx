import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, Copy, Download, Film, Image, Music2, RefreshCw, Save, Scissors, Subtitles, Volume2 } from "lucide-react";
import { assetLibraryApi } from "../assets/api";
import { contentProjectsApi } from "../content/api";
import { functionalLiveRoomsApi } from "../live-rooms/api";
import { PageHeader } from "../product/components";
import { EmptyBlock, LoadingBlock, StatusBadge } from "../workbench/components";
import { productLabel } from "../workbench/productLanguage";
import { functionalVideosApi, type FunctionalVideoPlan } from "./api";

type ClipDraft = {
  key: string;
  clipCode: string;
  durationMs: number;
  transition: string;
  sourceAssetCode?: string;
  initialSourceAssetCode?: string;
  sourceStartSeconds?: number;
  sourceEndSeconds?: number;
  fit?: "cover" | "contain";
  playbackRate: number;
  subtitleClipCode?: string;
  subtitleText: string;
  headlineText: string;
  captionPosition: "bottom" | "center";
  audioClipCode?: string;
  gainDb: number;
};

function clipsFromPlan(plan: FunctionalVideoPlan): ClipDraft[] {
  const video = plan.productionTimeline.tracks.find((item) => item.track_kind === "video");
  const subtitles = plan.productionTimeline.tracks.find((item) => item.track_kind === "subtitle")?.clips ?? [];
  const audio = plan.productionTimeline.tracks.find((item) => item.track_kind === "audio")?.clips ?? [];
  return video?.clips.map((clip, index) => {
    const subtitle = subtitles[index] ?? subtitles.find((item) => item.linked_shot_code === clip.source_shot_code);
    const voice = audio[index] ?? audio.find((item) => item.linked_shot_code === clip.source_shot_code);
    return {
      key: `${clip.clip_code}:${index}`,
      clipCode: clip.clip_code,
      durationMs: clip.timeline_range.duration_ms,
      transition: clip.transition ?? "cut",
      sourceAssetCode: clip.source_range?.asset_code,
      initialSourceAssetCode: clip.source_range?.asset_code,
      sourceStartSeconds: clip.source_range?.start_seconds,
      sourceEndSeconds: clip.source_range?.end_seconds,
      fit: clip.fit,
      playbackRate: clip.playback_rate ?? 1,
      subtitleClipCode: subtitle?.clip_code,
      subtitleText: subtitle?.subtitle_text ?? "",
      headlineText: subtitle?.headline_text ?? "",
      captionPosition: subtitle?.caption_position ?? "bottom",
      audioClipCode: voice?.clip_code,
      gainDb: voice?.gain_db ?? 0,
    };
  }) ?? [];
}

function jobLabel(status: string): string {
  if (status === "queued") return "等待制作";
  if (status === "running") return "正在渲染";
  if (status === "completed" || status === "succeeded") return "成片已完成";
  if (status === "failed") return "制作未完成";
  return productLabel(status, "准备中");
}

function stageLabel(value: string): string {
  const key = value.toLowerCase();
  if (key.includes("prepare") || key.includes("material")) return "准备素材";
  if (key.includes("voice") || key.includes("audio")) return "生成与混合音频";
  if (key.includes("subtitle")) return "生成字幕";
  if (key.includes("render") || key.includes("compose")) return "合成画面";
  if (key.includes("quality") || key.includes("probe")) return "检查成片";
  if (key.includes("publish") || key.includes("artifact")) return "整理产物";
  return "制作步骤";
}

function CreateVideoPanel({ requestedProject, onCreated }: { requestedProject: string; onCreated: (code: string) => void }) {
  const client = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: contentProjectsApi.list });
  const rooms = useQuery({ queryKey: ["functional-live-room-plans"], queryFn: functionalLiveRoomsApi.list });
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const [source, setSource] = useState<"project" | "live">("project");
  const [projectCode, setProjectCode] = useState(requestedProject);
  const [roomPlan, setRoomPlan] = useState("");
  const [duration, setDuration] = useState(55);
  const [visuals, setVisuals] = useState<string[]>([]);
  const [music, setMusic] = useState("");
  useEffect(() => { if (!projectCode && projects.data?.[0]) setProjectCode(projects.data[0].projectCode); }, [projectCode, projects.data]);
  useEffect(() => { if (!roomPlan && rooms.data?.[0]) setRoomPlan(rooms.data[0].planCode); }, [roomPlan, rooms.data]);
  const videos = (assets.data ?? []).filter((item) => item.mediaKind === "video" && item.executionCapability === "local_only");
  const musicAssets = (assets.data ?? []).filter((item) => item.mediaKind === "audio" && item.materialRoles.includes("background_music"));
  const create = useMutation({
    mutationFn: () => functionalVideosApi.create({
      ...(source === "project" ? { project_code: projectCode } : { live_room_plan_code: roomPlan }),
      target_duration_seconds: duration,
      visual_asset_codes: visuals.length ? visuals : undefined,
      background_music_asset_code: music || undefined,
      background_music_gain_db: music ? -18 : undefined,
    }),
    onSuccess: (plan) => { void client.invalidateQueries({ queryKey: ["functional-videos"] }); onCreated(plan.planCode); },
  });
  return <div className="video-create-product">
    <div className="video-create-heading"><div><span className="product-section-kicker">竖屏成片</span><h2>新建成片制作</h2><p>从内容项目或直播间方案生成初始镜头，再进入时间轴调整。</p></div><Film size={30} /></div>
    <div className="video-source-mode"><button type="button" className={source === "project" ? "active" : ""} onClick={() => setSource("project")}>从内容项目</button><button type="button" className={source === "live" ? "active" : ""} onClick={() => setSource("live")}>从直播间方案</button></div>
    <div className="video-create-fields">
      {source === "project" ? <label className="product-field"><span>内容项目</span><select value={projectCode} onChange={(event) => setProjectCode(event.target.value)}><option value="">选择项目</option>{projects.data?.map((item) => <option key={item.projectCode} value={item.projectCode}>{item.title}</option>)}</select></label> : <label className="product-field"><span>直播间方案</span><select value={roomPlan} onChange={(event) => setRoomPlan(event.target.value)}><option value="">选择方案</option>{rooms.data?.map((item) => <option key={item.planCode} value={item.planCode}>{item.expectedTitle}</option>)}</select></label>}
      <label className="product-field"><span>目标时长</span><select value={duration} onChange={(event) => setDuration(Number(event.target.value))}><option value="30">30 秒</option><option value="45">45 秒</option><option value="55">55 秒</option><option value="60">60 秒</option><option value="90">90 秒</option></select></label>
      <label className="product-field"><span>背景音乐</span><select value={music} onChange={(event) => setMusic(event.target.value)}><option value="">不使用背景音乐</option>{musicAssets.map((item) => <option key={item.assetCode} value={item.assetCode}>{item.title}</option>)}</select></label>
    </div>
    <section className="video-create-assets"><header><div><strong>可用视频素材</strong><span>最多选择 6 份</span></div><b>{visuals.length}/6</b></header>{videos.length ? <div>{videos.map((item) => <label key={item.assetCode} className={visuals.includes(item.assetCode) ? "selected" : ""}><input type="checkbox" checked={visuals.includes(item.assetCode)} disabled={!visuals.includes(item.assetCode) && visuals.length >= 6} onChange={() => setVisuals((current) => current.includes(item.assetCode) ? current.filter((code) => code !== item.assetCode) : [...current, item.assetCode])} /><video muted preload="metadata" src={assetLibraryApi.previewUrl(item.assetCode)} /><span><strong>{item.title}</strong><small>{item.materialRoles.map((role) => productLabel(role, "视频素材")).join("、")}</small></span></label>)}</div> : <EmptyBlock icon={Film} title="素材库中没有可本地剪辑的视频" detail="先导入视频素材并将用途设置为本地成片。" />}</section>
    {create.error ? <div className="product-inline-error">成片制作没有启动，请检查内容来源和视频素材。</div> : null}
    <footer><a className="product-secondary-button" href="/assets">管理视频素材</a><button className="product-primary-button" type="button" disabled={(source === "project" ? !projectCode : !roomPlan) || create.isPending} onClick={() => create.mutate()}><Scissors size={16} />{create.isPending ? "正在建立时间轴" : "建立初始时间轴"}</button></footer>
  </div>;
}

function VideoEditor({ plan, onPlan }: { plan: FunctionalVideoPlan; onPlan: (plan: FunctionalVideoPlan) => void }) {
  const client = useQueryClient();
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const [clips, setClips] = useState<ClipDraft[]>(() => clipsFromPlan(plan));
  const [selected, setSelected] = useState(0);
  const [panel, setPanel] = useState<"clip" | "production">("clip");
  const [posterTimeMs, setPosterTimeMs] = useState(plan.productionTimeline.poster_time_ms ?? 2000);
  const [subtitlePreset, setSubtitlePreset] = useState<"compact" | "standard" | "large">(plan.productionTimeline.subtitle_style?.preset ?? "standard");
  useEffect(() => { setClips(clipsFromPlan(plan)); setPosterTimeMs(plan.productionTimeline.poster_time_ms ?? 2000); setSubtitlePreset(plan.productionTimeline.subtitle_style?.preset ?? "standard"); setSelected(0); }, [plan.planCode, plan.timelineRevision]);
  const clip = clips[selected];
  const usableVideo = (assets.data ?? []).filter((item) => item.mediaKind === "video" && item.executionCapability === "local_only");
  const source = assets.data?.find((item) => item.assetCode === clip?.sourceAssetCode);
  const videoUrl = plan.artifacts.find((item) => item.artifact_key === "video")?.download_url;
  const posterUrl = plan.artifacts.find((item) => item.artifact_key === "poster")?.download_url;
  const contactSheetUrl = plan.artifacts.find((item) => item.artifact_key === "contact_sheet")?.download_url;
  const updateClip = (next: Partial<ClipDraft>) => setClips((current) => current.map((item,index) => index === selected ? { ...item, ...next } : item));
  const move = (offset: -1 | 1) => setClips((current) => { const destination = selected + offset; if (destination < 0 || destination >= current.length) return current; const next = [...current]; [next[selected],next[destination]] = [next[destination],next[selected]]; setSelected(destination); return next; });
  const save = useMutation({
    mutationFn: () => functionalVideosApi.updateTimeline(plan.planCode, {
      expected_revision: plan.timelineRevision, poster_time_ms: posterTimeMs,
      subtitle_style: { preset: subtitlePreset, safe_bottom_px: plan.productionTimeline.subtitle_style?.safe_bottom_px ?? 160 },
      video_clips: clips.map((item) => ({ clip_code: item.clipCode, duration_ms: item.durationMs, transition: item.transition, ...(item.sourceAssetCode && item.sourceAssetCode !== item.initialSourceAssetCode ? { source_asset_code: item.sourceAssetCode } : {}), ...(item.sourceStartSeconds !== undefined ? { source_start_seconds: item.sourceStartSeconds } : {}), ...(item.sourceEndSeconds !== undefined ? { source_end_seconds: item.sourceEndSeconds } : {}), fit: item.fit, playback_rate: item.playbackRate })),
      subtitle_clips: clips.flatMap((item) => item.subtitleClipCode ? [{ clip_code: item.subtitleClipCode, subtitle_text: item.subtitleText, headline_text: item.headlineText, caption_position: item.captionPosition }] : []),
      audio_clips: clips.flatMap((item) => item.audioClipCode ? [{ clip_code: item.audioClipCode, gain_db: item.gainDb }] : []),
    }),
    onSuccess: (next) => { onPlan(next); client.setQueryData(["functional-video", next.planCode], next); void client.invalidateQueries({ queryKey: ["functional-videos"] }); },
  });
  const retry = useMutation({ mutationFn: () => functionalVideosApi.retry(plan.planCode), onSuccess: onPlan });
  const branch = useMutation({ mutationFn: () => functionalVideosApi.branch(plan.planCode, { title: `${plan.title} - 编辑副本` }), onSuccess: onPlan });
  const completeChecks = Object.values(plan.qualityReport.checks).filter(Boolean).length;
  const totalChecks = Object.keys(plan.qualityReport.checks).length;
  const duration = Math.max(1, clips.reduce((sum,item) => sum + item.durationMs,0));
  const editable = plan.jobStatus === "queued";
  return <div className="video-editor-product">
    <header className="video-editor-topbar"><div><a href="/projects">内容项目</a><span>/</span><strong>{plan.title}</strong></div><div><StatusBadge label={jobLabel(plan.jobStatus)} tone={plan.jobStatus === "completed" || plan.jobStatus === "succeeded" ? "success" : plan.jobStatus === "failed" ? "danger" : "info"} /><span>{plan.progressPercent}%</span></div></header>
    <main className="video-preview-area"><div className="video-player-stage">{videoUrl ? <video controls preload="metadata" src={videoUrl} poster={posterUrl} /> : source ? <video controls muted preload="metadata" src={assetLibraryApi.previewUrl(source.assetCode)} /> : <div><Film size={34} /><strong>{plan.jobStatus === "running" ? "正在生成预览" : "选择镜头查看素材"}</strong></div>} {clip?.headlineText ? <strong className="video-preview-headline">{clip.headlineText}</strong> : null}{clip?.subtitleText ? <span className={`video-preview-caption ${clip.captionPosition}`}>{clip.subtitleText}</span> : null}</div><div className="video-preview-controls"><span>{clip ? `镜头 ${selected + 1} / ${clips.length}` : "暂无镜头"}</span><strong>{(duration/1000).toFixed(1)} 秒</strong></div></main>
    <aside className="video-inspector-product"><nav><button type="button" className={panel === "clip" ? "active" : ""} onClick={() => setPanel("clip")}>镜头</button><button type="button" className={panel === "production" ? "active" : ""} onClick={() => setPanel("production")}>制作进度</button></nav>{panel === "clip" ? <div className="video-clip-properties">{clip ? <>
      <header><span className="product-section-kicker">镜头 {selected + 1}</span><h3>{source?.title ?? "当前画面"}</h3></header>
      <label className="product-field"><span>画面素材</span><select disabled={!editable} value={clip.sourceAssetCode ?? ""} onChange={(event) => updateClip({ sourceAssetCode: event.target.value })}><option value="">沿用原画面</option>{usableVideo.map((item) => <option key={item.assetCode} value={item.assetCode}>{item.title}</option>)}</select></label>
      <div className="video-property-row"><label className="product-field"><span>时长（秒）</span><input disabled={!editable} type="number" min=".25" max="120" step=".1" value={clip.durationMs/1000} onChange={(event) => updateClip({ durationMs: Math.round(Number(event.target.value)*1000) })} /></label><label className="product-field"><span>速度</span><select disabled={!editable} value={clip.playbackRate} onChange={(event) => updateClip({ playbackRate: Number(event.target.value) })}><option value=".75">0.75x</option><option value="1">1x</option><option value="1.25">1.25x</option><option value="1.5">1.5x</option></select></label></div>
      <label className="product-field"><span>转场</span><select disabled={!editable} value={clip.transition} onChange={(event) => updateClip({ transition: event.target.value })}><option value="cut">直接切换</option><option value="fade">淡入淡出</option><option value="fade_out">淡出</option></select></label>
      <label className="product-field"><span>标题文字</span><input disabled={!editable} value={clip.headlineText} onChange={(event) => updateClip({ headlineText: event.target.value })} /></label>
      <label className="product-field"><span>字幕</span><textarea disabled={!editable} rows={4} value={clip.subtitleText} onChange={(event) => updateClip({ subtitleText: event.target.value })} /></label>
      <div className="video-property-row"><label className="product-field"><span>字幕位置</span><select disabled={!editable} value={clip.captionPosition} onChange={(event) => updateClip({ captionPosition: event.target.value as "bottom" | "center" })}><option value="bottom">画面底部</option><option value="center">画面中部</option></select></label><label className="product-field"><span>人声音量</span><input disabled={!editable} type="number" min="-30" max="12" value={clip.gainDb} onChange={(event) => updateClip({ gainDb: Number(event.target.value) })} /></label></div>
      <div className="video-clip-move"><button type="button" className="product-secondary-button" disabled={!editable || selected === 0} onClick={() => move(-1)}><ArrowLeft size={15} />前移</button><button type="button" className="product-secondary-button" disabled={!editable || selected === clips.length-1} onClick={() => move(1)}>后移<ArrowRight size={15} /></button></div>
    </> : <EmptyBlock icon={Scissors} title="选择一个镜头" />}</div> : <div className="video-production-panel">
      <section className="video-progress-product"><div><span>制作进度</span><strong>{plan.progressPercent}%</strong></div><i><b style={{ width: `${plan.progressPercent}%` }} /></i></section>
      <section className="video-stage-list"><h3>制作阶段</h3>{plan.workflowStages.map((stage,index) => <article key={`${stage.stageName}:${index}`}><span>{stage.status === "completed" || stage.status === "succeeded" ? <CheckCircle2 size={15} /> : index+1}</span><div><strong>{stageLabel(stage.stageName)}</strong><small>{productLabel(stage.status, "等待处理")}</small></div></article>)}</section>
      <section className="video-quality-product"><h3>成片检查</h3><div><strong>{completeChecks}/{totalChecks || 0}</strong><span>{plan.qualityReport.passed ? "全部通过" : totalChecks ? "仍有项目需要处理" : "渲染完成后自动检查"}</span></div>{plan.qualityReport.media ? <ul><li>画面 {plan.qualityReport.media.width} × {plan.qualityReport.media.height}</li><li>时长 {plan.qualityReport.media.durationSeconds.toFixed(1)} 秒</li><li>黑屏 {plan.qualityReport.diagnostics.blackSegments.length} 段 · 静音 {plan.qualityReport.diagnostics.silenceSegments.length} 段</li></ul> : null}</section>
      <section className="video-output-product"><h3>制作产物</h3>{videoUrl ? <a href={videoUrl}><Film size={15} />下载成片<Download size={14} /></a> : null}{posterUrl ? <a href={posterUrl}><Image size={15} />下载封面<Download size={14} /></a> : null}{contactSheetUrl ? <a href={contactSheetUrl}><Film size={15} />下载镜头总览<Download size={14} /></a> : null}{!videoUrl && !posterUrl ? <span>制作完成后可在这里下载</span> : null}</section>
      {plan.jobStatus === "failed" ? <button className="product-primary-button" type="button" disabled={retry.isPending} onClick={() => retry.mutate()}><RefreshCw size={15} />重新制作</button> : null}
    </div>}</aside>
    <section className="video-timeline-product"><header><div><button className="product-icon-button" type="button" title="剪辑工具"><Scissors size={16} /></button><button className="product-icon-button" type="button" title="字幕"><Subtitles size={16} /></button><button className="product-icon-button" type="button" title="音频"><Music2 size={16} /></button></div><label><span>海报帧</span><input disabled={!editable} type="number" min="0" max={duration/1000} step=".1" value={posterTimeMs/1000} onChange={(event) => setPosterTimeMs(Math.round(Number(event.target.value)*1000))} /><b>秒</b></label><label><span>字幕大小</span><select disabled={!editable} value={subtitlePreset} onChange={(event) => setSubtitlePreset(event.target.value as typeof subtitlePreset)}><option value="compact">紧凑</option><option value="standard">标准</option><option value="large">大字</option></select></label></header><div className="video-track-stack"><div className="video-track-label"><Film size={14} />画面</div><div className="video-track-clips">{clips.map((item,index) => <button key={item.key} type="button" className={selected === index ? "active" : ""} style={{ flexGrow: Math.max(1,item.durationMs) }} onClick={() => setSelected(index)}><span>{index+1}</span><strong>{assets.data?.find((asset) => asset.assetCode === item.sourceAssetCode)?.title ?? `镜头 ${index+1}`}</strong><small>{(item.durationMs/1000).toFixed(1)}s</small></button>)}</div><div className="video-track-label"><Subtitles size={14} />字幕</div><div className="video-track-subtitles">{clips.map((item,index) => <button key={item.key} type="button" className={selected === index ? "active" : ""} style={{ flexGrow: Math.max(1,item.durationMs) }} onClick={() => setSelected(index)}>{item.subtitleText || "无字幕"}</button>)}</div><div className="video-track-label"><Volume2 size={14} />音频</div><div className="video-track-audio">{clips.map((item) => <span key={item.key} style={{ flexGrow: Math.max(1,item.durationMs) }}><i /></span>)}</div></div></section>
    <footer className="video-editor-actions"><span>{save.isSuccess ? "时间轴已保存为新版本" : save.error ? "时间轴没有保存，请检查镜头设置" : editable ? "修改后保存为新的时间轴版本" : "已完成的成片需先创建编辑副本"}</span>{!editable ? <button className="product-secondary-button" type="button" disabled={branch.isPending} onClick={() => branch.mutate()}><Copy size={15} />创建编辑副本</button> : null}<button className="product-primary-button" type="button" disabled={!editable || save.isPending} onClick={() => save.mutate()}><Save size={16} />保存时间轴</button></footer>
  </div>;
}

export function VideoEditorProductPage({ search = window.location.search }: { search?: string }) {
  const params = new URLSearchParams(search);
  const requestedPlan = params.get("plan") ?? "";
  const requestedProject = params.get("project") ?? "";
  const [selected, setSelected] = useState(requestedPlan);
  const plans = useQuery({ queryKey: ["functional-videos"], queryFn: functionalVideosApi.list });
  const matching = useMemo(() => (plans.data ?? []).filter((item) => !requestedProject || item.projectCode === requestedProject), [plans.data, requestedProject]);
  useEffect(() => { if (requestedPlan) setSelected(requestedPlan); else if (!selected && matching[0]) setSelected(matching[0].planCode); }, [matching, requestedPlan, selected]);
  const detail = useQuery({ queryKey: ["functional-video", selected], queryFn: () => functionalVideosApi.get(selected), enabled: Boolean(selected), refetchInterval: (query) => ["queued","running"].includes(query.state.data?.jobStatus ?? "") ? 2500 : false });
  const [localPlan, setLocalPlan] = useState<FunctionalVideoPlan>();
  useEffect(() => { if (detail.data) setLocalPlan(detail.data); }, [detail.data]);
  if (plans.isLoading || (selected && detail.isLoading)) return <LoadingBlock label="正在打开成片制作" />;
  const plan = localPlan ?? detail.data;
  if (!plan) return <div className="product-page video-product-page"><PageHeader eyebrow="成片生产" title="竖屏成片" description="从项目或直播间方案生成可编辑时间轴，完成剪辑、渲染、质检与产物下载。" /><CreateVideoPanel requestedProject={requestedProject} onCreated={(code) => { setSelected(code); setLocalPlan(undefined); }} /></div>;
  return <VideoEditor plan={plan} onPlan={setLocalPlan} />;
}
