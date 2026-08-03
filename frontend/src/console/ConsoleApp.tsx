import { type MouseEvent as ReactMouseEvent, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  ChevronRight,
  CircleUserRound,
  ClipboardList,
  LogOut,
  Menu,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { AssetLibraryProductPage } from "../assets/AssetLibraryProductPage";
import { ProjectHubPage } from "../content/ProjectHubPage";
import { LiveRoomEditorProductPage } from "../live-rooms/LiveRoomEditorProductPage";
import { VideoEditorProductPage } from "../videos/VideoEditorProductPage";
import { DeliveryProductPanel } from "../releases/DeliveryProductPanel";
import { OperationsProductPage } from "../operations/OperationsProductPage";
import { LearningProductPage } from "../learning/LearningProductPage";
import { KnowledgeProductPage } from "../knowledge/KnowledgeProductPage";
import { TemplateLibraryProductPage } from "../live-research/TemplateLibraryProductPage";
import { InteractionProductPage } from "../interactions/InteractionProductPage";
import {
  WorkbenchApiError,
  hasWorkbenchAccessToken,
  setWorkbenchAccessToken,
  type WorkbenchProblem,
} from "../workbench/api";
import { EmptyBlock, ProblemNotice, StatusBadge, formatDate } from "../workbench/components";
import { problemPresentation, productCopy, productLabel, productTitle } from "../workbench/productLanguage";
import { LEGACY_ROUTE_MAP, PRODUCT_ROUTES, productPageTitle, routeIsActive } from "../product/routes";
import { consoleApi } from "./api";
import { DEMO_NOTIFICATIONS, DEMO_SEARCH, DEMO_SESSION, DEMO_TASKS } from "./demoData";
import type { ConsoleNotification, ConsoleSearchResult, ConsoleSession, ConsoleTask } from "./types";
import { BusinessOverviewPage } from "./BusinessOverviewPage";


const CONSOLE_BASE_PATH = "/console";


function consoleBrowserPath(pathname: string): string {
  if (pathname === CONSOLE_BASE_PATH || pathname.startsWith(`${CONSOLE_BASE_PATH}/`)) return pathname;
  return `${CONSOLE_BASE_PATH}${pathname === "/" ? "/" : pathname}`;
}


function workspacePath(pathname: string): string {
  if (pathname === CONSOLE_BASE_PATH || pathname === `${CONSOLE_BASE_PATH}/`) return "/console/";
  if (pathname.startsWith(`${CONSOLE_BASE_PATH}/`)) return pathname.slice(CONSOLE_BASE_PATH.length);
  return pathname;
}


function navigate(href: string): void {
  const next = new URL(href, window.location.origin);
  const legacy = LEGACY_ROUTE_MAP.find(([prefix]) => next.pathname === prefix || next.pathname.startsWith(`${prefix}/`));
  const pathname = legacy ? next.pathname.replace(legacy[0], legacy[1]) : next.pathname;
  window.history.pushState(null, "", `${consoleBrowserPath(pathname)}${next.search}${next.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}


function useLocation(): { pathname: string; search: string } {
  const current = () => ({ pathname: workspacePath(window.location.pathname), search: window.location.search });
  const [location, setLocation] = useState(current);
  useEffect(() => {
    const update = () => setLocation(current());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return location;
}


function taskTone(status: string) {
  if (status === "running") return "info" as const;
  if (["waiting_human", "queued", "open", "claimed", "escalated", "reconcile_required"].includes(status)) return "warning" as const;
  if (["failed", "expired"].includes(status)) return "danger" as const;
  return "neutral" as const;
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
    nextStep: "检查服务连接后重试。",
    retryable: false,
  };
}


function TaskRows({ tasks }: { tasks: ConsoleTask[] }) {
  if (!tasks.length) return <EmptyBlock icon={ClipboardList} title="当前没有待处理任务" />;
  return <div className="console-task-list">{tasks.map((task) => {
    const total = Math.max(0, task.progressTotal);
    const progress = total ? Math.round((task.progressCompleted / total) * 100) : 0;
    const href = task.href.startsWith("/governance/") ? "/projects?view=activity" : task.href;
    return <a key={task.itemCode} href={href} className="console-task-row">
      <span className="console-task-kind">{task.itemType === "human_task" ? "待办" : "进度"}</span>
      <span><strong>{productCopy(task.title, task.itemType === "human_task" ? "有一项内容需要确认" : "内容正在处理中")}</strong><small>{productCopy(task.summary, "打开相关内容查看处理建议")}</small></span>
      <span className="console-task-progress"><span><i style={{ width: `${progress}%` }} /></span><small>{total ? `${task.progressCompleted}/${total}` : "--"}</small></span>
      <StatusBadge label={productLabel(task.status)} tone={taskTone(task.status)} />
      <span className="console-task-time">{formatDate(task.dueAt ?? task.updatedAt)}</span>
      <ChevronRight size={16} aria-hidden="true" />
    </a>;
  })}</div>;
}


function NotificationRows({ notifications }: { notifications: ConsoleNotification[] }) {
  if (!notifications.length) return <EmptyBlock icon={Bell} title="当前没有未处理通知" />;
  return <div className="console-notification-list">{notifications.map((item) => { const copy = problemPresentation({ code: item.title, state: item.state }); return <a key={item.notificationCode} href={item.href.startsWith("/governance/") ? "/projects?view=activity" : item.href} className={`console-notification-row is-${item.state}`}>
    <AlertTriangle size={17} aria-hidden="true" />
    <span><strong>{copy.title}</strong><small>{productCopy(item.summary, copy.impact)}</small></span>
    <span>{item.occurrenceCount > 1 ? `${item.occurrenceCount} 次` : formatDate(item.occurredAt)}</span>
    <ChevronRight size={16} aria-hidden="true" />
  </a>; })}</div>;
}


function AssetsWorkspace({ search }: { search: string }) {
  return <AssetLibraryProductPage search={search} />;
}


export function Workspace({ pathname, search, demoMode = false, consoleDataAvailable = false }: { pathname: string; search: string; tasks: ConsoleTask[]; notifications: ConsoleNotification[]; loading: boolean; demoMode?: boolean; consoleDataAvailable?: boolean }) {
  if (pathname === "/" || pathname === "/console" || pathname === "/console/") return <BusinessOverviewPage demoMode={demoMode} consoleDataAvailable={consoleDataAvailable} />;
  if (pathname.startsWith("/assets")) return <AssetsWorkspace search={search} />;
  if (pathname.startsWith("/templates")) return <TemplateLibraryProductPage search={search} />;
  if (pathname.startsWith("/projects")) return <ProjectHubPage search={search} />;
  if (pathname.startsWith("/operations")) {
    const view = new URLSearchParams(search).get("view");
    const next = view === "attribution" ? "analysis" : view === "bindings" || view === "settings" ? view : "imports";
    return <OperationsProductPage initialView={next} />;
  }
  if (pathname.startsWith("/interactions")) return <InteractionProductPage />;
  if (pathname.startsWith("/learning")) return <LearningProductPage />;
  if (pathname.startsWith("/production/live-rooms")) {
    return <LiveRoomEditorProductPage search={search} />;
  }
  if (pathname.startsWith("/knowledge")) return <KnowledgeProductPage search={search} />;
  if (pathname.startsWith("/production/videos")) return <VideoEditorProductPage search={search} />;
  if (pathname.startsWith("/production/releases")) return <DeliveryProductPanel search={search} />;
  return <section className="console-empty-workspace"><EmptyBlock icon={AlertTriangle} title="路由不存在" detail={pathname} /></section>;
}


function pageTitle(pathname: string): string {
  return productPageTitle(pathname);
}


export default function ConsoleApp() {
  const [demoMode] = useState(() => new URLSearchParams(window.location.search).get("demo") === "1");
  const localSession: ConsoleSession = { operatorId: "当前工作区", roles: [], authScheme: "local_workspace" };
  const [session, setSession] = useState<ConsoleSession>(() => demoMode ? DEMO_SESSION : localSession);
  const [navOpen, setNavOpen] = useState(false);
  const [drawer, setDrawer] = useState<"tasks" | "notifications">();
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const location = useLocation();
  const consoleDataAvailable = demoMode || hasWorkbenchAccessToken();

  const tasksQuery = useQuery({
    queryKey: ["console", "tasks", demoMode],
    queryFn: () => demoMode ? Promise.resolve(DEMO_TASKS) : consoleApi.tasks(),
    enabled: Boolean(session) && consoleDataAvailable,
    refetchInterval: demoMode ? false : 15_000,
  });
  const notificationsQuery = useQuery({
    queryKey: ["console", "notifications", demoMode],
    queryFn: () => demoMode ? Promise.resolve(DEMO_NOTIFICATIONS) : consoleApi.notifications(),
    enabled: Boolean(session) && consoleDataAvailable,
    refetchInterval: demoMode ? false : 15_000,
  });
  const searchQuery = useQuery({
    queryKey: ["console", "search", searchText, demoMode],
    queryFn: () => demoMode
      ? Promise.resolve(DEMO_SEARCH.filter((item) => `${item.title} ${item.entityCode}`.toLowerCase().includes(searchText.toLowerCase())))
      : consoleApi.search(searchText),
    enabled: Boolean(session) && consoleDataAvailable && searchText.trim().length >= 2,
  });

  const tasks = tasksQuery.data ?? [];
  const notifications = notificationsQuery.data ?? [];
  const queryProblem = errorProblem(tasksQuery.error ?? notificationsQuery.error);
  const searchResults = searchQuery.data ?? [];
  const heading = pageTitle(location.pathname);

  const logout = () => {
    setWorkbenchAccessToken();
    setSession(localSession);
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
  return <div className="console-shell" onClickCapture={handleInternalLink}>
    <aside className={`console-sidebar ${navOpen ? "is-open" : ""}`}>
      <div className="console-brand"><span>AG</span><div><strong>AssetGraph</strong><small>直播内容运营</small></div><button type="button" className="console-icon console-nav-close" title="关闭导航" onClick={() => setNavOpen(false)}><X size={18} aria-hidden="true" /></button></div>
      <nav aria-label="一级产品导航"><div className="console-nav-section"><span>直播内容运营</span>{PRODUCT_ROUTES.map((item) => { const Icon = item.icon; const active = routeIsActive(location.pathname, item); return <a key={item.path} href={item.path} className={active ? "active" : undefined} aria-current={active ? "page" : undefined} title={item.description}><Icon size={17} aria-hidden="true" /><strong>{item.label}</strong>{item.path === "/projects" && tasks.length ? <b>{tasks.length}</b> : null}</a>; })}</div></nav>
      <div className="console-safety"><ShieldCheck size={15} aria-hidden="true" /><span>正式开播能力</span><strong>全局禁用</strong></div>
    </aside>
    {navOpen ? <button type="button" className="console-scrim" aria-label="关闭导航" onClick={() => setNavOpen(false)} /> : null}
    <div className="console-body">
      <header className="console-topbar">
        <button type="button" className="console-icon console-menu" title="打开导航" onClick={() => setNavOpen(true)}><Menu size={19} aria-hidden="true" /></button>
        <div className="console-page-title"><span>直播内容工作台</span><h1>{heading}</h1></div>
        <div className="console-global-search">
          <Search size={16} aria-hidden="true" />
          <input aria-label="全局搜索" placeholder="搜索素材、模板、知识或项目" value={searchText} onFocus={() => setSearchOpen(true)} onChange={(event) => { setSearchText(event.target.value); setSearchOpen(true); }} />
          {searchOpen && searchText.trim().length >= 2 ? <div className="console-search-results">
            {searchQuery.isLoading ? <span>正在搜索</span> : searchResults.length ? searchResults.map((result: ConsoleSearchResult) => <a key={`${result.entityType}:${result.entityCode}`} href={result.href}><Search size={14} aria-hidden="true" /><span><strong>{productTitle(result.title, "未命名内容")}</strong><small>{productLabel(result.entityType, "业务内容")} · {formatDate(result.updatedAt)}</small></span><StatusBadge label={result.status} tone="neutral" /></a>) : <span>没有匹配结果</span>}
          </div> : null}
        </div>
        <div className="console-actions">
          <button type="button" className="console-icon" title="任务中心" onClick={() => setDrawer(drawer === "tasks" ? undefined : "tasks")}><ClipboardList size={18} aria-hidden="true" />{tasks.length ? <b>{tasks.length}</b> : null}</button>
          <button type="button" className="console-icon" title="通知" onClick={() => setDrawer(drawer === "notifications" ? undefined : "notifications")}><Bell size={18} aria-hidden="true" />{notifications.length ? <b>{notifications.length}</b> : null}</button>
          <div className="console-user"><CircleUserRound size={18} aria-hidden="true" /><span><strong>{session.operatorId}</strong><small>{demoMode ? "演示数据" : consoleDataAvailable ? "已连接" : "浏览工作区"}</small></span>{hasWorkbenchAccessToken() ? <button type="button" className="console-icon" title="断开连接" onClick={logout}><LogOut size={16} aria-hidden="true" /></button> : null}</div>
        </div>
      </header>
      <main className="console-main">
        <div className="console-workspace">
          {queryProblem ? <ProblemNotice problem={queryProblem} /> : null}
          <Workspace pathname={location.pathname} search={location.search} tasks={tasks} notifications={notifications} loading={tasksQuery.isLoading || notificationsQuery.isLoading} demoMode={demoMode} consoleDataAvailable={consoleDataAvailable} />
        </div>
      </main>
    </div>
    {drawer ? <aside className="console-drawer" aria-label={drawer === "tasks" ? "任务中心" : "通知中心"}><header><div><span>{drawer === "tasks" ? "跨项目协作" : "业务提醒"}</span><h2>{drawer === "tasks" ? "任务中心" : "通知"}</h2></div><button type="button" className="console-icon" title="关闭" onClick={() => setDrawer(undefined)}><X size={18} aria-hidden="true" /></button></header>{drawer === "tasks" ? <TaskRows tasks={tasks} /> : <NotificationRows notifications={notifications} />}</aside> : null}
  </div>;
}
