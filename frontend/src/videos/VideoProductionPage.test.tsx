import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VideoProductionPage } from "./VideoProductionPage";

const plan = {
  plan_code: "VIDPLAN-001", project_code: "CONTENT-001", variant_code: "VAR-001", video_job_code: "VIDJOB-001", title: "镜头重排", timeline_revision: 1,
  production_timeline: { global_end_ms: 60_000, tracks: [
    { track_kind: "video", clips: [
      { clip_code: "SHOT-01", timeline_range: { start_ms: 0, duration_ms: 30_000 }, source_range: { asset_code: "ASSET-01" }, transition: "cut" },
      { clip_code: "SHOT-02", timeline_range: { start_ms: 30_000, duration_ms: 30_000 }, source_range: { asset_code: "ASSET-02" }, transition: "cut" },
    ] },
    { track_kind: "audio", clips: [] },
  ] },
  render_profile: { canvas: { width: 1080, height: 1920, fps: 30 } }, job_status: "queued", current_stage: "asset_selection", progress_percent: 37, error_message: null,
  workflow_stages: [{ stage_name: "asset_selection", stage_order: 4, status: "succeeded", attempt: 1 }, { stage_name: "quality_check", stage_order: 8, status: "pending", attempt: 1 }], quality_report: { passed: true, checks: { video_stream: true, subtitle_text_complete: true } }, artifacts: [], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><VideoProductionPage /></QueryClientProvider>);
}

describe("VideoProductionPage", () => {
  it("saves the operator-selected clip order as a timeline revision", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans") return new Response(JSON.stringify([plan]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001") return new Response(JSON.stringify(plan), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions") return new Response(JSON.stringify([{ revision_number: 1, production_timeline: plan.production_timeline, actor_id: "operator", created_at: "2026-07-25T00:00:00Z" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline" && init?.method === "PUT") return new Response(JSON.stringify({ ...plan, timeline_revision: 2 }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "镜头重排" });
    expect(screen.getByRole("heading", { name: "生产阶段" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "质量检查" })).toBeInTheDocument();
    expect(screen.getByText("subtitle_text_complete")).toBeInTheDocument();
    expect(await screen.findByText("修订历史")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "上移 SHOT-02" }));
    await user.click(screen.getByRole("button", { name: "保存时间轴修订" }));

    const request = requests.find((item) => item.url.endsWith("/timeline") && item.init?.method === "PUT");
    expect(request?.init?.body).toBe(JSON.stringify({ expected_revision: 1, video_clips: [
      { clip_code: "SHOT-02", duration_ms: 30_000, transition: "cut" },
      { clip_code: "SHOT-01", duration_ms: 30_000, transition: "cut" },
    ] }));
  });
});
