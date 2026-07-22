import { useState } from "react";
import { Database, Sparkles, Workflow } from "lucide-react";
import { StatusBadge, WorkbenchShell } from "../workbench/components";
import { GeminiPage } from "./GeminiPage";
import { ProductionPage } from "./ProductionPage";
import { ResourcesPage } from "./ResourcesPage";

type ViewKey = "production" | "resources" | "gemini";

function initialView(): ViewKey {
  const value = new URLSearchParams(window.location.search).get("view");
  return value === "resources" || value === "gemini" ? value : "production";
}

export default function MaituApp() {
  const [view, setView] = useState<ViewKey>(initialView);
  const changeView = (next: ViewKey) => {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "production") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    window.history.replaceState(null, "", url);
  };
  return <WorkbenchShell
    eyebrow="MAITU CONTENT OPERATIONS"
    title="麦兔内容生产工作台"
    status={<StatusBadge label="仅执行至草稿" tone="success" />}
    navItems={[
      { href: "/maitu/", label: "生产工作台", detail: "故事到麦兔草稿", icon: Workflow, active: true },
      { href: "/live-research/", label: "模板工坊", detail: "直播采集与模板", icon: Sparkles },
    ]}
  >
    <div className="wb-tabs" role="tablist" aria-label="生产工作台视图">
      <button type="button" role="tab" aria-selected={view === "production"} className={view === "production" ? "active" : undefined} onClick={() => changeView("production")}><Workflow size={15} aria-hidden="true" />生产运行</button>
      <button type="button" role="tab" aria-selected={view === "resources"} className={view === "resources" ? "active" : undefined} onClick={() => changeView("resources")}><Database size={15} aria-hidden="true" />资源与事实</button>
      <button type="button" role="tab" aria-selected={view === "gemini"} className={view === "gemini" ? "active" : undefined} onClick={() => changeView("gemini")}><Sparkles size={15} aria-hidden="true" />Gemini 回填</button>
    </div>
    {view === "production" ? <ProductionPage /> : view === "resources" ? <ResourcesPage /> : <GeminiPage />}
  </WorkbenchShell>;
}
