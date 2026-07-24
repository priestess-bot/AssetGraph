import { beforeEach, describe, expect, it, vi } from "vitest";
import { liveResearchApi, normalizeCaptureSession, normalizeOverview, normalizeTemplate, normalizeTimeline, normalizeWatchTarget } from "./api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("live research api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("normalizes watch, chunk retention and timeline spans without exposing raw events", () => {
    const target = normalizeWatchTarget({ target_code: "DY-WATCH-001", platform: "douyin", room_url: "https://live.douyin.com/1", canonical_room_id: "1", display_name: "参考间", status: "enabled", next_check_at: "2026-07-20T10:00:00Z", consecutive_failures: 0 });
    expect(target).toMatchObject({ room_id: "1", recorder_health: "unknown", interaction_health: "unknown" });

    const session = normalizeCaptureSession({ session_code: "DY-CAP-001", target_code: "DY-WATCH-001", status: "completed", observed_started_at: "2026-07-20T08:00:00Z", timeline_duration_seconds: 90, playback_url: "/api/live-research/media", event_count: 120, raw_event_batches: [{ relative_path: "private/events.gz" }], chunks: [{ retention_expires_at: "2026-08-19T08:00:00Z" }] });
    expect(session).toMatchObject({ duration_seconds: 90, playback_url: "/api/live-research/media", interaction_event_count: 120, expires_at: "2026-08-19T08:00:00Z" });
    expect(session).not.toHaveProperty("raw_event_batches");

    const timeline = normalizeTimeline([{ span_index: 0, global_start_seconds: 0, global_end_seconds: 90, confidence: .99 }]);
    expect(timeline.duration_seconds).toBe(90);
    expect(timeline.visual_segments[0]?.label).toBe("录屏分片 1");
  });

  it("uses authoritative overview queue, draft and retention counts", () => {
    expect(normalizeOverview({
      watch_targets_enabled: 3,
      active_capture_sessions: 1,
      queued_analysis_runs: 7,
      running_analysis_runs: 2,
      draft_templates: 4,
      published_templates: 20,
      expiring_capture_chunks: 5,
    })).toEqual({
      enabled_target_count: 3,
      live_target_count: 1,
      recording_session_count: 1,
      analysis_queue_count: 9,
      draft_template_count: 4,
      expiring_recording_count: 5,
    });
  });

  it("joins inferred components back to template scenes", () => {
    const template = normalizeTemplate({
      template_code: "DY-TPL-001", name: "三段式模板", status: "draft", published_revision_number: null,
      revisions: [{ revision_number: 2, status: "draft", source_session_code: "DY-CAP-001", scenes: [{ scene_key: "hook", name: "问题钩子", start_seconds: 0, end_seconds: 30, purpose: "建立代入" }], components: [{ component_id: "host", scene_key: "hook", role: "host", geometry: { x: .1, y: .2, width: .8, height: .7 }, confidence: .82, evidence: [{ label: "主播" }] }] }],
    });
    expect(template.title).toBe("三段式模板");
    expect(template.source_session_code).toBe("DY-CAP-001");
    expect(template.scenes[0]?.components[0]).toMatchObject({ role: "host", label: "主播", x: .1 });
  });

  it("keeps the latest draft revision distinct from the published revision in summaries", () => {
    const template = normalizeTemplate({
      template_code: "DY-TPL-001",
      name: "双版本模板",
      status: "draft",
      latest_revision_number: 2,
      published_revision_number: 1,
    });

    expect(template).toMatchObject({ latest_revision: 2, published_revision: 1, status: "draft" });
  });

  it("creates exact-reencode clips with backend field names", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ clip_job_code: "CLIP-JOB-001", session_code: "DY-CAP-001", requested_start_seconds: 12.5, requested_end_seconds: 44, status: "queued" }, 202));
    vi.stubGlobal("fetch", fetchMock);
    await liveResearchApi.createClip("DY-CAP-001", { title: "产品讲解", in_seconds: 12.5, out_seconds: 44 });
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({ title: "产品讲解", requested_start_seconds: 12.5, requested_end_seconds: 44, cut_mode: "exact_reencode" });
  });

  it("publishes an inferred revision with reference-safe component claims", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ template_code: "DY-TPL-001", template_name: "模板", revision_number: 2, projection_fingerprint: "abc", projection_ready: true, manual_review_required: true, blocking_reasons: [], canvas: {}, scenes: [], components: [], audio_policy: {}, provenance: {} }, 201));
    vi.stubGlobal("fetch", fetchMock);
    await liveResearchApi.createTemplateRevision("DY-TPL-001", { expected_revision: 1, reviewer_note: "已复核", source_session_code: "DY-CAP-001", scenes: [{ scene_code: "hook", title: "钩子", start_seconds: 0, end_seconds: 20, purpose: "吸引注意", material_slots: [], components: [{ role: "host", label: "主播", x: .1, y: .1, width: .8, height: .8, confidence: .8 }] }] });
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body.canvas.pixel_aspect_ratio).toBe("1:1");
    expect(body.components[0]).toMatchObject({ observability: "inferred", source_binding_status: "unmatched", muted: true });
    expect(body.components[0].evidence).toEqual([{ label: "主播", source: "flat_video_visual_inference" }]);
  });

  it("projects real provider outputs from each chunk onto the global timeline", async () => {
    const spans = [
      { span_index: 0, chunk_code: "CHUNK-1", global_start_seconds: 0, global_end_seconds: 600, chunk_start_seconds: 0, chunk_end_seconds: 600, mapping_slope: 1 },
      { span_index: 1, chunk_code: "CHUNK-2", global_start_seconds: 600, global_end_seconds: 1200, chunk_start_seconds: 0, chunk_end_seconds: 600, mapping_slope: 1 },
    ];
    const analyses = [
      { analysis_type: "asr", chunk_code: "CHUNK-2", output_payload: { transcript: { segments: [{ start: 2, end: 4, text: "第二分片口播" }] } } },
      { analysis_type: "frame_sampling", chunk_code: "CHUNK-2", output_payload: { frames: [{ frame_index: 1, timeline_seconds: 5, relative_path: "private/frame.jpg" }] } },
      { analysis_type: "layout_inference", chunk_code: "CHUNK-2", parameters: { sample_times_seconds: [0, 5, 15] }, output_payload: { summary: "主播位于画面中部", observations: [{ kind: "host", label: "主播", bbox: { x: .1, y: .1, width: .8, height: .8 }, confidence: .9, text: null }] } },
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/timeline")) return Promise.resolve(response(spans));
      if (url.includes("/analysis-runs")) return Promise.resolve(response(analyses));
      if (url.includes("interaction-summary")) return Promise.resolve(response({ buckets: [] }));
      return Promise.resolve(response({ session_code: "DY-CAP-001", observed_started_at: "2026-07-20T00:00:00Z" }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const timeline = await liveResearchApi.getTimeline("DY-CAP-001");

    expect(timeline.asr_segments[0]).toMatchObject({ start_seconds: 602, end_seconds: 604, text: "第二分片口播" });
    expect(timeline.keyframes[0]?.at_seconds).toBe(605);
    expect(timeline.visual_segments).toEqual(expect.arrayContaining([
      expect.objectContaining({ start_seconds: 600, end_seconds: 615, label: "主播位于画面中部" }),
    ]));
  });

  it("unwraps the strategy template payload before materializing a draft", async () => {
    const aggregation = [{
      analysis_type: "template_aggregation",
      status: "succeeded",
      output_payload: {
        template_name: "直播结构",
        template: {
          scenes: [{ scene_key: "hook", name: "开场", start_seconds: 0, end_seconds: 20, purpose: "建立注意" }],
          components: [{ component_id: "host", scene_key: "hook", role: "host", geometry: { x: .1, y: .1, width: .8, height: .8 }, confidence: .9 }],
        },
      },
    }];
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(aggregation))
      .mockResolvedValueOnce(response({ template_code: "DY-TPL-001", name: "直播结构", status: "draft", revisions: [] }, 201))
      .mockResolvedValueOnce(response({ revision_number: 1, status: "draft" }, 201))
      .mockResolvedValueOnce(response({ template_code: "DY-TPL-001", name: "直播结构", status: "draft", revisions: [{ revision_number: 1, status: "draft", scenes: [{ scene_key: "hook", name: "开场", start_seconds: 0, end_seconds: 20, purpose: "建立注意" }], components: [{ component_id: "host", scene_key: "hook", role: "host", geometry: { x: .1, y: .1, width: .8, height: .8 } }] }] }));
    vi.stubGlobal("fetch", fetchMock);

    const template = await liveResearchApi.materializeAnalysisTemplate({
      analysis_run_code: "LR-ANL-001",
      session_code: "DY-CAP-001",
      status: "succeeded",
      progress_percent: 100,
      asr_status: "succeeded",
      visual_status: "succeeded",
      structure_status: "succeeded",
    });

    expect(template.scenes[0]?.components[0]).toMatchObject({ role: "host" });
  });
});
