import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleSlash2,
  Clock3,
  Database,
  Eye,
  EyeOff,
  Layers3,
  MessageSquareText,
  RefreshCw,
  Search,
} from "lucide-react";
import { interactionsApi, type LiveInteraction, type LiveSession } from "./api";
import "./interactions.css";


const FORM_LABELS: Record<string, string> = {
  question: "问题",
  request: "请求",
  greeting: "问候",
  feedback: "反馈 / 评价",
  purchase_signal: "购买信号",
  noise: "噪声",
  other: "其他",
};

const INTENT_LABELS: Record<string, string> = {
  product_attributes: "商品属性",
  product_lookup: "商品 / 链接查询",
  recommendation: "选购推荐",
  price_promotion_gift: "价格促销赠品",
  inventory_shipping: "库存物流",
  order_purchase: "下单订单",
  after_sales_invoice: "售后发票",
  live_room_operation: "直播间操作",
  social_feedback: "社交反馈",
  off_topic_noise: "无关 / 噪声",
  other: "其他",
};

const GRADE_LABELS: Record<string, string> = {
  good: "好",
  fair: "一般",
  poor: "差",
};

const INTERACTION_TYPE_LABELS: Record<number, string> = {
  0: "普通互动",
  1: "关注",
  2: "进入直播间",
  3: "点赞",
  4: "分享",
  5: "打赏",
  6: "加购",
  7: "点击",
};


function formatDate(value?: string): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}


function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}


function StatusPill({ value }: { value: string }) {
  const label: Record<string, string> = {
    active: "已连接",
    unbound: "待绑定",
    waiting_login: "等待登录",
    account_mismatch: "账号不一致",
    error: "异常",
    queued: "排队中",
    running: "同步中",
    succeeded: "已完成",
    partial: "部分完成",
    failed: "失败",
    pending: "待分析",
    excluded: "已排除",
  };
  return <span className={`interaction-status is-${value}`}>{label[value] ?? value}</span>;
}


function Grade({ value }: { value?: string }) {
  if (!value) return <span className="interaction-grade is-pending">待分析</span>;
  return <span className={`interaction-grade is-${value}`}>{GRADE_LABELS[value] ?? value}</span>;
}


function Pager({ offset, limit, total, onChange }: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  const start = total ? offset + 1 : 0;
  const end = Math.min(total, offset + limit);
  return <div className="interaction-pager">
    <span>{start}-{end} / {total}</span>
    <button type="button" title="上一页" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
      <ChevronLeft size={16} aria-hidden="true" />
    </button>
    <button type="button" title="下一页" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
      <ChevronRight size={16} aria-hidden="true" />
    </button>
  </div>;
}


function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="interaction-error"><AlertCircle size={16} aria-hidden="true" /><span>{error instanceof Error ? error.message : "数据加载失败"}</span></div>;
}


function SessionRow({ session, selected, onSelect }: {
  session: LiveSession;
  selected: boolean;
  onSelect: () => void;
}) {
  return <button type="button" className={`interaction-session-row ${selected ? "is-selected" : ""}`} onClick={onSelect}>
    <span className="interaction-session-main"><strong>{session.title}</strong><small>{formatDate(session.startedAt)} · {formatDuration(session.durationSeconds)}</small></span>
    <span className="interaction-session-count"><strong>{session.storedInteractionCount}</strong><small>条互动</small></span>
    {session.syncComplete ? <CheckCircle2 size={15} aria-label="同步完整" /> : <Clock3 size={15} aria-label="待同步" />}
  </button>;
}


