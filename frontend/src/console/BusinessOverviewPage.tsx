import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Clapperboard,
  FolderKanban,
  MonitorUp,
  Plus,
  Radio,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "../product/components";
import { EmptyBlock, LoadingBlock, StatusBadge, formatDate } from "../workbench/components";
import { productLabel } from "../workbench/productLanguage";
import { consoleApi } from "./api";
import { DEMO_BUSINESS_OVERVIEW } from "./demoData";
import type { ConsoleBusinessOverview } from "./types";

const METRIC_ICONS = {
  projects: FolderKanban,
  live_rooms: MonitorUp,
  videos: Clapperboard,
  sessions: Radio,
};

function periodRange(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to);
  from.setUTCDate(from.getUTCDate() - days + 1);
  from.setUTCHours(0, 0, 0, 0);
  return { from: from.toISOString(), to: to.toISOString() };
}

function delta(value: number, previous: number): { label: string; direction: "up" | "down" | "flat" } {
  if (value === previous) return { label: "与上一周期持平", direction: "flat" };
  if (previous === 0) return { label: `较上一周期增加 ${value}`, direction: "up" };
  const percentage = Math.round(((value - previous) / previous) * 100);
  return { label: `较上一周期${percentage > 0 ? "增加" : "减少"} ${Math.abs(percentage)}%`, direction: percentage > 0 ? "up" : "down" };
}

function MetricBand({ overview }: { overview: ConsoleBusinessOverview }) {
  return <section className="business-metrics" aria-label="本周期业务指标">{overview.metrics.map((metric) => {
    const Icon = METRIC_ICONS[metric.key];
    const change = delta(metric.value, metric.previousValue);
    return <article key={metric.key}>
      <div className={`business-metric-icon is-${metric.key}`}><Icon size={18} aria-hidden="true" /></div>
      <div><span>{metric.label}</span><strong>{metric.value}<small>{metric.unit}</small></strong><p className={`is-${change.direction}`}>{change.label}</p></div>
    </article>;
  })}</section>;
}

