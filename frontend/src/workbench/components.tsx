import { type ComponentType, type ReactNode, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  FlaskConical,
  Menu,
  RefreshCw,
  RadioTower,
  Workflow,
  X,
} from "lucide-react";
import type { OperationalState, WorkbenchProblem } from "./api";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export interface ProductNavItem {
  href: string;
  label: string;
  detail: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean | "true" }>;
  active?: boolean;
}

interface WorkbenchShellProps {
  eyebrow: string;
  title: string;
  status?: ReactNode;
  children: ReactNode;
  navItems?: ProductNavItem[];
}

const DEFAULT_NAV: ProductNavItem[] = [
  { href: "/production/live-rooms", label: "生产工作台", detail: "故事到麦兔草稿", icon: Workflow },
  { href: "/research/live-sources", label: "模板工坊", detail: "直播采集与模板", icon: RadioTower },
];

export function WorkbenchShell({ eyebrow, title, status, children, navItems = DEFAULT_NAV }: WorkbenchShellProps) {
  const [navOpen, setNavOpen] = useState(false);
  return (
    <div className="wb-shell">
      <header className="wb-mobilebar">
        <button type="button" className="wb-icon-button" onClick={() => setNavOpen(true)} title="打开导航">
          <Menu size={19} aria-hidden="true" />
        </button>
        <strong>AssetGraph</strong>
        {status ?? <span />}
      </header>
      <aside className={`wb-sidebar ${navOpen ? "is-open" : ""}`} aria-label="产品导航">
        <div className="wb-brand">
          <span aria-hidden="true">AG</span>
          <div><strong>AssetGraph</strong><small>CONTENT OPERATIONS</small></div>
          <button type="button" className="wb-icon-button wb-close-nav" onClick={() => setNavOpen(false)} title="关闭导航">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <a key={item.href} href={item.href} className={item.active ? "active" : undefined} aria-current={item.active ? "page" : undefined}>
                <Icon size={18} aria-hidden="true" />
                <span><strong>{item.label}</strong><small>{item.detail}</small></span>
                <ChevronRight size={15} aria-hidden="true" />
              </a>
            );
          })}
        </nav>
        <div className="wb-sidebar-foot">
          <CircleDot size={14} aria-hidden="true" />
          <span>草稿执行边界</span>
          <strong>禁止自动开播</strong>
        </div>
      </aside>
      {navOpen ? <button className="wb-nav-scrim" aria-label="关闭导航" onClick={() => setNavOpen(false)} /> : null}
      <div className="wb-body">
        <header className="wb-pagebar">
          <div><span>{eyebrow}</span><h1>{title}</h1></div>
          {status}
        </header>
        <main className="wb-main">{children}</main>
      </div>
    </div>
  );
}

export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return <span className={`wb-status wb-status-${tone}`}><span aria-hidden="true" />{label}</span>;
}

export function SectionHeader({ kicker, title, actions }: { kicker?: string; title: string; actions?: ReactNode }) {
  return (
    <div className="wb-section-header">
      <div>{kicker ? <span>{kicker}</span> : null}<h2>{title}</h2></div>
      {actions ? <div className="wb-header-actions">{actions}</div> : null}
    </div>
  );
}

export function InlineNotice({ tone = "info", title, children }: { tone?: Tone; title: string; children?: ReactNode }) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "warning" || tone === "danger" ? AlertTriangle : FlaskConical;
  return (
    <div className={`wb-notice wb-notice-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon size={17} aria-hidden="true" />
      <div><strong>{title}</strong>{children ? <span>{children}</span> : null}</div>
    </div>
  );
}

export function operationalTone(state: OperationalState): Tone {
  if (state === "error") return "danger";
  if (state === "insufficient_data") return "info";
  return "warning";
}

export function ProblemNotice({ problem }: { problem: WorkbenchProblem }) {
  return (
    <div className={`wb-problem wb-notice wb-notice-${operationalTone(problem.state)}`} role={problem.state === "error" ? "alert" : "status"}>
      <AlertTriangle size={17} aria-hidden="true" />
      <div>
        <div className="wb-problem-heading"><strong>{problem.message}</strong><code>{problem.code}</code></div>
        <dl>
          <div><dt>影响</dt><dd>{problem.impact}</dd></div>
          <div><dt>下一步</dt><dd>{problem.nextStep}</dd></div>
          {problem.evidence.length ? <div><dt>证据</dt><dd>{problem.evidence.map((item) => <code key={`${item.kind}:${item.ref}`}>{item.kind}:{item.ref}</code>)}</dd></div> : null}
        </dl>
      </div>
    </div>
  );
}

export function LoadingBlock({ label = "正在读取数据" }: { label?: string }) {
  return <div className="wb-loading"><RefreshCw className="wb-spin" size={19} aria-hidden="true" /><span>{label}</span></div>;
}

export function EmptyBlock({ icon: Icon = FlaskConical, title, detail }: { icon?: typeof FlaskConical; title: string; detail?: string }) {
  return <div className="wb-empty"><Icon size={27} strokeWidth={1.5} aria-hidden="true" /><strong>{title}</strong>{detail ? <span>{detail}</span> : null}</div>;
}

export function Metric({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return <div className="wb-metric"><span>{label}</span><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</div>;
}

export function formatDate(value?: string | null): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function formatDuration(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const remainder = Math.floor(safe % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}
