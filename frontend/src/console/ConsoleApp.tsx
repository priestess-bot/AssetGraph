import { type FormEvent, type MouseEvent as ReactMouseEvent, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  BookOpen,
  BrainCircuit,
  ChartNoAxesCombined,
  ChevronRight,
  CircleUserRound,
  ClipboardList,
  Database,
  Film,
  FolderKanban,
  Images,
  LayoutDashboard,
  LogOut,
  Menu,
  MonitorUp,
  PackageCheck,
  Radio,
  RadioTower,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import type { ComponentType } from "react";
import { GeminiPage } from "../maitu/GeminiPage";
import { AssetLibraryPage } from "../assets/AssetLibraryPage";
import { ContentProjectsPage } from "../content/ContentProjectsPage";
import { LiveRoomPlannerPage } from "../live-rooms/LiveRoomPlannerPage";
import { VideoProductionPage } from "../videos/VideoProductionPage";
import { ReleaseWorkspacePage } from "../releases/ReleaseWorkspacePage";
import { OperationsPage } from "../operations/OperationsPage";
import { LearningPage } from "../learning/LearningPage";
import { KnowledgePage } from "../knowledge/KnowledgePage";
import { DataGovernancePage } from "../governance/DataGovernancePage";
import { SessionsPage } from "../live-research/SessionsPage";
import { ContentStrategiesPage } from "../live-research/ContentStrategiesPage";
import { TemplatesPage } from "../live-research/TemplatesPage";
import { WatchPage } from "../live-research/WatchPage";
import {
  WorkbenchApiError,
  hasWorkbenchAccessToken,
  setWorkbenchAccessToken,
  type WorkbenchProblem,
} from "../workbench/api";
import { EmptyBlock, ProblemNotice, StatusBadge, formatDate } from "../workbench/components";
import { consoleApi } from "./api";
import { DEMO_NOTIFICATIONS, DEMO_SEARCH, DEMO_SESSION, DEMO_TASKS } from "./demoData";
import { EntityInspector, type EntitySelection } from "./EntityInspector";
import type { ConsoleNotification, ConsoleSearchResult, ConsoleSession, ConsoleTask } from "./types";


interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean | "true" }>;
}

interface NavSection {
  label: string;
  items: NavItem[];
}


const NAVIGATION: NavSection[] = [
  { label: "工作", items: [{ href: "/console/", label: "我的任务与异常", icon: LayoutDashboard }] },
  { label: "内容基础", items: [
    { href: "/assets/library", label: "素材", icon: Images },
    { href: "/knowledge/facts", label: "知识库", icon: BookOpen },
    { href: "/research/live-sources", label: "直播研究", icon: RadioTower },
    { href: "/content/projects", label: "内容项目", icon: FolderKanban },
  ] },
  { label: "生产", items: [
    { href: "/production/live-rooms", label: "直播间", icon: MonitorUp },
    { href: "/production/videos", label: "成片", icon: Film },
    { href: "/production/releases", label: "发布", icon: PackageCheck },
  ] },
  { label: "运营与学习", items: [
    { href: "/operations/live-sessions", label: "运营场次", icon: Radio },
    { href: "/operations/attribution", label: "归因", icon: ChartNoAxesCombined },
    { href: "/learning/effects", label: "效果学习", icon: BrainCircuit },
  ] },
  { label: "控制", items: [{ href: "/governance/data", label: "数据治理", icon: Database }, { href: "/governance/runs", label: "治理与运行", icon: ShieldCheck }] },
];


