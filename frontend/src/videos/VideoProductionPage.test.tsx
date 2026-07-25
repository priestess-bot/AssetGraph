import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VideoProductionPage } from "./VideoProductionPage";

const plan = {
  plan_code: "VIDPLAN-001", project_code: "CONTENT-001", variant_code: "VAR-001", video_job_code: "VIDJOB-001", title: "镜头重排", timeline_revision: 1,
  production_timeline: { global_end_ms: 60_000, poster_time_ms: 2_000, tracks: [
    { track_kind: "video", clips: [
      { clip_code: "SHOT-01", source_shot_code: "CONTENT-SHOT-01", timeline_range: { start_ms: 0, duration_ms: 30_000 }, source_range: { asset_code: "ASSET-01", start_seconds: 0, end_seconds: 40, available_start_seconds: 0, available_end_seconds: 40 }, transition: "cut" },
      { clip_code: "SHOT-02", source_shot_code: "CONTENT-SHOT-02", timeline_range: { start_ms: 30_000, duration_ms: 30_000 }, source_range: { asset_code: "ASSET-02", start_seconds: 10, end_seconds: 50, available_start_seconds: 10, available_end_seconds: 50 }, transition: "cut", overlay_z_order: { brand_logo: 1000, product_sticker: -1000 }, product_sticker_layout_suggestion: { x: .2, y: .7, width_ratio: .4, source: "table_surface", table_surface_name: "hero_table", approximate: true } },
    ] },
    { track_kind: "audio", clips: [
      { clip_code: "VOICE-SHOT-01", linked_shot_code: "SHOT-01", timeline_range: { start_ms: 0, duration_ms: 30_000 }, gain_db: 0 },
      { clip_code: "VOICE-SHOT-02", linked_shot_code: "SHOT-02", timeline_range: { start_ms: 30_000, duration_ms: 30_000 }, gain_db: 0 },
    ] },
    { track_kind: "subtitle", clips: [
      { clip_code: "SUBTITLE-SHOT-01", linked_shot_code: "SHOT-01", timeline_range: { start_ms: 0, duration_ms: 30_000 }, subtitle_text: "第一段字幕", headline_text: "第一段标题" },
      { clip_code: "SUBTITLE-SHOT-02", linked_shot_code: "SHOT-02", timeline_range: { start_ms: 30_000, duration_ms: 30_000 }, subtitle_text: "第二段字幕", headline_text: "第二段标题" },
    ] },
  ] },
  render_profile: { canvas: { width: 1080, height: 1920, fps: 30 }, visual_assets: [{ asset_code: "AG-VID-000001", checksum_sha256: "a".repeat(64) }], visual_selection: { group_refs: [{ group_code: "AG-GRP-001", title: "商品讲解组", asset_codes: ["AG-VID-000001"] }], material_pack_refs: [{ pack_code: "AG-PACK-001", role: "supporting_video", revision_number: 1, fingerprint_sha256: "b".repeat(64), resolved_asset_codes: ["AG-VID-000001"] }] }, brand_logo: { asset_code: "AG-IMG-000002", checksum_sha256: "e".repeat(64) }, product_sticker: { asset_code: "AG-IMG-000001", checksum_sha256: "d".repeat(64) }, background_music: { asset_code: "AG-AUD-000001", checksum_sha256: "c".repeat(64), gain_db: -20 }, sound_effect: { asset_code: "AG-AUD-000002", checksum_sha256: "f".repeat(64), gain_db: -9 } }, job_status: "queued", current_stage: "asset_selection", progress_percent: 37, error_message: null,
  workflow_stages: [{ stage_name: "asset_selection", stage_order: 4, status: "succeeded", attempt: 1 }, { stage_name: "quality_check", stage_order: 8, status: "pending", attempt: 1 }], quality_report: { passed: true, checks: { video_stream: true, subtitle_text_complete: true }, media: { duration_seconds: 55, width: 1080, height: 1920, video_codec: "h264", audio_codec: "aac", audio_sample_rate: 48000 }, loudness: { integrated_lufs: -16.2, true_peak_db: -1.4, lra: 4.1 }, black_segments: [{ start_seconds: 2, end_seconds: 2.4, duration_seconds: .4 }], silence_segments: [], freeze_segments: [] }, artifacts: [{ artifact_key: "poster", download_url: "/files/poster.jpg", mime_type: "image/jpeg" }, { artifact_key: "contact_sheet", download_url: "/files/contact-sheet.jpg", mime_type: "image/jpeg" }], timeline_segments: [{ segment_code: "VTLSEG-VIDPLAN-001-r1-SHOT-01", clip_code: "SHOT-01", source_shot_code: "CONTENT-SHOT-01", source_script_block_codes: ["BLOCK-001"], source_asset_file_refs: [{ asset_file_id: "file-001", asset_code: "ASSET-01", file_role: "original", object_key: "assets/ASSET-01/source.mp4", checksum_sha256: "a".repeat(64) }], execution_artifact_refs: [{ job_attempt: 1, artifact_role: "source_media_probe", artifact_key: "asset_plan", relative_path: "VIDJOB-001/attempt-1/assets/plan.json", checksum_sha256: "9".repeat(64), evidence: { stream_start_pts: "3600", stream_time_base: "1/90000", source_start_seconds: 0, source_end_seconds: 6, playback_rate: 1 } }, { job_attempt: 1, artifact_role: "voice_segment", artifact_key: "voice", relative_path: "VIDJOB-001/attempt-1/voice/manifest.json", checksum_sha256: "e".repeat(64) }, { job_attempt: 1, artifact_role: "subtitle_track", artifact_key: "subtitles", relative_path: "VIDJOB-001/attempt-1/subtitles/subtitles.ass", checksum_sha256: "f".repeat(64) }, { job_attempt: 1, artifact_role: "render_manifest", artifact_key: "render_manifest", relative_path: "VIDJOB-001/attempt-1/render/manifest.json", checksum_sha256: "b".repeat(64) }, { job_attempt: 1, artifact_role: "rendered_video", artifact_key: "video", relative_path: "VIDJOB-001/attempt-1/render/final.mp4", checksum_sha256: "c".repeat(64) }, { job_attempt: 1, artifact_role: "poster", artifact_key: "poster", relative_path: "VIDJOB-001/attempt-1/render/poster.jpg", checksum_sha256: "d".repeat(64) }], timeline_start_ms: 0, timeline_end_ms: 30000, transition: "cut", fingerprint_sha256: "c".repeat(64) }, { segment_code: "VTLSEG-VIDPLAN-001-r1-SHOT-02", clip_code: "SHOT-02", source_shot_code: "CONTENT-SHOT-02", source_script_block_codes: ["BLOCK-002"], timeline_start_ms: 30000, timeline_end_ms: 60000, transition: "cut", fingerprint_sha256: "d".repeat(64) }], created_at: "2026-07-25T00:00:00Z", updated_at: "2026-07-25T00:00:00Z",
};
const musicOnlyPlan = {
  ...plan,
  render_profile: {
    ...plan.render_profile,
    visual_assets: [],
  },
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><VideoProductionPage /></QueryClientProvider>);
}