function TrendPanel({ overview }: { overview: ConsoleBusinessOverview }) {
  const data = useMemo(() => overview.trend.map((item) => ({
    ...item,
    dateLabel: new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(item.date)),
  })), [overview.trend]);
  return <section className="business-panel business-trend">
    <header><div><h2>内容产出与运营场次</h2><p>按天查看直播间方案、成片和已关联运营场次</p></div><a href="/operations?view=attribution">查看运营分析<ArrowUpRight size={15} aria-hidden="true" /></a></header>
    <div className="business-chart" aria-label="内容产出趋势图">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 10, bottom: 0, left: -22 }}>
          <defs>
            <linearGradient id="sessions-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2f66b0" stopOpacity={0.24} /><stop offset="100%" stopColor="#2f66b0" stopOpacity={0.02} /></linearGradient>
            <linearGradient id="outputs-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#26805f" stopOpacity={0.2} /><stop offset="100%" stopColor="#26805f" stopOpacity={0.02} /></linearGradient>
          </defs>
          <CartesianGrid stroke="#e5e9e6" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="dateLabel" tick={{ fill: "#738078", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={28} />
          <YAxis allowDecimals={false} tick={{ fill: "#738078", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={{ border: "1px solid #dfe5e1", borderRadius: 6, boxShadow: "0 8px 24px rgb(20 32 25 / 12%)", fontSize: 12 }} />
          <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
          <Area type="monotone" dataKey="sessions" name="运营场次" stroke="#2f66b0" strokeWidth={2} fill="url(#sessions-fill)" />
          <Area type="monotone" dataKey="liveRooms" name="直播间方案" stroke="#26805f" strokeWidth={2} fill="url(#outputs-fill)" />
          <Area type="monotone" dataKey="videos" name="成片" stroke="#b26a25" strokeWidth={2} fill="transparent" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  </section>;
}

function RankingPanel({ overview }: { overview: ConsoleBusinessOverview }) {
  return <section className="business-panel business-ranking">
    <header><div><h2>近期活跃内容</h2><p>按已关联运营场次数排序</p></div></header>
    {overview.rankings.length ? <div className="business-ranking-list">{overview.rankings.map((item, index) => <a key={item.projectCode} href={`/projects?project=${encodeURIComponent(item.projectCode)}&tab=activity`}>
      <b>{index + 1}</b><span><strong>{item.title}</strong><small>{item.lastSessionAt ? `最近场次 ${formatDate(item.lastSessionAt)}` : "暂无场次时间"}</small></span><em>{item.sessionCount}<small>场</small></em><ArrowUpRight size={15} aria-hidden="true" />
    </a>)}</div> : <EmptyBlock title="本周期还没有已关联场次" detail="导入运营数据并关联内容项目后，这里会显示活跃内容。" />}
  </section>;
}

function CoveragePanel({ overview }: { overview: ConsoleBusinessOverview }) {
  const coverage = overview.coverage;
  const boundRate = coverage.totalSessions ? Math.round((coverage.boundSessions / coverage.totalSessions) * 100) : 0;
  const items = [
    { label: "可用素材", value: coverage.readyAssets, unit: "份", tone: "green" },
    { label: "已发布模板", value: coverage.publishedTemplates, unit: "个", tone: "blue" },
    { label: "已批准事实", value: coverage.approvedFacts, unit: "条", tone: "amber" },
  ];
  return <section className="business-panel business-coverage">
    <header><div><h2>生产资料覆盖</h2><p>生成内容前可直接使用的资料</p></div></header>
    <div className="business-coverage-counts">{items.map((item) => <div key={item.label}><span>{item.label}</span><strong>{item.value}<small>{item.unit}</small></strong><i className={`is-${item.tone}`} /></div>)}</div>
    <div className="business-coverage-rate"><div><span>运营场次关联率</span><strong>{boundRate}%</strong></div><div><i style={{ width: `${boundRate}%` }} /></div><small>{coverage.boundSessions} / {coverage.totalSessions} 场已关联到内容项目</small></div>
  </section>;
}

function RecentProjects({ overview }: { overview: ConsoleBusinessOverview }) {
  return <section className="business-panel business-projects">
    <header><div><h2>最近项目</h2><p>继续正在推进的内容生产</p></div><a href="/projects">全部项目<ArrowUpRight size={15} aria-hidden="true" /></a></header>
    {overview.recentProjects.length ? <div className="business-project-table"><div className="business-project-head"><span>项目</span><span>产出</span><span>运营反馈</span><span>状态</span><span>最近更新</span><span /></div>{overview.recentProjects.map((project) => <a key={project.projectCode} href={`/projects?project=${encodeURIComponent(project.projectCode)}`}>
      <span><strong>{project.title}</strong></span>
      <span className="business-output-tags">{project.hasLiveRoom ? <i>直播间</i> : null}{project.hasVideo ? <i>成片</i> : null}{!project.hasLiveRoom && !project.hasVideo ? <small>尚未生成</small> : null}</span>
      <span>{project.sessionCount ? `${project.sessionCount} 场` : "待关联"}</span>
      <StatusBadge label={productLabel(project.status)} tone={project.status === "active" ? "success" : "neutral"} />
      <span>{formatDate(project.updatedAt)}</span>
      <ArrowUpRight size={15} aria-hidden="true" />
    </a>)}</div> : <EmptyBlock title="还没有内容项目" detail="创建第一个项目后，可以从这里继续简报、剧本、直播间和成片制作。" />}
  </section>;
}

export function BusinessOverviewPage({ demoMode, consoleDataAvailable }: { demoMode: boolean; consoleDataAvailable: boolean }) {
  const [days, setDays] = useState(30);
  const range = useMemo(() => periodRange(days), [days]);
  const overview = useQuery({
    queryKey: ["console", "business-overview", days, demoMode],
    queryFn: () => demoMode ? Promise.resolve(DEMO_BUSINESS_OVERVIEW) : consoleApi.businessOverview(range.from, range.to),
    enabled: demoMode || consoleDataAvailable,
  });

  return <div className="business-overview">
    <PageHeader eyebrow="业务概览" title="直播内容生产概览" description="查看内容产出、交付准备、运营反馈与资料覆盖情况。" actions={<><div className="business-period" role="group" aria-label="统计周期">{[30, 90].map((value) => <button key={value} type="button" className={days === value ? "active" : undefined} onClick={() => setDays(value)}>近 {value} 天</button>)}</div><a className="wb-button wb-button-primary" href="/projects?create=1"><Plus size={16} aria-hidden="true" />新建项目</a></>} />
    {overview.isLoading ? <LoadingBlock label="正在汇总业务数据" /> : overview.error || !overview.data ? <section className="business-panel"><EmptyBlock title={consoleDataAvailable ? "暂时无法读取业务概览" : "业务概览数据尚未连接"} detail={consoleDataAvailable ? "其他业务页面仍可正常使用，请稍后刷新。" : "可以先从素材库、直播模板或内容项目开始工作。"} /></section> : <>
      <MetricBand overview={overview.data} />
      <div className="business-grid"><TrendPanel overview={overview.data} /><RankingPanel overview={overview.data} /><CoveragePanel overview={overview.data} /></div>
      <RecentProjects overview={overview.data} />
    </>}
  </div>;
}
