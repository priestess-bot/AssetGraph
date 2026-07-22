import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Film, Flag, Pause, Play, Save, Scissors, ShieldCheck, TimerReset, VideoOff } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate, formatDuration } from "../workbench/components";
import { liveResearchApi } from "./api";
import { DEMO_CAPTURE_SESSIONS, DEMO_CLIP_JOBS, DEMO_TIMELINE } from "./demoData";
import { SESSION_STATUS_META, type CaptureSession, type CaptureTimeline, type ClipJob } from "./types";

function initialSessionCode(): string {
  return new URLSearchParams(window.location.search).get("session")?.trim() ?? "";
}

function writeSessionCode(sessionCode: string) {
  const url = new URL(window.location.href);
  url.searchParams.set("session", sessionCode);
  window.history.replaceState(null, "", url);
}

function sessionStatus(session: CaptureSession) {
  const meta = SESSION_STATUS_META[session.status];
  return <StatusBadge label={meta.label} tone={meta.tone} />;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未能完成";
}

function retentionLabel(session: CaptureSession): { label: string; tone: "success" | "warning" | "danger" | "neutral" } {
  if (!session.recording_available) return { label: "原录屏已过期", tone: "neutral" };
  if (!session.expires_at) return { label: session.status === "recording" ? "录制中" : "待计算保留期", tone: "neutral" };
  const days = Math.ceil((new Date(session.expires_at).getTime() - Date.now()) / 86_400_000);
  if (days <= 2) return { label: `${Math.max(0, days)} 天后过期`, tone: "danger" };
  if (days <= 7) return { label: `${days} 天后过期`, tone: "warning" };
  return { label: `${days} 天后过期`, tone: "success" };
}

function SessionList({ sessions, selected, onSelect }: { sessions: CaptureSession[]; selected: string; onSelect: (code: string) => void }) {
  if (!sessions.length) return <EmptyBlock icon={Film} title="尚无采集场次" detail="值守目标开播后会自动产生录屏与互动时间线。" />;
  return <ul className="research-session-list wb-list">{sessions.map((session) => { const retention = retentionLabel(session); return <li key={session.session_code}><button type="button" className={selected === session.session_code ? "active" : undefined} onClick={() => onSelect(session.session_code)}><div><strong>{session.title}</strong><code>{session.session_code}</code><small>{formatDate(session.started_at)} · {formatDuration(session.duration_seconds)}</small></div><span>{sessionStatus(session)}<StatusBadge label={retention.label} tone={retention.tone} /></span></button></li>; })}</ul>;
}

interface TimelineViewProps {
  timeline: CaptureTimeline;
  currentTime: number;
  inPoint: number;
  outPoint: number;
  onSeek: (seconds: number) => void;
}

