import {
  BookOpen,
  BrainCircuit,
  ChartNoAxesCombined,
  FolderKanban,
  Images,
  LayoutDashboard,
  MessageSquareText,
  PanelsTopLeft,
} from "lucide-react";
import type { ComponentType } from "react";

export interface ProductRoute {
  path: string;
  label: string;
  description: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean | "true" }>;
}

export const PRODUCT_ROUTES: ProductRoute[] = [
  { path: "/", label: "业务概览", description: "产出、交付与表现", icon: LayoutDashboard },
  { path: "/assets", label: "素材库", description: "素材、分组与约束", icon: Images },
  { path: "/templates", label: "直播模板", description: "录屏解析与模板", icon: PanelsTopLeft },
  { path: "/knowledge", label: "知识库", description: "事实、来源与引用", icon: BookOpen },
  { path: "/projects", label: "内容项目", description: "从目标到交付", icon: FolderKanban },
  { path: "/operations", label: "运营分析", description: "场次、归因与指标", icon: ChartNoAxesCombined },
  { path: "/interactions", label: "用户互动", description: "采集、意图与应答", icon: MessageSquareText },
  { path: "/learning", label: "效果学习", description: "证据与再生产", icon: BrainCircuit },
];

export function routeIsActive(pathname: string, route: ProductRoute): boolean {
  if (route.path === "/") return pathname === "/" || pathname === "/console" || pathname === "/console/";
  return pathname === route.path || pathname.startsWith(`${route.path}/`);
}

export function productPageTitle(pathname: string): string {
  return PRODUCT_ROUTES.find((route) => routeIsActive(pathname, route))?.label ?? "内容项目";
}

export const LEGACY_ROUTE_MAP: Array<[prefix: string, target: string]> = [
  ["/assets/library", "/assets"],
  ["/research/live-sources", "/templates"],
  ["/content/projects", "/projects"],
  ["/operations/live-sessions", "/operations"],
  ["/operations/attribution", "/operations"],
  ["/learning/effects", "/learning"],
];