function CollectionRecords() {
  const [platformId, setPlatformId] = useState<number>();
  const [sessionId, setSessionId] = useState<number>();
  const [sessionOffset, setSessionOffset] = useState(0);
  const [itemOffset, setItemOffset] = useState(0);
  const [showArrivals, setShowArrivals] = useState(false);
  const [search, setSearch] = useState("");
  const platformsQuery = useQuery({ queryKey: ["interactions", "platforms"], queryFn: interactionsApi.platforms });
  const sessionsQuery = useQuery({
    queryKey: ["interactions", "sessions", platformId, sessionOffset],
    queryFn: () => interactionsApi.sessions({ platformId, limit: 30, offset: sessionOffset }),
    enabled: platformId !== undefined,
  });
  const itemsQuery = useQuery({
    queryKey: ["interactions", "session-items", sessionId, showArrivals, search, itemOffset],
    queryFn: () => interactionsApi.sessionItems({
      externalSessionId: sessionId!,
      includeArrivals: showArrivals,
      search,
      limit: 50,
      offset: itemOffset,
    }),
    enabled: sessionId !== undefined,
  });

  useEffect(() => {
    if (platformId === undefined && platformsQuery.data?.length) {
      const preferred = platformsQuery.data.find((item) => item.sessionCount > 0)
        ?? platformsQuery.data[0];
      setPlatformId(preferred.externalPlatformId);
    }
  }, [platformId, platformsQuery.data]);

  useEffect(() => {
    const sessions = sessionsQuery.data?.items ?? [];
    if (!sessions.length) {
      setSessionId(undefined);
    } else if (!sessions.some((item) => item.externalSessionId === sessionId)) {
      const preferred = sessions.find((item) => item.effectiveCount > 0) ?? sessions[0];
      setSessionId(preferred.externalSessionId);
    }
  }, [sessionId, sessionsQuery.data]);

  const selectedSession = sessionsQuery.data?.items.find(
    (item) => item.externalSessionId === sessionId,
  );

  return <div className="interaction-collection">
    <aside className="interaction-platform-pane">
      <header><Layers3 size={17} aria-hidden="true" /><h3>直播平台</h3></header>
      <ErrorLine error={platformsQuery.error} />
      <div className="interaction-platform-list">
        {(platformsQuery.data ?? []).map((platform) => <button
          type="button"
          key={platform.externalPlatformId}
          className={platform.externalPlatformId === platformId ? "is-selected" : ""}
          onClick={() => {
            setPlatformId(platform.externalPlatformId);
            setSessionOffset(0);
            setItemOffset(0);
          }}
        >
          <span><strong>{platform.platformName}</strong><small>{platform.effectiveCount} 条有效互动</small></span>
          <b>{platform.sessionCount}</b>
        </button>)}
      </div>
    </aside>

    <section className="interaction-session-pane">
      <header><div><span>采集场次</span><h3>{platformsQuery.data?.find((item) => item.externalPlatformId === platformId)?.platformName ?? "直播平台"}</h3></div></header>
      <ErrorLine error={sessionsQuery.error} />
      <div className="interaction-session-list">
        {(sessionsQuery.data?.items ?? []).map((session) => <SessionRow
          key={session.externalSessionId}
          session={session}
          selected={session.externalSessionId === sessionId}
          onSelect={() => { setSessionId(session.externalSessionId); setItemOffset(0); }}
        />)}
        {!sessionsQuery.isLoading && !sessionsQuery.data?.items.length ? <div className="interaction-empty"><Database size={22} aria-hidden="true" /><span>暂无直播场次</span></div> : null}
      </div>
      <Pager offset={sessionOffset} limit={30} total={sessionsQuery.data?.total ?? 0} onChange={(next) => { setSessionOffset(next); setItemOffset(0); }} />
    </section>

    <section className="interaction-detail-pane">
      <header className="interaction-detail-header">
        <div><span>{selectedSession ? `${selectedSession.platformName} · ${formatDate(selectedSession.startedAt)}` : "场次互动"}</span><h3>{selectedSession?.title ?? "选择一个直播场次"}</h3></div>
        <label className="interaction-switch">
          <input type="checkbox" checked={showArrivals} onChange={(event) => { setShowArrivals(event.target.checked); setItemOffset(0); }} />
          <span>{showArrivals ? <Eye size={15} aria-hidden="true" /> : <EyeOff size={15} aria-hidden="true" />}</span>
          显示固定互动
        </label>
      </header>
      {selectedSession ? <div className="interaction-session-metrics">
        <span><strong>{selectedSession.storedInteractionCount}</strong>全部</span>
        <span><strong>{selectedSession.effectiveCount}</strong>有效互动</span>
        <span><strong>{selectedSession.arrivalCount}</strong>固定互动</span>
        <span><strong>{selectedSession.unansweredCount}</strong>未应答</span>
      </div> : null}
      <div className="interaction-table-toolbar">
        <label><Search size={15} aria-hidden="true" /><input aria-label="搜索场次互动" placeholder="搜索用户名、互动或回复" value={search} onChange={(event) => { setSearch(event.target.value); setItemOffset(0); }} /></label>
        <Pager offset={itemOffset} limit={50} total={itemsQuery.data?.total ?? 0} onChange={setItemOffset} />
      </div>
      <ErrorLine error={itemsQuery.error} />
      <div className="interaction-table-wrap">
        <table className="interaction-table">
          <thead><tr><th>用户 / 时间</th><th>商品 ID</th><th>用户互动内容</th><th>类型</th><th>数字人回复</th><th>弹幕回复</th><th>应答</th></tr></thead>
          <tbody>{(itemsQuery.data?.items ?? []).map((item) => <tr key={item.id}>
            <td><strong>{item.publisherName ?? "匿名用户"}</strong><small>{formatDate(item.publishedAt)}</small></td>
            <td>{item.itemId ?? "--"}</td>
            <td className="interaction-copy">{item.content || "--"}</td>
            <td><span className="interaction-type">{INTERACTION_TYPE_LABELS[item.interactionType] ?? `类型 ${item.interactionType}`}</span></td>
            <td className="interaction-reply">{item.digitalReplyContent ?? "--"}</td>
            <td className="interaction-reply">{item.bulletReplyContent ?? "--"}</td>
            <td>{item.answered ? <span className="interaction-answer is-answered"><CheckCircle2 size={14} />已应答</span> : <span className="interaction-answer is-unanswered"><CircleSlash2 size={14} />未应答</span>}</td>
          </tr>)}</tbody>
        </table>
        {!itemsQuery.isLoading && sessionId && !itemsQuery.data?.items.length ? <div className="interaction-empty"><MessageSquareText size={22} aria-hidden="true" /><span>没有符合条件的互动</span></div> : null}
      </div>
    </section>
  </div>;
}