function TimelineView({ timeline, currentTime, inPoint, outPoint, onSeek }: TimelineViewProps) {
  const [zoom, setZoom] = useState<"full" | "window">("window");
  const duration = Math.max(1, timeline.duration_seconds);
  const range = useMemo(() => {
    if (zoom === "full" || duration <= 300) return { start: 0, end: duration };
    const start = Math.min(Math.max(0, currentTime - 150), Math.max(0, duration - 300));
    return { start, end: Math.min(duration, start + 300) };
  }, [currentTime, duration, zoom]);
  const width = Math.max(1, range.end - range.start);
  const percent = (value: number) => `${Math.min(100, Math.max(0, ((value - range.start) / width) * 100))}%`;
  const segmentStyle = (start: number, end: number): CSSProperties => ({ left: percent(start), width: `${Math.max(.45, ((Math.min(end, range.end) - Math.max(start, range.start)) / width) * 100)}%` });
  const visible = (start: number, end: number) => end >= range.start && start <= range.end;
  const clickTimeline = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0;
    onSeek(range.start + Math.min(1, Math.max(0, ratio)) * width);
  };
  const interactionMax = Math.max(1, ...timeline.interaction_buckets.map((item) => item.total_count));

  return <div className="research-timeline">
    <div className="research-timeline-toolbar"><span>{formatDuration(range.start)} - {formatDuration(range.end)}</span><div className="wb-segmented"><button type="button" className={zoom === "window" ? "active" : undefined} onClick={() => setZoom("window")}>5 分钟</button><button type="button" className={zoom === "full" ? "active" : undefined} onClick={() => setZoom("full")}>全场</button></div></div>
    <div className="research-timeline-canvas" onClick={clickTimeline} role="slider" aria-label="采集时间线" aria-valuemin={range.start} aria-valuemax={range.end} aria-valuenow={currentTime} tabIndex={0}>
      <div className="timeline-track keyframe-track"><span>画面</span><div>{timeline.keyframes.filter((item) => item.at_seconds >= range.start && item.at_seconds <= range.end).map((item, index) => <i key={`${item.at_seconds}-${index}`} style={{ left: percent(item.at_seconds) }} title={`${formatDuration(item.at_seconds)} ${item.label ?? "关键帧"}`} />)}</div></div>
      <div className="timeline-track visual-track"><span>结构</span><div>{timeline.visual_segments.filter((item) => visible(item.start_seconds, item.end_seconds)).map((item, index) => <i key={`${item.start_seconds}-${index}`} style={segmentStyle(item.start_seconds, item.end_seconds)} title={`${item.label} · ${formatDuration(item.start_seconds)}`}><em>{item.label}</em></i>)}</div></div>
      <div className="timeline-track asr-track"><span>ASR</span><div>{timeline.asr_segments.filter((item) => visible(item.start_seconds, item.end_seconds)).map((item, index) => <i key={`${item.start_seconds}-${index}`} style={segmentStyle(item.start_seconds, item.end_seconds)} title={item.text} />)}</div></div>
      <div className="timeline-track interaction-track"><span>互动</span><div>{timeline.interaction_buckets.filter((item) => visible(item.start_seconds, item.end_seconds)).map((item, index) => <i key={`${item.start_seconds}-${index}`} style={{ ...segmentStyle(item.start_seconds, item.end_seconds), height: `${Math.max(18, item.total_count / interactionMax * 100)}%` }} title={`${item.total_count} 条 · ${item.summary ?? item.dominant_type ?? "互动"}`} />)}</div></div>
      {inPoint >= range.start && inPoint <= range.end ? <span className="timeline-boundary boundary-in" style={{ left: percent(inPoint) }}><b>IN</b></span> : null}
      {outPoint >= range.start && outPoint <= range.end ? <span className="timeline-boundary boundary-out" style={{ left: percent(outPoint) }}><b>OUT</b></span> : null}
      {currentTime >= range.start && currentTime <= range.end ? <span className="timeline-playhead" style={{ left: percent(currentTime) }} /> : null}
    </div>
    <div className="research-transcript-preview">{timeline.asr_segments.filter((item) => currentTime >= item.start_seconds && currentTime <= item.end_seconds).map((item) => <p key={item.start_seconds}><span>{formatDuration(item.start_seconds)}</span>{item.text}</p>)}{timeline.interaction_buckets.filter((item) => currentTime >= item.start_seconds && currentTime <= item.end_seconds).map((item) => <p key={`i-${item.start_seconds}`} className="interaction-summary"><span>{item.total_count} 条</span>{item.summary ?? "该时间段互动聚合"}</p>)}</div>
  </div>;
}

function ClipJobs({ jobs, sessionCode }: { jobs: ClipJob[]; sessionCode: string }) {
  const rows = jobs.filter((job) => job.session_code === sessionCode);
  return <section className="wb-section"><SectionHeader kicker="PERMANENT CLIPS" title={`人工片段 · ${rows.length}`} />{rows.length ? <div className="wb-table-wrap"><table className="wb-table"><thead><tr><th>片段</th><th>范围</th><th>状态</th><th>校验</th></tr></thead><tbody>{rows.map((job) => <tr key={job.clip_job_code}><td><strong>{job.title}</strong><code>{job.clip_code ?? job.clip_job_code}</code></td><td>{formatDuration(job.in_seconds)} - {formatDuration(job.out_seconds)}</td><td><StatusBadge label={job.status === "succeeded" ? "永久保存" : job.status === "failed" ? "生成失败" : "正在固化"} tone={job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : "warning"} /></td><td>{job.checksum_sha256 ? <code title={job.checksum_sha256}>{job.checksum_sha256.slice(0, 12)}</code> : <span>等待 checksum</span>}</td></tr>)}</tbody></table></div> : <EmptyBlock icon={Scissors} title="尚无永久片段" detail="在播放器设置 IN / OUT 后生成独立媒体对象。" />}</section>;
}

