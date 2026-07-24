import { useState } from "react";
import { Archive, BookOpenCheck, Film, Layers3, RadioTower, Workflow } from "lucide-react";
import { ContentStrategiesPage } from "./ContentStrategiesPage";
import { StatusBadge, WorkbenchShell } from "../workbench/components";
import { SessionsPage } from "./SessionsPage";
import { TemplatesPage } from "./TemplatesPage";
import { WatchPage } from "./WatchPage";

type ViewKey = "watch" | "sessions" | "drafts" | "published" | "strategies";

function initialView(): ViewKey {
  const value = new URLSearchParams(window.location.search).get("view");
  return value === "sessions" || value === "drafts" || value === "published" || value === "strategies" ? value : "watch";
}

export default function LiveResearchApp() {
  const [view, setView] = useState<ViewKey>(initialView);
  const changeView = (next: ViewKey) => {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "watch") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    window.history.replaceState(null, "", url);
  };
  return <WorkbenchShell
    eyebrow="DOUYIN TEMPLATE RESEARCH"
    title="直播模板工坊"
    status={<StatusBadge label="研究采集运行中" tone="info" />}
    navItems={[
      { href: "/production/live-rooms", label: "生产工作台", detail: "故事到麦兔草稿", icon: Workflow },
      { href: "/research/live-sources", label: "模板工坊", detail: "直播采集与模板", icon: RadioTower, active: true },
    ]}
  >
    <div className="wb-tabs research-tabs" role="tablist" aria-label="模板工坊视图">
      <button type="button" role="tab" aria-selected={view === "watch"} className={view === "watch" ? "active" : undefined} onClick={() => changeView("watch")}><RadioTower size={15} aria-hidden="true" />长期值守</button>
      <button type="button" role="tab" aria-selected={view === "sessions"} className={view === "sessions" ? "active" : undefined} onClick={() => changeView("sessions")}><Film size={15} aria-hidden="true" />采集场次</button>
      <button type="button" role="tab" aria-selected={view === "drafts"} className={view === "drafts" ? "active" : undefined} onClick={() => changeView("drafts")}><Layers3 size={15} aria-hidden="true" />模板草稿</button>
      <button type="button" role="tab" aria-selected={view === "published"} className={view === "published" ? "active" : undefined} onClick={() => changeView("published")}><Archive size={15} aria-hidden="true" />已发布模板</button>
      <button type="button" role="tab" aria-selected={view === "strategies"} className={view === "strategies" ? "active" : undefined} onClick={() => changeView("strategies")}><BookOpenCheck size={15} aria-hidden="true" />内容策略</button>
    </div>
    {view === "watch" ? <WatchPage /> : view === "sessions" ? <SessionsPage /> : view === "strategies" ? <ContentStrategiesPage /> : <TemplatesPage published={view === "published"} />}
  </WorkbenchShell>;
}
