import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Pause, Play, Plus, Radio, RefreshCw, ShieldCheck, Video } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, Metric, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { liveResearchApi } from "./api";
import { DEMO_RESEARCH_OVERVIEW, DEMO_WATCH_TARGETS } from "./demoData";
import type { WatchTarget } from "./types";

function healthBadge(value: WatchTarget["recorder_health"], label: string) {
  return <StatusBadge label={`${label} ${value === "healthy" ? "正常" : value === "degraded" ? "降级" : value === "offline" ? "离线" : "未知"}`} tone={value === "healthy" ? "success" : value === "degraded" ? "warning" : "neutral"} />;
}

function targetStatus(target: WatchTarget) {
  if (target.status === "blocked") return <StatusBadge label="需要处理" tone="danger" />;
  if (target.status === "paused") return <StatusBadge label="已暂停" tone="neutral" />;
  if (target.live_state === "recording") return <StatusBadge label="录制中" tone="info" />;
  if (target.live_state === "live_detected") return <StatusBadge label="发现直播" tone="warning" />;
  if (target.live_state === "unknown" && !target.last_checked_at) return <StatusBadge label="等待首次检查" tone="neutral" />;
  return <StatusBadge label="离线值守" tone="success" />;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未能完成";
}

export function WatchPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [roomUrl, setRoomUrl] = useState("");
  const overviewQuery = useQuery({ queryKey: ["live-research", "overview"], queryFn: liveResearchApi.getOverview, refetchInterval: 5000 });
  const targetsQuery = useQuery({ queryKey: ["live-research", "watch-targets"], queryFn: liveResearchApi.listWatchTargets, refetchInterval: 5000 });
  const demoMode = overviewQuery.isError && targetsQuery.isError;
  const overview = overviewQuery.data ?? (demoMode ? DEMO_RESEARCH_OVERVIEW : undefined);
  const targets = targetsQuery.data ?? (demoMode ? DEMO_WATCH_TARGETS : []);
  const createMutation = useMutation({
    mutationFn: liveResearchApi.createWatchTarget,
    onSuccess: () => {
      setShowCreate(false); setDisplayName(""); setRoomUrl("");
      void queryClient.invalidateQueries({ queryKey: ["live-research"] });
    },
  });
  const toggleMutation = useMutation({
    mutationFn: ({ targetCode, status }: { targetCode: string; status: "enabled" | "paused" }) => liveResearchApi.updateWatchTarget(targetCode, { status }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["live-research"] }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!displayName.trim() || !roomUrl.trim()) return;
    createMutation.mutate({ display_name: displayName.trim(), room_url: roomUrl.trim() });
  };

  return <div>
    {demoMode ? <InlineNotice tone="warning" title="当前展示值守演示数据">连接采集服务后会自动切换为 StreamCap 与 douyinLive 的真实健康状态。</InlineNotice> : null}
    {overview ? <div className="wb-metrics research-overview"><Metric label="启用值守" value={overview.enabled_target_count} /><Metric label="正在直播" value={overview.live_target_count} /><Metric label="正在录制" value={overview.recording_session_count} /><Metric label="分析队列" value={overview.analysis_queue_count} /><Metric label="模板草稿" value={overview.draft_template_count} /><Metric label="即将过期录屏" value={overview.expiring_recording_count} detail="原录屏固定保留 30 天" /></div> : null}
    <section className="wb-section research-watch-section">
      <SectionHeader kicker="ALWAYS-ON WATCH" title="长期值守列表" actions={<><button type="button" className="wb-button" onClick={() => void targetsQuery.refetch()}><RefreshCw size={14} aria-hidden="true" />刷新</button><button type="button" className="wb-button wb-button-primary" onClick={() => setShowCreate((value) => !value)}><Plus size={14} aria-hidden="true" />新增值守</button></>} />
      {showCreate ? <form className="research-target-form" onSubmit={submit}><div className="wb-field"><label htmlFor="watch-name">值守名称</label><input id="watch-name" className="wb-input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="用于内部识别" /></div><div className="wb-field"><label htmlFor="watch-url">抖音直播间 URL</label><input id="watch-url" className="wb-input" type="url" value={roomUrl} onChange={(event) => setRoomUrl(event.target.value)} placeholder="https://live.douyin.com/..." /></div><div className="research-target-policy"><Video size={15} aria-hidden="true" /><span>StreamCap 原录屏 30 天</span><Radio size={15} aria-hidden="true" /><span>互动事件仅保留脱敏聚合视图</span></div><div className="wb-form-actions"><button type="button" className="wb-button" onClick={() => setShowCreate(false)}>取消</button><button type="submit" className="wb-button wb-button-primary" disabled={createMutation.isPending || !displayName.trim() || !roomUrl.trim()}><Eye size={14} aria-hidden="true" />开始值守</button></div>{createMutation.error ? <InlineNotice tone="danger" title="无法创建值守">{errorMessage(createMutation.error)}</InlineNotice> : null}</form> : null}
      {targetsQuery.isLoading ? <LoadingBlock /> : targets.length ? <div className="wb-table-wrap"><table className="wb-table research-watch-table"><thead><tr><th>直播间</th><th>值守状态</th><th>采集通道</th><th>最近直播</th><th>下次动作</th><th>操作</th></tr></thead><tbody>{targets.filter((target) => target.status !== "deleted").map((target) => <tr key={target.target_code}><td><strong>{target.display_name}</strong><small>{target.account_name ?? target.room_url}</small><code>{target.target_code}</code></td><td>{targetStatus(target)}{target.failure_reason ? <small>{target.failure_reason}</small> : null}</td><td><div className="research-health-stack">{healthBadge(target.recorder_health, "录屏")}{healthBadge(target.interaction_health, "互动")}</div></td><td>{formatDate(target.last_live_at)}<small>检查 {formatDate(target.last_checked_at)}</small></td><td>{target.next_retry_at ? <><strong>{formatDate(target.next_retry_at)}</strong><small>自动重试</small></> : <span className="research-quiet">持续轮询</span>}</td><td><button type="button" className="wb-button" disabled={toggleMutation.isPending || target.status === "blocked"} onClick={() => toggleMutation.mutate({ targetCode: target.target_code, status: target.status === "enabled" ? "paused" : "enabled" })}>{target.status === "enabled" ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}{target.status === "enabled" ? "暂停" : "启用"}</button></td></tr>)}</tbody></table></div> : <EmptyBlock icon={Radio} title="尚无长期值守目标" detail="添加抖音直播间后，系统会在开播时分别启动录屏与互动采集通道。" />}
      {toggleMutation.error ? <div className="wb-section-body"><InlineNotice tone="danger" title="值守状态更新失败">{errorMessage(toggleMutation.error)}</InlineNotice></div> : null}
    </section>
    <div className="research-policy-band"><div><ShieldCheck size={18} aria-hidden="true" /><span><strong>完整原始事件永久保存但不直接暴露</strong><small>浏览器只读取脱敏后的数量、类型和语义摘要，不提供原始评论或用户标识下载。</small></span></div><div><Video size={18} aria-hidden="true" /><span><strong>录屏 30 天，人工片段永久</strong><small>永久片段是经过 checksum 校验的独立媒体对象，不是对即将过期录屏的时间引用。</small></span></div></div>
  </div>;
}