function navigate(href: string): void {
  const next = new URL(href, window.location.origin);
  window.history.pushState(null, "", `${next.pathname}${next.search}${next.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}


function useLocation(): { pathname: string; search: string } {
  const [location, setLocation] = useState(() => ({ pathname: window.location.pathname, search: window.location.search }));
  useEffect(() => {
    const update = () => setLocation({ pathname: window.location.pathname, search: window.location.search });
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return location;
}


function isActive(pathname: string, href: string): boolean {
  if (href === "/console/") return pathname === "/" || pathname === "/console" || pathname === "/console/";
  return pathname === href || pathname.startsWith(`${href}/`);
}


function taskTone(status: string) {
  if (status === "running") return "info" as const;
  if (["waiting_human", "queued", "open", "claimed", "escalated", "reconcile_required"].includes(status)) return "warning" as const;
  if (["failed", "expired"].includes(status)) return "danger" as const;
  return "neutral" as const;
}


function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: "运行中",
    queued: "排队中",
    waiting_human: "等待人工",
    open: "待处理",
    claimed: "已领取",
    escalated: "已升级",
    reconcile_required: "需要对账",
    failed: "失败",
  };
  return labels[status] ?? status;
}


function errorProblem(error: unknown): WorkbenchProblem | undefined {
  if (error instanceof WorkbenchApiError && error.problem) return error.problem;
  if (!(error instanceof Error)) return undefined;
  return {
    code: "CONSOLE_REQUEST_FAILED",
    state: "error",
    message: error.message,
    impact: "Console 数据未加载，未执行任何写命令。",
    evidence: [],
    nextStep: "检查后端连接与登录凭据后重试。",
    retryable: false,
  };
}


function LoginPanel({ onAuthenticated }: { onAuthenticated: (session: ConsoleSession) => void }) {
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<WorkbenchProblem>();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setProblem(undefined);
    try {
      const session = await consoleApi.session(token);
      setWorkbenchAccessToken(token);
      setToken("");
      onAuthenticated(session);
    } catch (error) {
      setWorkbenchAccessToken();
      setProblem(errorProblem(error));
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <main className="console-login">
      <section>
        <div className="console-login-brand"><span>AG</span><div><strong>AssetGraph</strong><small>CONTENT OPERATIONS CONSOLE</small></div></div>
        <h1>运营控制台登录</h1>
        <form onSubmit={submit}>
          <label className="wb-field"><span>控制面访问凭据</span><input className="wb-input" type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} required /></label>
          <button className="wb-button wb-button-primary" type="submit" disabled={submitting || !token.trim()}>{submitting ? "正在验证" : "登录"}</button>
        </form>
        {problem ? <ProblemNotice problem={problem} /> : null}
        <div className="console-login-policy"><ShieldCheck size={16} aria-hidden="true" /><span>凭据仅保存在当前页面内存中，刷新或登出后清除。</span></div>
      </section>
    </main>
  );
}


function TaskRows({ tasks }: { tasks: ConsoleTask[] }) {
  if (!tasks.length) return <EmptyBlock icon={ClipboardList} title="当前没有待处理任务" />;
  return <div className="console-task-list">{tasks.map((task) => {
    const total = Math.max(0, task.progressTotal);
    const progress = total ? Math.round((task.progressCompleted / total) * 100) : 0;
    return <a key={task.itemCode} href={task.href} className="console-task-row">
      <span className="console-task-kind">{task.itemType === "human_task" ? "人工" : "运行"}</span>
      <span><strong>{task.title}</strong><small>{task.summary}</small><code>{task.itemCode}</code></span>
      <span className="console-task-progress"><span><i style={{ width: `${progress}%` }} /></span><small>{total ? `${task.progressCompleted}/${total}` : "--"}</small></span>
      <StatusBadge label={statusLabel(task.status)} tone={taskTone(task.status)} />
      <span className="console-task-time">{formatDate(task.dueAt ?? task.updatedAt)}</span>
      <ChevronRight size={16} aria-hidden="true" />
    </a>;
  })}</div>;
}


function NotificationRows({ notifications }: { notifications: ConsoleNotification[] }) {
  if (!notifications.length) return <EmptyBlock icon={Bell} title="当前没有未处理通知" />;
  return <div className="console-notification-list">{notifications.map((item) => <a key={item.notificationCode} href={item.href} className={`console-notification-row is-${item.state}`}>
    <AlertTriangle size={17} aria-hidden="true" />
    <span><strong>{item.title}</strong><small>{item.summary}</small><code>{item.notificationCode}</code></span>
    <span>{item.occurrenceCount > 1 ? `${item.occurrenceCount} 次` : formatDate(item.occurredAt)}</span>
    <ChevronRight size={16} aria-hidden="true" />
  </a>)}</div>;
}


function Dashboard({ tasks, notifications, loading }: { tasks: ConsoleTask[]; notifications: ConsoleNotification[]; loading: boolean }) {
  const waiting = tasks.filter((task) => task.itemType === "human_task" || task.status === "waiting_human").length;
  const running = tasks.filter((task) => task.status === "running").length;
  const critical = notifications.filter((item) => item.state === "error" || item.state === "reconcile_required").length;
  return <div className="console-dashboard">
    <div className="console-summary" aria-label="任务摘要">
      <div><span>我的待办</span><strong>{tasks.length}</strong><small>当前操作者范围</small></div>
      <div><span>等待人工</span><strong>{waiting}</strong><small>含升级事项</small></div>
      <div><span>运行中</span><strong>{running}</strong><small>后台持续执行</small></div>
      <div><span>异常与对账</span><strong>{critical}</strong><small>禁止盲目重试</small></div>
    </div>
    <section className="console-band">
      <header><div><span>PRIORITY QUEUE</span><h2>需要我处理</h2></div><a href="/governance/runs">查看所有运行<ChevronRight size={15} aria-hidden="true" /></a></header>
      {loading ? <div className="console-loading">正在读取任务控制面</div> : <TaskRows tasks={tasks} />}
    </section>
    <section className="console-band">
      <header><div><span>INTEGRITY & DELIVERY</span><h2>异常和对账</h2></div></header>
      {loading ? <div className="console-loading">正在读取证据告警</div> : <NotificationRows notifications={notifications} />}
    </section>
  </div>;
}


function ResearchWorkspace({ search, demoMode }: { search: string; demoMode: boolean }) {
  const view = new URLSearchParams(search).get("view") ?? "watch";
  const change = (next: string) => {
    const current = new URLSearchParams(search);
    const nextSearch = new URLSearchParams();
    if (demoMode || current.get("demo") === "1") nextSearch.set("demo", "1");
    if (next !== "watch") nextSearch.set("view", next);
    const encoded = nextSearch.toString();
    navigate(`/research/live-sources${encoded ? `?${encoded}` : ""}`);
  };
  return <>
    <div className="wb-tabs" role="tablist" aria-label="直播研究视图">
      {[ ["watch", "来源直播间"], ["sessions", "录屏场次"], ["strategies", "内容策略"], ["drafts", "模板草稿"], ["published", "已发布模板"] ].map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={view === key} className={view === key ? "active" : undefined} onClick={() => change(key)}>{label}</button>)}
    </div>
    {view === "watch" ? <WatchPage /> : view === "sessions" ? <SessionsPage key={`sessions:${search}`} /> : view === "strategies" ? <ContentStrategiesPage /> : <TemplatesPage published={view === "published"} />}
  </>;
}


function AssetsWorkspace({ search }: { search: string }) {
  const panel = new URLSearchParams(search).get("panel");
  return <>{panel === "analysis" ? <GeminiPage /> : <AssetLibraryPage />}</>;
}


export function Workspace({ pathname, search, tasks, notifications, loading, demoMode = false }: { pathname: string; search: string; tasks: ConsoleTask[]; notifications: ConsoleNotification[]; loading: boolean; demoMode?: boolean }) {
  if (pathname === "/" || pathname === "/console" || pathname === "/console/") return <Dashboard tasks={tasks} notifications={notifications} loading={loading} />;
  if (pathname.startsWith("/assets/library")) return <AssetsWorkspace search={search} />;
  if (pathname.startsWith("/research/live-sources")) return <ResearchWorkspace search={search} demoMode={demoMode} />;
  if (pathname.startsWith("/production/live-rooms")) {
    return <LiveRoomPlannerPage search={search} />;
  }
  if (pathname.startsWith("/governance/runs")) return <div className="console-band console-governance"><header><div><span>CONTROL PLANE</span><h2>任务与运行</h2></div></header><TaskRows tasks={tasks} /><NotificationRows notifications={notifications} /></div>;
  if (pathname.startsWith("/governance/data")) return <DataGovernancePage />;
  if (pathname.startsWith("/knowledge")) return <KnowledgePage />;
  if (pathname.startsWith("/content/projects")) return <ContentProjectsPage />;
  if (pathname.startsWith("/production/videos")) return <VideoProductionPage />;
  if (pathname.startsWith("/production/releases")) return <ReleaseWorkspacePage search={search} />;
  if (pathname.startsWith("/operations/live-sessions")) return <OperationsPage view="sessions" />;
  if (pathname.startsWith("/operations/attribution")) return <OperationsPage view="attribution" />;
  if (pathname.startsWith("/learning")) return <LearningPage />;
  return <section className="console-empty-workspace"><EmptyBlock icon={AlertTriangle} title="路由不存在" detail={pathname} /></section>;
}


function pageTitle(pathname: string): string {
  const item = NAVIGATION.flatMap((section) => section.items).find((candidate) => isActive(pathname, candidate.href));
  return item?.label ?? "AssetGraph Console";
}


function entitySelection(pathname: string, search: string): EntitySelection | undefined {
  const params = new URLSearchParams(search);
  const candidates: Array<{ pathname: string; queryKey: string; entityType: string }> = [
    { pathname: "/assets/library", queryKey: "asset", entityType: "asset" },
    { pathname: "/content/projects", queryKey: "project", entityType: "content_project" },
    { pathname: "/research/live-sources", queryKey: "template", entityType: "live_room_template" },
    { pathname: "/governance/runs", queryKey: "run", entityType: "workflow_run" },
    { pathname: "/production/releases", queryKey: "release", entityType: "release" },
  ];
  const candidate = candidates.find((item) => pathname === item.pathname || pathname.startsWith(`${item.pathname}/`));
  const entityCode = candidate ? params.get(candidate.queryKey)?.trim() : undefined;
  return candidate && entityCode ? { entityType: candidate.entityType, entityCode, queryKey: candidate.queryKey } : undefined;
}


export default function ConsoleApp() {
  const [demoMode] = useState(() => new URLSearchParams(window.location.search).get("demo") === "1");
  const [session, setSession] = useState<ConsoleSession | undefined>(() => demoMode ? DEMO_SESSION : undefined);
  const [navOpen, setNavOpen] = useState(false);
  const [drawer, setDrawer] = useState<"tasks" | "notifications">();
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const location = useLocation();

  const tasksQuery = useQuery({
    queryKey: ["console", "tasks", demoMode],
    queryFn: () => demoMode ? Promise.resolve(DEMO_TASKS) : consoleApi.tasks(),
    enabled: Boolean(session),
    refetchInterval: demoMode ? false : 15_000,
  });
  const notificationsQuery = useQuery({
    queryKey: ["console", "notifications", demoMode],
    queryFn: () => demoMode ? Promise.resolve(DEMO_NOTIFICATIONS) : consoleApi.notifications(),
    enabled: Boolean(session),
    refetchInterval: demoMode ? false : 15_000,
  });
  const searchQuery = useQuery({
    queryKey: ["console", "search", searchText, demoMode],
    queryFn: () => demoMode
      ? Promise.resolve(DEMO_SEARCH.filter((item) => `${item.title} ${item.entityCode}`.toLowerCase().includes(searchText.toLowerCase())))
      : consoleApi.search(searchText),
    enabled: Boolean(session) && searchText.trim().length >= 2,
  });

  const tasks = tasksQuery.data ?? [];
  const notifications = notificationsQuery.data ?? [];
  const queryProblem = errorProblem(tasksQuery.error ?? notificationsQuery.error);
  const searchResults = searchQuery.data ?? [];
  const heading = pageTitle(location.pathname);
  const selectedEntity = entitySelection(location.pathname, location.search);

  useEffect(() => {
    if (!hasWorkbenchAccessToken() && !demoMode) setSession(undefined);
  }, [demoMode]);

  const logout = () => {
    setWorkbenchAccessToken();
    setSession(undefined);
    setDrawer(undefined);
  };
  const handleInternalLink = (event: ReactMouseEvent<HTMLDivElement>) => {
    const anchor = (event.target as HTMLElement).closest("a");
    if (!anchor || anchor.target || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const url = new URL(anchor.href, window.location.origin);
    if (url.origin !== window.location.origin || url.pathname.startsWith("/api/")) return;
    event.preventDefault();
    navigate(`${url.pathname}${url.search}${url.hash}`);
    setNavOpen(false);
    setDrawer(undefined);
    setSearchOpen(false);
  };
  const closeEntityInspector = () => {
    if (!selectedEntity) return;
    const params = new URLSearchParams(location.search);
    params.delete(selectedEntity.queryKey);
    const nextSearch = params.toString();
    navigate(`${location.pathname}${nextSearch ? `?${nextSearch}` : ""}`);
  };

  if (!session) return <LoginPanel onAuthenticated={setSession} />;

  return <div className="console-shell" onClickCapture={handleInternalLink}>
    <aside className={`console-sidebar ${navOpen ? "is-open" : ""}`}>
      <div className="console-brand"><span>AG</span><div><strong>AssetGraph</strong><small>OPERATIONS CONSOLE</small></div><button type="button" className="console-icon console-nav-close" title="关闭导航" onClick={() => setNavOpen(false)}><X size={18} aria-hidden="true" /></button></div>
      <nav aria-label="一级产品导航">{NAVIGATION.map((section) => <div key={section.label} className="console-nav-section"><span>{section.label}</span>{section.items.map((item) => { const Icon = item.icon; const active = isActive(location.pathname, item.href); return <a key={item.href} href={item.href} className={active ? "active" : undefined} aria-current={active ? "page" : undefined}><Icon size={17} aria-hidden="true" /><strong>{item.label}</strong>{item.href === "/governance/runs" && tasks.length ? <b>{tasks.length}</b> : null}</a>; })}</div>)}</nav>
      <div className="console-safety"><ShieldCheck size={15} aria-hidden="true" /><span>正式开播能力</span><strong>全局禁用</strong></div>
    </aside>
    {navOpen ? <button type="button" className="console-scrim" aria-label="关闭导航" onClick={() => setNavOpen(false)} /> : null}
    <div className="console-body">
      <header className="console-topbar">
        <button type="button" className="console-icon console-menu" title="打开导航" onClick={() => setNavOpen(true)}><Menu size={19} aria-hidden="true" /></button>
        <div className="console-page-title"><span>ASSETGRAPH</span><h1>{heading}</h1></div>
        <div className="console-global-search">
          <Search size={16} aria-hidden="true" />
          <input aria-label="全局搜索" placeholder="搜索实体编码或名称" value={searchText} onFocus={() => setSearchOpen(true)} onChange={(event) => { setSearchText(event.target.value); setSearchOpen(true); }} />
          {searchOpen && searchText.trim().length >= 2 ? <div className="console-search-results">
            {searchQuery.isLoading ? <span>正在搜索</span> : searchResults.length ? searchResults.map((result: ConsoleSearchResult) => <a key={`${result.entityType}:${result.entityCode}`} href={result.href}><Search size={14} aria-hidden="true" /><span><strong>{result.title}</strong><code>{result.entityCode}{result.revision ? ` · r${result.revision}` : ""}</code></span><StatusBadge label={result.status} tone="neutral" /></a>) : <span>没有匹配结果</span>}
          </div> : null}
        </div>
        <div className="console-actions">
          <button type="button" className="console-icon" title="任务中心" onClick={() => setDrawer(drawer === "tasks" ? undefined : "tasks")}><ClipboardList size={18} aria-hidden="true" />{tasks.length ? <b>{tasks.length}</b> : null}</button>
          <button type="button" className="console-icon" title="通知" onClick={() => setDrawer(drawer === "notifications" ? undefined : "notifications")}><Bell size={18} aria-hidden="true" />{notifications.length ? <b>{notifications.length}</b> : null}</button>
          <div className="console-user"><CircleUserRound size={18} aria-hidden="true" /><span><strong>{session.operatorId}</strong><small>{session.roles[0]}</small></span><button type="button" className="console-icon" title="登出" onClick={logout}><LogOut size={16} aria-hidden="true" /></button></div>
        </div>
      </header>
      <main className={`console-main ${selectedEntity ? "has-entity-inspector" : ""}`}>
        <div className="console-workspace">
          {queryProblem ? <ProblemNotice problem={queryProblem} /> : null}
          <Workspace pathname={location.pathname} search={location.search} tasks={tasks} notifications={notifications} loading={tasksQuery.isLoading || notificationsQuery.isLoading} demoMode={demoMode} />
        </div>
        {selectedEntity ? <EntityInspector selection={selectedEntity} demoMode={demoMode} onClose={closeEntityInspector} /> : null}
      </main>
    </div>
    {drawer ? <aside className="console-drawer" aria-label={drawer === "tasks" ? "任务中心" : "通知中心"}><header><div><span>{drawer === "tasks" ? "CONTROL PLANE" : "EVIDENCE ALERTS"}</span><h2>{drawer === "tasks" ? "任务中心" : "通知"}</h2></div><button type="button" className="console-icon" title="关闭" onClick={() => setDrawer(undefined)}><X size={18} aria-hidden="true" /></button></header>{drawer === "tasks" ? <TaskRows tasks={tasks} /> : <NotificationRows notifications={notifications} />}</aside> : null}
  </div>;
}