function AnalysisRow({ item, expanded, onToggle }: {
  item: LiveInteraction;
  expanded: boolean;
  onToggle: () => void;
}) {
  const result = item.analysis;
  return <>
    <tr className={expanded ? "is-expanded" : undefined}>
      <td><button type="button" className="interaction-expand" title={expanded ? "收起详情" : "展开详情"} onClick={onToggle}>{expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button></td>
      <td><strong>{item.publisherName ?? "匿名用户"}</strong><small>{item.platformName} · {formatDate(item.publishedAt)}</small></td>
      <td className="interaction-copy"><strong>{item.content || "--"}</strong><small>{item.sessionTitle}</small></td>
      <td>{result ? FORM_LABELS[result.interactionForm] ?? result.interactionForm : <StatusPill value={item.analysisStatus} />}</td>
      <td>{result ? INTENT_LABELS[result.businessIntent] ?? result.businessIntent : "--"}</td>
      <td>{item.answered ? <span className="interaction-answer is-answered">已应答</span> : <span className="interaction-answer is-unanswered">未应答</span>}</td>
      <td><Grade value={result?.overallGrade} /></td>
    </tr>
    {expanded ? <tr className="interaction-analysis-detail"><td colSpan={7}>
      <div className="interaction-analysis-grid">
        <section><span>用户互动</span><p>{item.content || "--"}</p></section>
        <section><span>数字人回复</span><p>{item.digitalReplyContent ?? "--"}</p></section>
        <section><span>弹幕回复 · 仅展示</span><p>{item.bulletReplyContent ?? "--"}</p></section>
      </div>
      {result ? <div className="interaction-quality-line">
        <span>相关性 <Grade value={result.relevanceGrade} /></span>
        <span>完整性 <Grade value={result.completenessGrade} /></span>
        <span>解决程度 <Grade value={result.resolutionGrade} /></span>
        <p>{result.reason}</p>
        <small>置信度 {Math.round(result.confidence * 100)}% · {result.analyzerVersion}</small>
      </div> : <div className="interaction-analysis-wait"><Clock3 size={15} />等待分析</div>}
    </td></tr> : null}
  </>;
}


function InteractionAnalysisView() {
  const [platformId, setPlatformId] = useState<number>();
  const [answeredFilter, setAnsweredFilter] = useState<"all" | "answered" | "unanswered">("all");
  const [form, setForm] = useState("");
  const [intent, setIntent] = useState("");
  const [grade, setGrade] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string>();
  const platformsQuery = useQuery({ queryKey: ["interactions", "platforms"], queryFn: interactionsApi.platforms });
  const summaryQuery = useQuery({ queryKey: ["interactions", "analysis-summary"], queryFn: interactionsApi.analysisSummary, refetchInterval: 15_000 });
  const itemsQuery = useQuery({
    queryKey: ["interactions", "analysis-items", platformId, answeredFilter, form, intent, grade, search, offset],
    queryFn: () => interactionsApi.analysisItems({
      platformId,
      answered: answeredFilter === "all" ? undefined : answeredFilter === "answered",
      interactionForm: form || undefined,
      businessIntent: intent || undefined,
      overallGrade: grade || undefined,
      search,
      limit: 50,
      offset,
    }),
    refetchInterval: summaryQuery.data?.pending ? 15_000 : false,
  });
  const summary = summaryQuery.data;
  const resetPage = () => setOffset(0);

  return <div className="interaction-analysis-view">
    {!summary?.analysisConfigured ? <div className="interaction-config-state"><Bot size={17} aria-hidden="true" /><span>分析模型或处理授权尚未配置，采集数据会继续保存。</span></div> : null}
    <section className="interaction-summary-band">
      <div><span>有效互动</span><strong>{summary?.total ?? 0}</strong><small>{summary?.pending ?? 0} 条待分析</small></div>
      <div><span>已应答</span><strong>{summary?.answered ?? 0}</strong><small>仅数字人回复</small></div>
      <div><span>未应答</span><strong>{summary?.unanswered ?? 0}</strong><small>{summary?.total ? Math.round(((summary.unanswered ?? 0) / summary.total) * 100) : 0}%</small></div>
      <div><span>回答质量好</span><strong>{summary?.grades.good ?? 0}</strong><small>{summary?.analyzed ?? 0} 条已分析</small></div>
    </section>
    <section className="interaction-analysis-panel">
      <div className="interaction-filterbar">
        <label className="interaction-search"><Search size={15} aria-hidden="true" /><input aria-label="搜索互动分析" placeholder="搜索互动或回复" value={search} onChange={(event) => { setSearch(event.target.value); resetPage(); }} /></label>
        <select aria-label="直播平台" value={platformId ?? ""} onChange={(event) => { setPlatformId(event.target.value ? Number(event.target.value) : undefined); resetPage(); }}>
          <option value="">全部平台</option>
          {(platformsQuery.data ?? []).map((item) => <option key={item.externalPlatformId} value={item.externalPlatformId}>{item.platformName}</option>)}
        </select>
        <select aria-label="互动形式" value={form} onChange={(event) => { setForm(event.target.value); resetPage(); }}><option value="">全部形式</option>{Object.entries(FORM_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <select aria-label="业务意图" value={intent} onChange={(event) => { setIntent(event.target.value); resetPage(); }}><option value="">全部意图</option>{Object.entries(INTENT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <select aria-label="回答质量" value={grade} onChange={(event) => { setGrade(event.target.value); resetPage(); }}><option value="">全部质量</option>{Object.entries(GRADE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <div className="interaction-segments" aria-label="应答状态">
          {(["all", "answered", "unanswered"] as const).map((value) => <button type="button" key={value} className={answeredFilter === value ? "is-selected" : ""} onClick={() => { setAnsweredFilter(value); resetPage(); }}>{value === "all" ? "全部" : value === "answered" ? "已应答" : "未应答"}</button>)}
        </div>
      </div>
      <ErrorLine error={summaryQuery.error ?? itemsQuery.error} />
      <div className="interaction-table-wrap">
        <table className="interaction-table is-analysis">
          <thead><tr><th aria-label="展开" /><th>用户 / 平台</th><th>互动内容 / 场次</th><th>互动形式</th><th>业务意图</th><th>应答</th><th>整体质量</th></tr></thead>
          <tbody>{(itemsQuery.data?.items ?? []).map((item) => <AnalysisRow key={item.id} item={item} expanded={expandedId === item.id} onToggle={() => setExpandedId(expandedId === item.id ? undefined : item.id)} />)}</tbody>
        </table>
        {!itemsQuery.isLoading && !itemsQuery.data?.items.length ? <div className="interaction-empty"><MessageSquareText size={22} aria-hidden="true" /><span>没有符合条件的互动分析</span></div> : null}
      </div>
      <Pager offset={offset} limit={50} total={itemsQuery.data?.total ?? 0} onChange={setOffset} />
    </section>
  </div>;
}


export function InteractionProductPage() {
  const [view, setView] = useState<"records" | "analysis">("records");
  const queryClient = useQueryClient();
  const sourceQuery = useQuery({ queryKey: ["interactions", "source"], queryFn: interactionsApi.source, refetchInterval: 15_000 });
  const runsQuery = useQuery({ queryKey: ["interactions", "sync-runs"], queryFn: interactionsApi.syncRuns, refetchInterval: 10_000 });
  const syncMutation = useMutation({
    mutationFn: () => interactionsApi.startSync(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["interactions"] });
    },
  });
  const latestRun = runsQuery.data?.[0];
  const source = sourceQuery.data;
  const syncBusy = latestRun?.status === "queued" || latestRun?.status === "running" || latestRun?.status === "waiting_login";
  const subtitle = useMemo(() => {
    if (source?.lastErrorMessage) return source.lastErrorMessage;
    if (latestRun?.status === "running") return "正在同步直播记录";
    if (source?.lastIncrementalSyncAt || source?.lastFullSyncAt) return `上次同步 ${formatDate(source.lastIncrementalSyncAt ?? source.lastFullSyncAt)}`;
    return "等待首次全量同步";
  }, [latestRun?.status, source]);

  return <div className="interaction-page">
    <header className="interaction-page-header">
      <div><span>麦兔直播数据</span><h2>用户互动</h2><p>{subtitle}</p></div>
      <div className="interaction-page-actions">
        {source ? <StatusPill value={source.status} /> : null}
        {source?.nextSyncAt ? <span className="interaction-next-sync"><Clock3 size={14} aria-hidden="true" />下次 {formatDate(source.nextSyncAt)}</span> : null}
        <button type="button" className="interaction-sync-button" disabled={syncBusy || syncMutation.isPending} onClick={() => syncMutation.mutate()}>
          <RefreshCw size={16} aria-hidden="true" className={syncBusy ? "is-spinning" : undefined} />
          {syncBusy ? "同步中" : "立即同步"}
        </button>
      </div>
    </header>
    <ErrorLine error={sourceQuery.error ?? runsQuery.error ?? syncMutation.error} />
    {latestRun?.errorMessage ? <div className="interaction-error"><AlertCircle size={16} aria-hidden="true" /><span>{latestRun.errorMessage}</span></div> : null}
    <div className="interaction-tabs" role="tablist" aria-label="用户互动视图">
      <button type="button" role="tab" aria-selected={view === "records"} className={view === "records" ? "is-selected" : ""} onClick={() => setView("records")}><Database size={16} aria-hidden="true" />采集记录</button>
      <button type="button" role="tab" aria-selected={view === "analysis"} className={view === "analysis" ? "is-selected" : ""} onClick={() => setView("analysis")}><Bot size={16} aria-hidden="true" />互动分析</button>
    </div>
    {view === "records" ? <CollectionRecords /> : <InteractionAnalysisView />}
  </div>;
}