describe("VideoProductionPage", () => {
  it("shows frozen background-music evidence without a selected local video", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-live-room-plans") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/groups" || url === "/api/assets/material-packs" || url === "/api/assets") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans") return new Response(JSON.stringify([musicOnlyPlan]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001") return new Response(JSON.stringify(musicOnlyPlan), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));

    renderPage();

    expect(await screen.findByText("BGM AG-AUD-000001 · cccccccccccc · -20.0 dB")).toBeInTheDocument();
    expect(screen.getByText(/当前素材输入已经冻结/)).toBeInTheDocument();
    const trace = screen.getByRole("heading", { name: "固定镜头输入" }).closest("section");
    expect(trace).not.toBeNull();
    expect(within(trace!).getByText("BGM-01")).toBeInTheDocument();
    expect(within(trace!).getByText("AG-AUD-000001")).toBeInTheDocument();
    expect(within(trace!).getByText("SFX-01")).toBeInTheDocument();
    expect(within(trace!).getByText("AG-AUD-000002")).toBeInTheDocument();
    expect(within(trace!).getByText("PRODUCT-STICKER")).toBeInTheDocument();
    expect(within(trace!).getByText("AG-IMG-000001")).toBeInTheDocument();
    expect(within(trace!).getByText("BRAND-LOGO")).toBeInTheDocument();
    expect(within(trace!).getByText("AG-IMG-000002")).toBeInTheDocument();
  });

  it("saves the operator-selected clip order as a timeline revision", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-live-room-plans") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/groups") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/material-packs") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
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
    expect(screen.getByText("55.0 秒 · 1080x1920")).toBeInTheDocument();
    expect(screen.getByText("-16.2 LUFS · 峰值 -1.4 dB")).toBeInTheDocument();
    expect(screen.getByText("黑帧")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "成片海报" })).toHaveAttribute("src", "/files/poster.jpg");
    expect(screen.getAllByText("AG-VID-000001 · aaaaaaaaaaaa").length).toBeGreaterThan(0);
    expect(screen.getByText("分组 商品讲解组 · AG-GRP-001 · 1 项")).toBeInTheDocument();
    expect(screen.getByText("素材包 AG-PACK-001 · r1 · bbbbbbbbbbbb")).toBeInTheDocument();
    expect(screen.getByText("BGM AG-AUD-000001 · cccccccccccc · -20.0 dB")).toBeInTheDocument();
    expect(screen.getByText("商品贴片 AG-IMG-000001 · dddddddddddd")).toBeInTheDocument();
    expect(screen.getByText("品牌标识 AG-IMG-000002 · eeeeeeeeeeee")).toBeInTheDocument();
    const trace = screen.getByRole("heading", { name: "固定镜头输入" }).closest("section");
    expect(trace).not.toBeNull();
    expect(within(trace!).getByText("SHOT-01")).toBeInTheDocument();
    expect(within(trace!).getByText("第一段字幕")).toBeInTheDocument();
    expect(within(trace!).getByText("ASSET-01")).toBeInTheDocument();
    expect(within(trace!).getByText("CONTENT-SHOT-01")).toBeInTheDocument();
    expect(within(trace!).getByText("BLOCK-001")).toBeInTheDocument();
    expect(within(trace!).getByText("voice_segment r1 eeeeeeeeeeee")).toBeInTheDocument();
    expect(within(trace!).getByText("source_media_probe r1 999999999999")).toBeInTheDocument();
    expect(within(trace!).getByText("PTS 3600 / 1/90000 · 0.00-6.00 秒 · 1.00x")).toBeInTheDocument();
    expect(within(trace!).getByText("render_manifest r1 bbbbbbbbbbbb")).toBeInTheDocument();
    expect(within(trace!).getByText("ASSET-01 original aaaaaaaaaaaa")).toBeInTheDocument();
    expect(within(trace!).getByText("VTLSEG-VIDPLAN-001-r1-SHOT-01")).toBeInTheDocument();
    expect(await screen.findByText("修订历史")).toBeInTheDocument();
    expect(screen.getByAltText("成片镜头联系表")).toHaveAttribute("src", "/files/contact-sheet.jpg");
    await user.click(screen.getByRole("button", { name: "上移 SHOT-02" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "画面素材 SHOT-02" }), "AG-VID-000001");
    await user.clear(screen.getByRole("spinbutton", { name: "素材入点 SHOT-02" }));
    await user.type(screen.getByRole("spinbutton", { name: "素材入点 SHOT-02" }), "1");
    await user.selectOptions(screen.getByRole("combobox", { name: "画面适配 SHOT-02" }), "cover");
    fireEvent.change(screen.getByRole("slider", { name: "裁切焦点 X SHOT-02" }), { target: { value: "25" } });
    fireEvent.change(screen.getByRole("slider", { name: "裁切焦点 Y SHOT-02" }), { target: { value: "75" } });
    await user.selectOptions(screen.getByRole("combobox", { name: "播放速度 SHOT-02" }), "1.5");
    await user.click(screen.getByRole("checkbox", { name: "品牌标识 SHOT-02" }));
    await user.click(screen.getByRole("checkbox", { name: "商品贴片 SHOT-02" }));
    expect(screen.getByText("桌面区域建议：hero_table（近似）")).toBeInTheDocument();
    expect(screen.getByText("商品图层：底部")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: "商品位置 X SHOT-02" }), { target: { value: "20" } });
    fireEvent.change(screen.getByRole("slider", { name: "商品位置 Y SHOT-02" }), { target: { value: "70" } });
    fireEvent.change(screen.getByRole("slider", { name: "商品宽度 SHOT-02" }), { target: { value: "40" } });
    await user.clear(screen.getByRole("spinbutton", { name: "海报帧（秒）" }));
    await user.type(screen.getByRole("spinbutton", { name: "海报帧（秒）" }), "7.5");
    await user.clear(screen.getByRole("textbox", { name: "字幕文本 SHOT-02" }));
    await user.type(screen.getByRole("textbox", { name: "字幕文本 SHOT-02" }), "更新后的第二段字幕");
    await user.selectOptions(screen.getByRole("combobox", { name: "字幕位置 SHOT-02" }), "center");
    await user.selectOptions(screen.getByRole("combobox", { name: "字幕样式" }), "large");
    await user.clear(screen.getByRole("spinbutton", { name: "字幕底部安全边距（像素）" }));
    await user.type(screen.getByRole("spinbutton", { name: "字幕底部安全边距（像素）" }), "240");
    fireEvent.change(screen.getByRole("slider", { name: "配音增益 SHOT-02" }), { target: { value: "1" } });
    await user.click(screen.getByRole("button", { name: "保存时间轴修订" }));

    const request = requests.find((item) => item.url.endsWith("/timeline") && item.init?.method === "PUT");
    expect(request?.init?.body).toBe(JSON.stringify({ expected_revision: 1, poster_time_ms: 7_500, subtitle_style: { preset: "large", safe_bottom_px: 240 }, video_clips: [
      { clip_code: "SHOT-02", duration_ms: 30_000, transition: "cut", source_asset_code: "AG-VID-000001", source_start_seconds: 1, source_end_seconds: 6, fit: "cover", crop_x: 0.25, crop_y: 0.75, playback_rate: 1.5, show_brand_logo: true, show_product_sticker: true, product_sticker_x: 0.2, product_sticker_y: 0.7, product_sticker_width_ratio: 0.4 },
      { clip_code: "SHOT-01", duration_ms: 30_000, transition: "cut", source_start_seconds: 0, source_end_seconds: 40 },
    ], subtitle_clips: [
      { clip_code: "SUBTITLE-SHOT-01", subtitle_text: "第一段字幕", headline_text: "第一段标题", caption_position: "bottom" },
      { clip_code: "SUBTITLE-SHOT-02", subtitle_text: "更新后的第二段字幕", headline_text: "第二段标题", caption_position: "center" },
    ], audio_clips: [
      { clip_code: "VOICE-SHOT-01", gain_db: 0 },
      { clip_code: "VOICE-SHOT-02", gain_db: 1 },
    ] }));
  });

  it("restores a historical timeline as a new revision", async () => {
    const current = { ...plan, timeline_revision: 2 };
    const previousTimeline = structuredClone(plan.production_timeline);
    const previousVideoClips = previousTimeline.tracks[0].clips as Array<{
      clip_code: string;
      source_shot_code: string;
      timeline_range: { start_ms: number; duration_ms: number };
      source_range: {
        asset_code: string;
        start_seconds: number;
        end_seconds: number;
        available_start_seconds: number;
        available_end_seconds: number;
      };
      transition: string;
    }>;
    previousVideoClips.reverse();
    previousVideoClips[1] = {
      ...previousVideoClips[1],
      transition: "fade",
      source_range: {
        ...previousVideoClips[1].source_range,
        start_seconds: 2,
        end_seconds: 42,
      },
    };
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-live-room-plans") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/groups") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/material-packs") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans") return new Response(JSON.stringify([current]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001") return new Response(JSON.stringify(current), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions") return new Response(JSON.stringify([{ revision_number: 2, production_timeline: current.production_timeline, actor_id: "operator", created_at: "2026-07-25T01:00:00Z" }, { revision_number: 1, production_timeline: previousTimeline, actor_id: "operator", created_at: "2026-07-25T00:00:00Z" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions/1/restore" && init?.method === "POST") return new Response(JSON.stringify({ ...current, timeline_revision: 3 }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "镜头重排" });
    const history = await screen.findByText("修订历史");
    expect(history.parentElement?.parentElement).toHaveTextContent(
      "SHOT-01 转场 fade -> cut",
    );
    expect(history.parentElement?.parentElement).toHaveTextContent(
      "镜头顺序 SHOT-02 / SHOT-01 -> SHOT-01 / SHOT-02",
    );
    await user.click(await screen.findByRole("button", { name: "恢复 r1" }));

    const request = requests.find((item) => item.url.endsWith("/timeline-revisions/1/restore") && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({ expected_revision: 2 }));
  });

  it("creates an editable branch after a render job has started", async () => {
    const running = { ...plan, job_status: "running", current_stage: "rendering" };
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-live-room-plans") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/groups") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/material-packs") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans") return new Response(JSON.stringify([running]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001") return new Response(JSON.stringify(running), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-002") return new Response(JSON.stringify({ ...plan, plan_code: "VIDPLAN-002", title: "剪辑修订" }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions") return new Response(JSON.stringify([{ revision_number: 1, production_timeline: plan.production_timeline, actor_id: "operator", created_at: "2026-07-25T00:00:00Z" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/branch" && init?.method === "POST") return new Response(JSON.stringify({ ...plan, plan_code: "VIDPLAN-002", title: "剪辑修订" }), { status: 201, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "镜头重排" });
    await user.type(screen.getByRole("textbox", { name: "分支名称" }), "剪辑修订");
    await user.click(screen.getByRole("button", { name: "创建可编辑分支" }));

    const request = requests.find((item) => item.url.endsWith("/branch") && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({ title: "剪辑修订" }));
    expect(await screen.findByRole("heading", { name: "剪辑修订" })).toBeInTheDocument();
  });

  it("creates a rendered-video plan from a fixed live-room plan", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-live-room-plans") return new Response(JSON.stringify([{ plan_code: "LIVEPLAN-001", expected_title: "夏日直播间" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/groups") return new Response(JSON.stringify([{ group_code: "AG-GRP-001", title: "商品讲解组", asset_codes: ["AG-VID-000001"], asset_count: 1 }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/material-packs") return new Response(JSON.stringify([{ pack_code: "AG-PACK-001", title: "讲解素材包", role: "supporting_video", revision_number: 1, status: "published", fingerprint_sha256: "b".repeat(64), entries: [], resolved_asset_codes: ["AG-VID-000001"] }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets") return new Response(JSON.stringify([{ asset_code: "AG-VID-000001", title: "本地商品讲解", asset_type: "VID", media_kind: "video", execution_capability: "local_only" }, { asset_code: "AG-IMG-000002", title: "本地品牌标识", asset_type: "IMG", media_kind: "image", material_roles: ["brand_title"], execution_capability: "local_only" }, { asset_code: "AG-IMG-000001", title: "本地商品贴片", asset_type: "IMG", media_kind: "image", material_roles: ["product_display"], execution_capability: "local_only" }, { asset_code: "AG-AUD-000001", title: "本地背景音乐", asset_type: "AUD", media_kind: "audio", material_roles: ["background_music"], execution_capability: "local_only" }, { asset_code: "AG-AUD-000002", title: "本地开场音效", asset_type: "AUD", media_kind: "audio", material_roles: ["sound_effect"], execution_capability: "local_only" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans") {
        if (init?.method === "POST") return new Response(JSON.stringify(plan), { status: 201, headers: { "Content-Type": "application/json" } });
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/functional-video-plans/VIDPLAN-001") return new Response(JSON.stringify(plan), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "内容来源" }), "live_room");
    await user.selectOptions(screen.getByRole("combobox", { name: "直播间计划" }), "LIVEPLAN-001");
    expect(screen.getByLabelText("预览 本地商品讲解")).toHaveAttribute("src", "/api/assets/AG-VID-000001/preview");
    await user.click(screen.getByRole("checkbox", { name: "选择 本地商品讲解" }));
    await user.click(screen.getByRole("checkbox", { name: "选择分组 商品讲解组" }));
    await user.click(screen.getByRole("checkbox", { name: "选择素材包 讲解素材包" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "品牌标识" }), "AG-IMG-000002");
    await user.selectOptions(screen.getByRole("combobox", { name: "商品贴片" }), "AG-IMG-000001");
    await user.selectOptions(screen.getByRole("combobox", { name: "背景音乐" }), "AG-AUD-000001");
    await user.selectOptions(screen.getByRole("combobox", { name: "音效" }), "AG-AUD-000002");
    expect(screen.getByAltText("预览 本地品牌标识")).toHaveAttribute("src", "/api/assets/AG-IMG-000002/preview");
    expect(screen.getByAltText("预览 本地商品贴片")).toHaveAttribute("src", "/api/assets/AG-IMG-000001/preview");
    expect(screen.getByLabelText("预览 本地背景音乐")).toHaveAttribute("src", "/api/assets/AG-AUD-000001/preview");
    expect(screen.getByLabelText("预览 本地开场音效")).toHaveAttribute("src", "/api/assets/AG-AUD-000002/preview");
    fireEvent.change(screen.getByRole("slider", { name: "背景音乐增益" }), { target: { value: "-20" } });
    fireEvent.change(screen.getByRole("slider", { name: "音效增益" }), { target: { value: "-9" } });
    await user.click(screen.getByRole("button", { name: "创建渲染任务" }));

    const request = requests.find((item) => item.url === "/api/functional-video-plans" && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({ live_room_plan_code: "LIVEPLAN-001", target_duration_seconds: 55, visual_asset_codes: ["AG-VID-000001"], visual_group_codes: ["AG-GRP-001"], visual_material_pack_codes: ["AG-PACK-001"], brand_logo_asset_code: "AG-IMG-000002", product_sticker_asset_code: "AG-IMG-000001", background_music_asset_code: "AG-AUD-000001", background_music_gain_db: -20, sound_effect_asset_code: "AG-AUD-000002", sound_effect_gain_db: -9 }));
  });

  it("creates a release candidate only from a QC-passed completed video", async () => {
    const completed = { ...plan, job_status: "succeeded", current_stage: "quality_check" };
    const released = {
      ...completed,
      release_code: "RELEASE-001",
      release_snapshot_artifact_code: "ART-001",
      release_manifest_fingerprint: "a".repeat(64),
      release: { release_code: "RELEASE-001", status: "candidate", manifest_code: "RELEASE-001-M001", manifest_fingerprint: "a".repeat(64), snapshot_artifact_code: "ART-001" },
    };
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url === "/api/content-projects") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-live-room-plans") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/groups") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets/material-packs") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/assets") return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans") return new Response(JSON.stringify([completed]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001") return new Response(JSON.stringify(completed), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/timeline-revisions") return new Response(JSON.stringify([{ revision_number: 1, production_timeline: plan.production_timeline, actor_id: "operator", created_at: "2026-07-25T00:00:00Z" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/functional-video-plans/VIDPLAN-001/release-candidate" && init?.method === "POST") return new Response(JSON.stringify(released), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "镜头重排" });
    await user.click(screen.getByRole("button", { name: "创建发布候选" }));

    const request = requests.find((item) => item.url.endsWith("/release-candidate") && item.init?.method === "POST");
    expect(request?.init?.body).toBe(JSON.stringify({}));
    expect(await screen.findByText("RELEASE-001")).toBeInTheDocument();
  });
});