function SessionPlayer({ session, timeline, clipJobs, onClipCreated }: { session: CaptureSession; timeline: CaptureTimeline; clipJobs: ClipJob[]; onClipCreated: (job: ClipJob) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingChunkSeek = useRef<number | undefined>(undefined);
  const pendingAutoplay = useRef(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [inPoint, setInPoint] = useState(0);
  const [outPoint, setOutPoint] = useState(Math.min(60, session.duration_seconds));
  const [clipTitle, setClipTitle] = useState("值得复用的直播片段");
  const [looping, setLooping] = useState(false);
  const mediaChunks = useMemo(() => session.media_chunks?.length ? session.media_chunks : session.playback_url ? [{ chunk_code: "playback", media_url: session.playback_url, global_start_seconds: 0, global_end_seconds: session.duration_seconds, chunk_start_seconds: 0 }] : [], [session.duration_seconds, session.media_chunks, session.playback_url]);
  const [activeChunkIndex, setActiveChunkIndex] = useState(0);
  const activeChunk = mediaChunks[activeChunkIndex];
  useEffect(() => { setCurrentTime(0); setInPoint(0); setOutPoint(Math.min(60, session.duration_seconds)); setLooping(false); setActiveChunkIndex(0); }, [session.duration_seconds, session.session_code]);
  const seek = (seconds: number, autoplay = false) => {
    const safe = Math.min(session.duration_seconds, Math.max(0, seconds));
    setCurrentTime(safe);
    const chunkIndex = mediaChunks.findIndex((chunk, index) => safe >= chunk.global_start_seconds && (safe < chunk.global_end_seconds || index === mediaChunks.length - 1));
    if (chunkIndex < 0) return;
    const chunk = mediaChunks[chunkIndex];
    const localTime = chunk.chunk_start_seconds + safe - chunk.global_start_seconds;
    if (chunkIndex !== activeChunkIndex) {
      pendingChunkSeek.current = localTime;
      pendingAutoplay.current = autoplay;
      setActiveChunkIndex(chunkIndex);
      return;
    }
    if (videoRef.current) {
      videoRef.current.currentTime = localTime;
      if (autoplay) void videoRef.current.play().catch(() => undefined);
    }
  };
  const validRange = inPoint >= 0 && outPoint > inPoint && outPoint <= session.duration_seconds;
  const clipMutation = useMutation({
    mutationFn: () => liveResearchApi.createClip(session.session_code, { title: clipTitle.trim() || "人工永久片段", in_seconds: inPoint, out_seconds: outPoint }),
    onSuccess: onClipCreated,
  });
  const preview = () => {
    if (!validRange) return;
    setLooping(true);
    seek(inPoint, true);
  };
  const retention = retentionLabel(session);

  return <>
    <section className="wb-section research-player-section">
      <SectionHeader kicker={session.session_code} title={session.title} actions={<>{sessionStatus(session)}<StatusBadge label={retention.label} tone={retention.tone} /></>} />
      <div className="research-player-layout">
        <div className="research-media-column">
          <div className="research-media-frame">
            {activeChunk && session.recording_available ? <video key={activeChunk.media_url} ref={videoRef} src={activeChunk.media_url} poster={session.poster_url} controls playsInline preload="metadata" onLoadedMetadata={(event) => { if (pendingChunkSeek.current !== undefined) { event.currentTarget.currentTime = pendingChunkSeek.current; pendingChunkSeek.current = undefined; } if (pendingAutoplay.current) { pendingAutoplay.current = false; void event.currentTarget.play().catch(() => undefined); } }} onTimeUpdate={(event) => { const time = activeChunk.global_start_seconds + event.currentTarget.currentTime - activeChunk.chunk_start_seconds; setCurrentTime(time); if (looping && time >= outPoint) seek(inPoint, true); }} onEnded={() => { if (!looping && activeChunkIndex < mediaChunks.length - 1) { pendingChunkSeek.current = mediaChunks[activeChunkIndex + 1]?.chunk_start_seconds ?? 0; pendingAutoplay.current = true; setActiveChunkIndex((value) => value + 1); } }} aria-label="直播录屏播放器" /> : <div className="research-media-placeholder"><VideoOff size={34} strokeWidth={1.4} aria-hidden="true" /><strong>{session.recording_available ? "播放流等待就绪" : "原录屏已过期"}</strong><span>{session.recording_available ? "时间线、分析结果和永久片段仍可正常操作" : "模板证据和永久人工片段继续保留"}</span><time>{formatDuration(currentTime)} / {formatDuration(session.duration_seconds)}</time></div>}
          </div>
          <div className="research-player-status"><span><Clock3 size={14} aria-hidden="true" />{formatDuration(currentTime)}</span><span>录屏 {session.recorder_health === "healthy" ? "完整" : "存在缺口"}</span><span>互动 {session.interaction_health === "healthy" ? "已对齐" : "降级"}</span></div>
        </div>
        <div className="research-clip-panel">
          <InlineNotice title="设置永久片段范围">保存时会复制媒体并校验 checksum；不会把时间引用伪装成永久素材。</InlineNotice>
          <div className="research-mark-buttons"><button type="button" className="wb-button" onClick={() => setInPoint(Math.min(currentTime, outPoint - .1))}><Flag size={14} aria-hidden="true" />设为 IN</button><button type="button" className="wb-button" onClick={() => setOutPoint(Math.max(currentTime, inPoint + .1))}><Flag size={14} aria-hidden="true" />设为 OUT</button></div>
          <div className="research-time-fields"><div className="wb-field"><label htmlFor="clip-in">IN（秒）</label><input id="clip-in" className="wb-input" type="number" min={0} max={session.duration_seconds} step="0.1" value={inPoint} onChange={(event) => setInPoint(Number(event.target.value))} /></div><div className="wb-field"><label htmlFor="clip-out">OUT（秒）</label><input id="clip-out" className="wb-input" type="number" min={0} max={session.duration_seconds} step="0.1" value={outPoint} onChange={(event) => setOutPoint(Number(event.target.value))} /></div></div>
          <div className="research-range-summary"><span>{formatDuration(inPoint)}</span><strong>{validRange ? `${(outPoint - inPoint).toFixed(1)} 秒` : "范围无效"}</strong><span>{formatDuration(outPoint)}</span></div>
          <div className="wb-field"><label htmlFor="clip-title">片段名称</label><input id="clip-title" className="wb-input" value={clipTitle} onChange={(event) => setClipTitle(event.target.value)} /></div>
          <div className="research-clip-actions"><button type="button" className="wb-button" disabled={!validRange || !mediaChunks.length} onClick={preview}>{looping ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}循环预览</button><button type="button" className="wb-button wb-button-primary" disabled={!validRange || !session.recording_available || session.status !== "completed" || clipMutation.isPending} onClick={() => clipMutation.mutate()}><Save size={14} aria-hidden="true" />保存永久片段</button></div>
          {session.status !== "completed" ? <InlineNotice tone="warning" title="等待录屏封装完成">录制中或封装中的场次不能固化片段。</InlineNotice> : null}
          {clipMutation.error ? <InlineNotice tone="danger" title="片段任务创建失败">{errorMessage(clipMutation.error)}</InlineNotice> : null}
        </div>
      </div>
      <div className="wb-section-body research-timeline-body"><TimelineView timeline={timeline} currentTime={currentTime} inPoint={inPoint} outPoint={outPoint} onSeek={seek} /></div>
    </section>
    <ClipJobs jobs={clipJobs} sessionCode={session.session_code} />
  </>;
}

export function SessionsPage() {
  const queryClient = useQueryClient();
  const [sessionCode, setSessionCode] = useState(initialSessionCode);
  const sessionsQuery = useQuery({ queryKey: ["live-research", "sessions"], queryFn: liveResearchApi.listCaptureSessions, refetchInterval: (query) => query.state.data?.some((item) => ["starting", "recording", "finalizing"].includes(item.status)) ? 2000 : false });
  const clipJobsQuery = useQuery({ queryKey: ["live-research", "clip-jobs"], queryFn: liveResearchApi.listClipJobs, refetchInterval: (query) => query.state.data?.some((item) => ["queued", "running"].includes(item.status)) ? 1500 : false });
  const demoMode = sessionsQuery.isError && clipJobsQuery.isError;
  const sessions = sessionsQuery.data ?? (demoMode ? DEMO_CAPTURE_SESSIONS : []);
  const clipJobs = clipJobsQuery.data ?? (demoMode ? DEMO_CLIP_JOBS : []);
  useEffect(() => { if (!sessionCode && sessions[0]) { setSessionCode(sessions[0].session_code); writeSessionCode(sessions[0].session_code); } }, [sessionCode, sessions]);
  const summary = sessions.find((item) => item.session_code === sessionCode);
  const detailQuery = useQuery({ queryKey: ["live-research", "session", sessionCode], queryFn: () => liveResearchApi.getCaptureSession(sessionCode), enabled: Boolean(sessionCode) && !demoMode });
  const timelineQuery = useQuery({ queryKey: ["live-research", "timeline", sessionCode], queryFn: () => liveResearchApi.getTimeline(sessionCode), enabled: Boolean(sessionCode) && !demoMode });
  const session = detailQuery.data ?? summary;
  const timeline = timelineQuery.data ?? (demoMode && session ? { ...DEMO_TIMELINE, session_code: session.session_code, duration_seconds: session.duration_seconds } : undefined);
  const select = (code: string) => { setSessionCode(code); writeSessionCode(code); };
  const onClipCreated = (job: ClipJob) => {
    queryClient.setQueryData<ClipJob[]>(["live-research", "clip-jobs"], (current) => [job, ...(current ?? [])]);
    void queryClient.invalidateQueries({ queryKey: ["live-research", "sessions"] });
  };

  return <div>
    {demoMode ? <InlineNotice tone="warning" title="当前展示场次演示数据">真实播放地址、连续分片映射和分析轨道会从 `/api/live-research` 读取。</InlineNotice> : null}
    <div className="wb-grid research-session-grid">
      <aside className="wb-section research-session-rail"><SectionHeader kicker="CAPTURE SESSIONS" title="采集场次" />{sessionsQuery.isLoading ? <LoadingBlock /> : <SessionList sessions={sessions} selected={sessionCode} onSelect={select} />}</aside>
      <div className="research-session-detail">{detailQuery.isLoading || timelineQuery.isLoading ? <section className="wb-section"><LoadingBlock label="正在加载录屏与时间线" /></section> : session && timeline ? <SessionPlayer session={session} timeline={timeline} clipJobs={clipJobs} onClipCreated={onClipCreated} /> : <section className="wb-section"><EmptyBlock icon={TimerReset} title="选择一个采集场次" detail="完成后的场次可以审阅时间线并固化永久片段。" /></section>}</div>
    </div>
    <div className="research-session-policy"><ShieldCheck size={17} aria-hidden="true" /><span>时间线只展示脱敏互动聚合。完整事件 payload 和外部用户标识不会发送到浏览器。</span>{timeline?.media_gaps.length ? <StatusBadge label={`${timeline.media_gaps.length} 个媒体缺口`} tone="warning" /> : <StatusBadge label="时间轴连续" tone="success" />}</div>
  </div>;
}
