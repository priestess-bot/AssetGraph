import { type FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  CircleX,
  Download,
  FileCheck2,
  Film,
  GitFork,
  RefreshCw,
  RotateCcw,
  Send,
} from "lucide-react";
import { contentProjectsApi } from "../content/api";
import { assetLibraryApi, type LibraryAsset } from "../assets/api";
import { functionalLiveRoomsApi } from "../live-rooms/api";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../workbench/components";
import {
  functionalVideosApi,
  type FunctionalVideoPlan,
  type VideoTimelineRevision,
} from "./api";

function text(error: unknown): string {
  return error instanceof Error ? error.message : "操作未完成";
}
function bytes(value?: number): string {
  return typeof value === "number"
    ? value < 1024 * 1024
      ? `${Math.round(value / 1024)} KB`
      : `${(value / (1024 * 1024)).toFixed(1)} MB`
    : "--";
}
function jobTone(
  status: string,
): "success" | "warning" | "danger" | "info" | "neutral" {
  return status === "succeeded"
    ? "success"
    : status === "failed"
      ? "danger"
      : status === "running"
        ? "info"
        : "warning";
}
function jobLabel(status: string): string {
  return (
    (
      {
        queued: "等待渲染 Worker",
        running: "正在渲染",
        succeeded: "渲染完成",
        failed: "渲染失败",
      } as Record<string, string>
    )[status] ?? status
  );
}
function stageLabel(stage: string): string {
  return (
    (
      {
        brief_generation: "内容摘要",
        script_generation: "脚本",
        shot_planning: "镜头规划",
        asset_selection: "素材选择",
        voice_synthesis: "配音",
        subtitle_generation: "字幕",
        rendering: "渲染",
        quality_check: "质量检查",
      } as Record<string, string>
    )[stage] ?? stage
  );
}
function stageTone(
  status: string,
): "success" | "warning" | "danger" | "info" | "neutral" {
  return status === "succeeded"
    ? "success"
    : status === "failed"
      ? "danger"
      : status === "running"
        ? "info"
        : "neutral";
}
function decimal(value: number | undefined, suffix = ""): string {
  return typeof value === "number" ? `${value.toFixed(1)}${suffix}` : "--";
}
function timelineClips(timeline: FunctionalVideoPlan["productionTimeline"]) {
  return (
    timeline.tracks.find((track) => track.track_kind === "video")?.clips ?? []
  );
}

function clipRangeLabel(
  clip: FunctionalVideoPlan["productionTimeline"]["tracks"][number]["clips"][number],
): string {
  const source = clip.source_range;
  if (!source) return "基线视觉源";
  const range =
    typeof source.start_seconds === "number" &&
    typeof source.end_seconds === "number"
      ? ` ${source.start_seconds.toFixed(2)}-${source.end_seconds.toFixed(2)} 秒`
      : "";
  return `${source.asset_code}${range}`;
}

function linkedClips(
  timeline: FunctionalVideoPlan["productionTimeline"],
  trackKind: string,
) {
  return new Map(
    (timeline.tracks.find((track) => track.track_kind === trackKind)?.clips ?? [])
      .filter((clip) => clip.linked_shot_code)
      .map((clip) => [clip.linked_shot_code!, clip]),
  );
}

function timelineDiff(
  current: FunctionalVideoPlan["productionTimeline"],
  previous?: VideoTimelineRevision["productionTimeline"],
): string[] {
  if (!previous) return ["首个时间轴修订"];
  const currentCodes = timelineClips(current).map((clip) => clip.clip_code);
  const previousCodes = timelineClips(previous).map((clip) => clip.clip_code);
  const changes: string[] = [
    currentCodes.join(" / ") === previousCodes.join(" / ")
      ? "镜头顺序未变"
      : `镜头顺序 ${previousCodes.join(" / ")} -> ${currentCodes.join(" / ")}`,
  ];
  const durationDelta = current.global_end_ms - previous.global_end_ms;
  if (durationDelta)
    changes.push(
      `总时长 ${durationDelta > 0 ? "+" : ""}${(durationDelta / 1000).toFixed(1)} 秒`,
    );
  const previousByCode = new Map(
    timelineClips(previous).map((clip) => [clip.clip_code, clip]),
  );
  for (const clip of timelineClips(current)) {
    const before = previousByCode.get(clip.clip_code);
    if (!before) {
      changes.push(`${clip.clip_code} 已加入`);
      continue;
    }
    if (clip.timeline_range.duration_ms !== before.timeline_range.duration_ms)
      changes.push(
        `${clip.clip_code} 时长 ${timelineSeconds(before.timeline_range.duration_ms)} -> ${timelineSeconds(clip.timeline_range.duration_ms)}`,
      );
    if ((clip.transition ?? "cut") !== (before.transition ?? "cut"))
      changes.push(
        `${clip.clip_code} 转场 ${before.transition ?? "cut"} -> ${clip.transition ?? "cut"}`,
      );
    if (clipRangeLabel(clip) !== clipRangeLabel(before))
      changes.push(
        `${clip.clip_code} 画面源 ${clipRangeLabel(before)} -> ${clipRangeLabel(clip)}`,
      );
    if ((clip.fit ?? "cover") !== (before.fit ?? "cover"))
      changes.push(
        `${clip.clip_code} 适配 ${before.fit ?? "cover"} -> ${clip.fit ?? "cover"}`,
      );
    if ((clip.playback_rate ?? 1) !== (before.playback_rate ?? 1))
      changes.push(
        `${clip.clip_code} 倍速 ${before.playback_rate ?? 1}x -> ${clip.playback_rate ?? 1}x`,
      );
    if (
      (clip.crop_x ?? null) !== (before.crop_x ?? null) ||
      (clip.crop_y ?? null) !== (before.crop_y ?? null)
    )
      changes.push(`${clip.clip_code} 裁切焦点已更新`);
    if (
      (clip.overlay_roles ?? []).join(",") !==
      (before.overlay_roles ?? []).join(",")
    )
      changes.push(`${clip.clip_code} 叠层角色已更新`);
  }
  const previousSubtitles = linkedClips(previous, "subtitle");
  const currentSubtitles = linkedClips(current, "subtitle");
  for (const [shotCode, subtitle] of currentSubtitles) {
    const before = previousSubtitles.get(shotCode);
    if (before && subtitle.subtitle_text !== before.subtitle_text)
      changes.push(`${shotCode} 字幕已更新`);
    if (before && subtitle.headline_text !== before.headline_text)
      changes.push(`${shotCode} 标题已更新`);
  }
  const previousVoices = linkedClips(previous, "audio");
  const currentVoices = linkedClips(current, "audio");
  for (const [shotCode, voice] of currentVoices) {
    const before = previousVoices.get(shotCode);
    if (before && (voice.gain_db ?? 0) !== (before.gain_db ?? 0))
      changes.push(
        `${shotCode} 配音 ${decimal(before.gain_db, " dB")} -> ${decimal(voice.gain_db, " dB")}`,
      );
  }
  if (
    current.poster_time_ms !== previous.poster_time_ms &&
    typeof current.poster_time_ms === "number"
  )
    changes.push(`海报帧 ${timelineSeconds(current.poster_time_ms)}`);
  if (
    current.subtitle_style?.preset !== previous.subtitle_style?.preset ||
    current.subtitle_style?.safe_bottom_px !== previous.subtitle_style?.safe_bottom_px
  )
    changes.push("字幕样式已更新");
  if (changes.length === 1 && changes[0] === "镜头顺序未变" && !durationDelta)
    return ["时间轴字段未变"];
  if (changes.length > 8)
    return [...changes.slice(0, 8), `另有 ${changes.length - 8} 项变更`];
  return changes;
}

function timelineSeconds(value: number): string {
  return `${(value / 1000).toFixed(1)} 秒`;
}

function assetPreviewUrl(assetCode: string): string {
  return `/api/assets/${encodeURIComponent(assetCode)}/preview`;
}

function LocalMaterialPreview({ asset }: { asset: LibraryAsset }) {
  const source = assetPreviewUrl(asset.assetCode);
  return (
    <figure className={`video-material-preview is-${asset.mediaKind ?? "unknown"}`}>
      {asset.mediaKind === "image" ? (
        <img src={source} alt={`预览 ${asset.title}`} />
      ) : asset.mediaKind === "audio" ? (
        <audio aria-label={`预览 ${asset.title}`} controls preload="metadata" src={source} />
      ) : (
        <video
          aria-label={`预览 ${asset.title}`}
          controls
          muted
          playsInline
          preload="metadata"
          src={source}
        />
      )}
      <figcaption>
        <strong>{asset.title}</strong>
        <code>{asset.assetCode}</code>
      </figcaption>
    </figure>
  );
}

function FixedInputTrace({ plan }: { plan: FunctionalVideoPlan }) {
  const videoClips = timelineClips(plan.productionTimeline);
  const subtitleTrack = plan.productionTimeline.tracks.find(
    (track) => track.track_kind === "subtitle",
  );
  const audioTrack = plan.productionTimeline.tracks.find(
    (track) => track.track_kind === "audio",
  );
  const subtitlesByShot = new Map(
    (subtitleTrack?.clips ?? [])
      .filter((clip) => clip.linked_shot_code)
      .map((clip) => [clip.linked_shot_code!, clip]),
  );
  const voicesByShot = new Map(
    (audioTrack?.clips ?? [])
      .filter((clip) => clip.linked_shot_code)
      .map((clip) => [clip.linked_shot_code!, clip]),
  );
  const backgroundMusic = plan.renderProfile.backgroundMusic;
  const soundEffect = plan.renderProfile.soundEffect;
  const brandLogo = plan.renderProfile.brandLogo;
  const productSticker = plan.renderProfile.productSticker;
  const timelineSegmentsByClip = new Map(
    plan.timelineSegments.map((segment) => [segment.clipCode, segment]),
  );

  if (!videoClips.length && !backgroundMusic && !soundEffect && !brandLogo && !productSticker)
    return null;

  return (
    <section className="wb-section">
      <SectionHeader
        kicker={`INPUT r${plan.timelineRevision}`}
        title="固定镜头输入"
        actions={
          <StatusBadge label={`${videoClips.length} 个镜头`} tone="info" />
        }
      />
      <div className="video-input-trace">
        {videoClips.map((clip) => {
          const subtitle = subtitlesByShot.get(clip.clip_code);
          const voice = voicesByShot.get(clip.clip_code);
          const source = clip.source_range;
          const segment = timelineSegmentsByClip.get(clip.clip_code);
          return (
            <article key={clip.clip_code}>
              <header>
                <code>{clip.clip_code}</code>
                <small>
                  {timelineSeconds(clip.timeline_range.start_ms)} - {timelineSeconds(
                    clip.timeline_range.start_ms + clip.timeline_range.duration_ms,
                  )}
                </small>
              </header>
              <dl>
                <div>
                  <dt>画面源</dt>
                  <dd>
                    <code>{source?.asset_code || "基线视觉源"}</code>
                    {typeof source?.start_seconds === "number" &&
                    typeof source.end_seconds === "number"
                      ? ` · ${source.start_seconds.toFixed(2)}-${source.end_seconds.toFixed(2)} 秒`
                      : null}
                  </dd>
                </div>
                <div>
                  <dt>来源镜头</dt>
                  <dd>
                    <code>
                      {segment?.sourceShotCode ?? clip.source_shot_code ?? "待迁移"}
                    </code>
                  </dd>
                </div>
                {segment?.sourceScriptBlockCodes.length ? (
                  <div>
                    <dt>脚本块</dt>
                    <dd>
                      {segment.sourceScriptBlockCodes.map((code) => (
                        <code key={code}>{code}</code>
                      ))}
                    </dd>
                  </div>
                ) : null}
                {segment ? (
                  <div>
                    <dt>时间轴投影</dt>
                    <dd>
                      <code>{segment.segmentCode}</code>
                    </dd>
                  </div>
                ) : null}
                {segment?.executionArtifactRefs.length ? (
                  <div>
                    <dt>执行产物</dt>
                    <dd>
                      {segment.executionArtifactRefs.map((artifact) => (
                        <code key={`${artifact.artifactRole}-${artifact.jobAttempt}`}>
                          {artifact.artifactRole} r{artifact.jobAttempt} {artifact.checksumSha256.slice(0, 12)}
                        </code>
                      ))}
                    </dd>
                  </div>
                ) : null}
                <div>
                  <dt>转场</dt>
                  <dd>{clip.transition ?? "cut"}</dd>
                </div>
                <div>
                  <dt>标题</dt>
                  <dd>{subtitle?.headline_text || "--"}</dd>
                </div>
                <div className="video-input-trace-wide">
                  <dt>字幕</dt>
                  <dd>{subtitle?.subtitle_text || "--"}</dd>
                </div>
                <div>
                  <dt>旁白增益</dt>
                  <dd>{decimal(voice?.gain_db, " dB")}</dd>
                </div>
                {clip.audio_roles?.includes("sound_effect") ? (
                  <div>
                    <dt>音效</dt>
                    <dd>镜头起点</dd>
                  </div>
                ) : null}
              </dl>
            </article>
          );
        })}
        {backgroundMusic ? (
          <article className="video-input-trace-bgm">
            <header>
              <code>BGM-01</code>
              <small>背景音乐</small>
            </header>
            <dl>
              <div className="video-input-trace-wide">
                <dt>音乐源</dt>
                <dd>
                  <code>{backgroundMusic.assetCode}</code> · {backgroundMusic.checksumSha256.slice(0, 12)}
                </dd>
              </div>
              <div>
                <dt>增益</dt>
                <dd>{backgroundMusic.gainDb.toFixed(1)} dB</dd>
              </div>
            </dl>
          </article>
        ) : null}
        {soundEffect ? (
          <article className="video-input-trace-bgm">
            <header>
              <code>SFX-01</code>
              <small>镜头音效</small>
            </header>
            <dl>
              <div className="video-input-trace-wide">
                <dt>音效源</dt>
                <dd>
                  <code>{soundEffect.assetCode}</code> · {soundEffect.checksumSha256.slice(0, 12)}
                </dd>
              </div>
              <div>
                <dt>增益</dt>
                <dd>{soundEffect.gainDb.toFixed(1)} dB</dd>
              </div>
            </dl>
          </article>
        ) : null}
        {productSticker ? (
          <article className="video-input-trace-product">
            <header>
              <code>PRODUCT-STICKER</code>
              <small>商品贴片</small>
            </header>
            <dl>
              <div className="video-input-trace-wide">
                <dt>图片源</dt>
                <dd>
                  <code>{productSticker.assetCode}</code> · {productSticker.checksumSha256.slice(0, 12)}
                </dd>
              </div>
            </dl>
          </article>
        ) : null}
        {brandLogo ? (
          <article className="video-input-trace-product">
            <header>
              <code>BRAND-LOGO</code>
              <small>品牌标识</small>
            </header>
            <dl>
              <div className="video-input-trace-wide">
                <dt>图片源</dt>
                <dd>
                  <code>{brandLogo.assetCode}</code> · {brandLogo.checksumSha256.slice(0, 12)}
                </dd>
              </div>
            </dl>
          </article>
        ) : null}
      </div>
    </section>
  );
}

function TimelineRevisionHistory({ plan }: { plan: FunctionalVideoPlan }) {
  const queryClient = useQueryClient();
  const revisions = useQuery({
    queryKey: ["functional-video", plan.planCode, "timeline-revisions"],
    queryFn: () => functionalVideosApi.listTimelineRevisions(plan.planCode),
  });
  const restore = useMutation({
    mutationFn: (sourceRevision: number) =>
      functionalVideosApi.restoreTimelineRevision(
        plan.planCode,
        sourceRevision,
        plan.timelineRevision,
      ),
    onSuccess: (next) => {
      queryClient.setQueryData(["functional-video", plan.planCode], next);
      void queryClient.invalidateQueries({ queryKey: ["functional-videos"] });
      void queryClient.invalidateQueries({
        queryKey: ["functional-video", plan.planCode, "timeline-revisions"],
      });
    },
  });
  if (revisions.isLoading)
    return (
      <div className="video-timeline-history">
        <small>正在读取修订历史</small>
      </div>
    );
  if (revisions.error)
    return (
      <div className="video-timeline-history">
        <InlineNotice tone="warning" title="时间轴历史不可用">
          {text(revisions.error)}
        </InlineNotice>
      </div>
    );
  const history = revisions.data ?? [];
  const current = history.find(
    (revision) => revision.revisionNumber === plan.timelineRevision,
  );
  const previous = history.find(
    (revision) => revision.revisionNumber === plan.timelineRevision - 1,
  );
  return (
    <div className="video-timeline-history">
      <div>
        <strong>修订历史</strong>
        <small>
          {timelineDiff(
            plan.productionTimeline,
            previous?.productionTimeline,
          ).join(" · ")}
        </small>
      </div>
      <ol>
        {history.map((revision, index) => {
          const prior = history[index + 1];
          return (
            <li key={revision.revisionNumber}>
            <span>
              <strong>r{revision.revisionNumber}</strong>
              <small>
                {timelineClips(revision.productionTimeline)
                  .map((clip) => clip.clip_code)
                  .join(" / ")}{" "}
                ·{" "}
                {(revision.productionTimeline.global_end_ms / 1000).toFixed(1)}{" "}
                秒
              </small>
              <small>
                {timelineDiff(
                  revision.productionTimeline,
                  prior?.productionTimeline,
                ).join(" · ")}
              </small>
            </span>
            <span className="video-timeline-history-actions">
              <StatusBadge
                label={
                  revision.revisionNumber === current?.revisionNumber
                    ? "当前"
                    : revision.actorId
                }
                tone={
                  revision.revisionNumber === current?.revisionNumber
                    ? "info"
                    : "neutral"
                }
              />
              {plan.jobStatus === "queued" &&
              revision.revisionNumber !== current?.revisionNumber ? (
                <button
                  type="button"
                  className="wb-icon-button"
                  title={`恢复 r${revision.revisionNumber} 为新修订`}
                  aria-label={`恢复 r${revision.revisionNumber}`}
                  disabled={restore.isPending}
                  onClick={() => restore.mutate(revision.revisionNumber)}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                </button>
              ) : null}
            </span>
            </li>
          );
        })}
      </ol>
      {restore.error ? (
        <InlineNotice tone="danger" title="时间轴恢复失败">
          {text(restore.error)}
        </InlineNotice>
      ) : null}
    </div>
  );
}

type EditableTimelineClip = {
  clipCode: string;
  durationMs: number;
  transition: string;
  sourceAssetCode?: string;
  initialSourceAssetCode?: string;
  sourceStartSeconds?: number;
  sourceEndSeconds?: number;
  sourceAvailableStartSeconds?: number;
  sourceAvailableEndSeconds?: number;
  fit?: "cover" | "contain";
  cropX?: number;
  cropY?: number;
  playbackRate?: number;
  brandLogo?: boolean;
  productSticker?: boolean;
  overlayZOrder?: { brandLogo?: number; productSticker?: number };
  productStickerX?: number;
  productStickerY?: number;
  productStickerWidthRatio?: number;
  productStickerSuggestion?: {
    x: number;
    y: number;
    widthRatio: number;
    tableSurfaceName?: string;
    approximate?: boolean;
  };
  soundEffect?: boolean;
};

function editableTimelineClips(
  videoTrack:
    | FunctionalVideoPlan["productionTimeline"]["tracks"][number]
    | undefined,
): EditableTimelineClip[] {
  return (
    videoTrack?.clips.map((clip) => ({
      clipCode: clip.clip_code,
      durationMs: clip.timeline_range.duration_ms,
      transition: clip.transition ?? "cut",
      sourceAssetCode: clip.source_range?.asset_code,
      initialSourceAssetCode: clip.source_range?.asset_code,
      sourceStartSeconds: clip.source_range?.start_seconds,
      sourceEndSeconds: clip.source_range?.end_seconds,
      sourceAvailableStartSeconds: clip.source_range?.available_start_seconds,
      sourceAvailableEndSeconds: clip.source_range?.available_end_seconds,
      fit: clip.fit,
      cropX: clip.crop_x,
      cropY: clip.crop_y,
      playbackRate: clip.playback_rate,
      brandLogo: clip.overlay_roles?.includes("brand_logo"),
      productSticker: clip.overlay_roles?.includes("product_sticker"),
      overlayZOrder: clip.overlay_z_order
        ? {
            brandLogo: clip.overlay_z_order.brand_logo,
            productSticker: clip.overlay_z_order.product_sticker,
          }
        : undefined,
      productStickerX: clip.product_sticker_layout?.x,
      productStickerY: clip.product_sticker_layout?.y,
      productStickerWidthRatio: clip.product_sticker_layout?.width_ratio,
      productStickerSuggestion: clip.product_sticker_layout_suggestion
        ? {
            x: clip.product_sticker_layout_suggestion.x,
            y: clip.product_sticker_layout_suggestion.y,
            widthRatio: clip.product_sticker_layout_suggestion.width_ratio,
            tableSurfaceName:
              clip.product_sticker_layout_suggestion.table_surface_name,
            approximate: clip.product_sticker_layout_suggestion.approximate,
          }
        : undefined,
      soundEffect: clip.audio_roles?.includes("sound_effect"),
    })) ?? []
  );
}

type EditableSubtitleClip = {
  clipCode: string;
  shotCode: string;
  subtitleText: string;
  headlineText: string;
  captionPosition: "bottom" | "center";
};

type EditableSubtitleStyle = {
  preset: "compact" | "standard" | "large";
  safeBottomPx: number;
};

function editableSubtitleStyle(plan: FunctionalVideoPlan): EditableSubtitleStyle {
  const style = plan.productionTimeline.subtitle_style;
  return {
    preset: style?.preset ?? "standard",
    safeBottomPx: style?.safe_bottom_px ?? 160,
  };
}

function editableSubtitleClips(
  subtitleTrack:
    | FunctionalVideoPlan["productionTimeline"]["tracks"][number]
    | undefined,
): EditableSubtitleClip[] {
  return (
    subtitleTrack?.clips.map((clip) => ({
      clipCode: clip.clip_code,
      shotCode:
        clip.linked_shot_code ?? clip.clip_code.replace(/^SUBTITLE-/, ""),
      subtitleText: clip.subtitle_text ?? "",
      headlineText: clip.headline_text ?? "",
      captionPosition: clip.caption_position ?? "bottom",
    })) ?? []
  );
}

type EditableAudioClip = {
  clipCode: string;
  shotCode: string;
  gainDb: number;
};

function editableAudioClips(
  audioTrack:
    | FunctionalVideoPlan["productionTimeline"]["tracks"][number]
    | undefined,
): EditableAudioClip[] {
  return (
    audioTrack?.clips
      .filter((clip) => clip.clip_code.startsWith("VOICE-"))
      .map((clip) => ({
        clipCode: clip.clip_code,
        shotCode:
          clip.linked_shot_code ?? clip.clip_code.replace(/^VOICE-/, ""),
        gainDb: clip.gain_db ?? 0,
      })) ?? []
  );
}

function TimelineEditor({ plan }: { plan: FunctionalVideoPlan }) {
  const queryClient = useQueryClient();
  const videoTrack = plan.productionTimeline.tracks.find(
    (track) => track.track_kind === "video",
  );
  const audioTrack = plan.productionTimeline.tracks.find(
    (track) => track.track_kind === "audio",
  );
  const subtitleTrack = plan.productionTimeline.tracks.find(
    (track) => track.track_kind === "subtitle",
  );
  const [clips, setClips] = useState<EditableTimelineClip[]>(() =>
    editableTimelineClips(videoTrack),
  );
  const [audioClips, setAudioClips] = useState<EditableAudioClip[]>(() =>
    editableAudioClips(audioTrack),
  );
  const [subtitleClips, setSubtitleClips] = useState<EditableSubtitleClip[]>(
    () => editableSubtitleClips(subtitleTrack),
  );
  const [subtitleStyle, setSubtitleStyle] = useState<EditableSubtitleStyle>(
    () => editableSubtitleStyle(plan),
  );
  const [posterTimeMs, setPosterTimeMs] = useState(
    () => plan.productionTimeline.poster_time_ms ?? 2_000,
  );
  useEffect(
    () => setClips(editableTimelineClips(videoTrack)),
    [plan.timelineRevision, videoTrack],
  );
  useEffect(
    () => setAudioClips(editableAudioClips(audioTrack)),
    [plan.timelineRevision, audioTrack],
  );
  useEffect(
    () => setSubtitleClips(editableSubtitleClips(subtitleTrack)),
    [plan.timelineRevision, subtitleTrack],
  );
  useEffect(
    () => setSubtitleStyle(editableSubtitleStyle(plan)),
    [plan.timelineRevision, plan.productionTimeline.subtitle_style],
  );
  useEffect(
    () => setPosterTimeMs(plan.productionTimeline.poster_time_ms ?? 2_000),
    [plan.timelineRevision, plan.productionTimeline.poster_time_ms],
  );
  const update = useMutation({
    mutationFn: () =>
      functionalVideosApi.updateTimeline(plan.planCode, {
        expected_revision: plan.timelineRevision,
        poster_time_ms: posterTimeMs,
        subtitle_style: {
          preset: subtitleStyle.preset,
          safe_bottom_px: subtitleStyle.safeBottomPx,
        },
        video_clips: clips.map((clip) => ({
          clip_code: clip.clipCode,
          duration_ms: clip.durationMs,
          transition: clip.transition,
          ...(typeof clip.sourceStartSeconds === "number" &&
          typeof clip.sourceEndSeconds === "number"
            ? {
                ...(clip.sourceAssetCode !== clip.initialSourceAssetCode &&
                clip.sourceAssetCode
                  ? { source_asset_code: clip.sourceAssetCode }
                  : {}),
                source_start_seconds: clip.sourceStartSeconds,
                source_end_seconds: clip.sourceEndSeconds,
              }
            : {}),
          ...(clip.fit ? { fit: clip.fit } : {}),
          ...(typeof clip.cropX === "number" && typeof clip.cropY === "number"
            ? { crop_x: clip.cropX, crop_y: clip.cropY }
            : {}),
          ...(typeof clip.playbackRate === "number"
            ? { playback_rate: clip.playbackRate }
            : {}),
          ...(typeof clip.brandLogo === "boolean"
            ? { show_brand_logo: clip.brandLogo }
            : {}),
          ...(typeof clip.productSticker === "boolean"
            ? { show_product_sticker: clip.productSticker }
            : {}),
          ...(typeof clip.productStickerX === "number" &&
          typeof clip.productStickerY === "number" &&
          typeof clip.productStickerWidthRatio === "number"
            ? {
                product_sticker_x: clip.productStickerX,
                product_sticker_y: clip.productStickerY,
                product_sticker_width_ratio: clip.productStickerWidthRatio,
              }
            : {}),
          ...(typeof clip.soundEffect === "boolean"
            ? { play_sound_effect: clip.soundEffect }
            : {}),
        })),
        subtitle_clips: subtitleClips.map((clip) => ({
          clip_code: clip.clipCode,
          subtitle_text: clip.subtitleText,
          headline_text: clip.headlineText,
          caption_position: clip.captionPosition,
        })),
        ...(audioClips.length
          ? {
              audio_clips: audioClips.map((clip) => ({
                clip_code: clip.clipCode,
                gain_db: clip.gainDb,
              })),
            }
          : {}),
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(["functional-video", plan.planCode], next);
      void queryClient.invalidateQueries({ queryKey: ["functional-videos"] });
      void queryClient.invalidateQueries({
        queryKey: ["functional-video", plan.planCode, "timeline-revisions"],
      });
    },
  });
  const totalSeconds =
    clips.reduce((sum, clip) => sum + clip.durationMs, 0) / 1000;
  const maximumPosterTimeMs = Math.max(0, Math.round(totalSeconds * 1_000) - 1);
  const frozenVisualAssets = plan.renderProfile.visualAssets ?? [];
  const updateClip = (index: number, changes: Partial<EditableTimelineClip>) =>
    setClips((current) =>
      current.map((clip, clipIndex) =>
        clipIndex === index ? { ...clip, ...changes } : clip,
      ),
    );
  const updateAudio = (index: number, changes: Partial<EditableAudioClip>) =>
    setAudioClips((current) =>
      current.map((clip, clipIndex) =>
        clipIndex === index ? { ...clip, ...changes } : clip,
      ),
    );
  const updateSubtitle = (
    index: number,
    changes: Partial<EditableSubtitleClip>,
  ) =>
    setSubtitleClips((current) =>
      current.map((clip, clipIndex) =>
        clipIndex === index ? { ...clip, ...changes } : clip,
      ),
    );
  const moveClip = (index: number, offset: number) =>
    setClips((current) => {
      const destination = index + offset;
      if (destination < 0 || destination >= current.length) return current;
      const next = [...current];
      [next[index], next[destination]] = [next[destination]!, next[index]!];
      return next;
    });
  const editable = plan.jobStatus === "queued";
  const subtitleContentInvalid = subtitleClips.some(
    (clip) => !clip.subtitleText.trim(),
  );
  const subtitleStyleInvalid =
    !Number.isInteger(subtitleStyle.safeBottomPx) ||
    subtitleStyle.safeBottomPx < 80 ||
    subtitleStyle.safeBottomPx > 360;
  const posterTimeInvalid =
    !Number.isInteger(posterTimeMs) ||
    posterTimeMs < 0 ||
    posterTimeMs > maximumPosterTimeMs;
  return (
    <section className="wb-section">
      <SectionHeader
        kicker={`TIMELINE r${plan.timelineRevision}`}
        title="时间轴"
        actions={
          <StatusBadge label={`${totalSeconds.toFixed(1)} 秒`} tone="info" />
        }
      />
      <div className="video-timeline">
        {clips.map((clip) => (
          <div
            key={clip.clipCode}
            style={{ flexGrow: Math.max(1, clip.durationMs) }}
          >
            <span>{clip.clipCode}</span>
            <strong>{(clip.durationMs / 1000).toFixed(1)}s</strong>
            <small>
              {videoTrack?.clips.find(
                (item) => item.clip_code === clip.clipCode,
              )?.source_range?.asset_code ?? "voice"}{" "}
              · {clip.transition}
            </small>
          </div>
        ))}
      </div>
      <label className="wb-field video-poster-control">
        <span>海报帧（秒）</span>
        <input
          aria-label="海报帧（秒）"
          className="wb-input"
          type="number"
          min="0"
          max={maximumPosterTimeMs / 1_000}
          step="0.001"
          value={posterTimeMs / 1_000}
          disabled={!editable}
          onChange={(event) =>
            setPosterTimeMs(Math.round(Number(event.target.value) * 1_000))
          }
        />
      </label>
      <div className="video-timeline-editor">
        {clips.map((clip, index) => {
          const hasSourceRange =
            typeof clip.sourceStartSeconds === "number" &&
            typeof clip.sourceEndSeconds === "number";
          const sourceLowerBound = clip.sourceAvailableStartSeconds ?? 0;
          const sourceUpperBound = clip.sourceAvailableEndSeconds;
          const cropEnabled = clip.fit !== "contain";
          return (
            <div key={clip.clipCode}>
              <code>{clip.clipCode}</code>
              <div className="video-clip-order">
                <button
                  type="button"
                  className="wb-icon-button"
                  title="上移镜头"
                  aria-label={`上移 ${clip.clipCode}`}
                  disabled={!editable || index === 0}
                  onClick={() => moveClip(index, -1)}
                >
                  <ArrowUp size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="wb-icon-button"
                  title="下移镜头"
                  aria-label={`下移 ${clip.clipCode}`}
                  disabled={!editable || index === clips.length - 1}
                  onClick={() => moveClip(index, 1)}
                >
                  <ArrowDown size={14} aria-hidden="true" />
                </button>
              </div>
              <label className="wb-field">
                <span>时长（毫秒）</span>
                <input
                  className="wb-input"
                  type="number"
                  min="250"
                  max="120000"
                  value={clip.durationMs}
                  disabled={!editable}
                  onChange={(event) =>
                    updateClip(index, {
                      durationMs: Number(event.target.value),
                    })
                  }
                />
              </label>
              {frozenVisualAssets.length ? (
                <label className="wb-field">
                  <span>画面素材</span>
                  <select
                    aria-label={`画面素材 ${clip.clipCode}`}
                    className="wb-input"
                    value={clip.sourceAssetCode ?? ""}
                    disabled={!editable}
                    onChange={(event) =>
                      updateClip(index, {
                        sourceAssetCode: event.target.value || undefined,
                        sourceStartSeconds: 0,
                        sourceEndSeconds: 6,
                        sourceAvailableStartSeconds: 0,
                        sourceAvailableEndSeconds: 6,
                      })
                    }
                  >
                    <option value="">沿用当前素材</option>
                    {frozenVisualAssets.map((asset) => (
                      <option key={asset.assetCode} value={asset.assetCode}>
                        {asset.assetCode} · {asset.checksumSha256.slice(0, 12)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="wb-field">
                <span>转场</span>
                <select
                  className="wb-input"
                  value={clip.transition}
                  disabled={!editable}
                  onChange={(event) =>
                    updateClip(index, { transition: event.target.value })
                  }
                >
                  <option value="cut">直接切换</option>
                  <option value="fade">淡入淡出</option>
                  <option value="fade_out">淡出</option>
                </select>
              </label>
              <label className="wb-field">
                <span>画面适配</span>
                <select
                  aria-label={`画面适配 ${clip.clipCode}`}
                  className="wb-input"
                  value={clip.fit ?? ""}
                  disabled={!editable}
                  onChange={(event) => {
                    const fit = event.target.value;
                    updateClip(index, {
                      fit:
                        fit === "cover" || fit === "contain" ? fit : undefined,
                      ...(fit === "contain"
                        ? { cropX: undefined, cropY: undefined }
                        : {}),
                    });
                  }}
                >
                  <option value="">沿用</option>
                  <option value="cover">cover</option>
                  <option value="contain">contain</option>
                </select>
              </label>
              <label className="wb-field">
                <span>播放速度</span>
                <select
                  aria-label={`播放速度 ${clip.clipCode}`}
                  className="wb-input"
                  value={clip.playbackRate ?? 1}
                  disabled={!editable}
                  onChange={(event) =>
                    updateClip(index, {
                      playbackRate: Number(event.target.value),
                    })
                  }
                >
                  <option value="0.5">0.5x</option>
                  <option value="0.75">0.75x</option>
                  <option value="1">1x</option>
                  <option value="1.25">1.25x</option>
                  <option value="1.5">1.5x</option>
                  <option value="2">2x</option>
                </select>
              </label>
              <label className="wb-field video-overlay-toggle">
                <span>品牌标识</span>
                <input
                  aria-label={`品牌标识 ${clip.clipCode}`}
                  type="checkbox"
                  checked={clip.brandLogo ?? false}
                  disabled={!editable}
                  onChange={(event) =>
                    updateClip(index, { brandLogo: event.target.checked })
                  }
                />
              </label>
              <label className="wb-field video-overlay-toggle">
                <span>商品贴片</span>
                <input
                  aria-label={`商品贴片 ${clip.clipCode}`}
                  type="checkbox"
                  checked={clip.productSticker ?? false}
                  disabled={!editable}
                  onChange={(event) =>
                    updateClip(
                      index,
                      event.target.checked
                        ? {
                            productSticker: true,
                            productStickerX:
                              clip.productStickerSuggestion?.x ?? 0.5,
                            productStickerY:
                              clip.productStickerSuggestion?.y ?? 0.8,
                            productStickerWidthRatio:
                              clip.productStickerSuggestion?.widthRatio ??
                              640 / 1080,
                          }
                        : {
                            productSticker: false,
                            productStickerX: undefined,
                            productStickerY: undefined,
                            productStickerWidthRatio: undefined,
                          },
                    )
                  }
                />
              </label>
              {clip.productSticker ? (
                <div className="video-product-sticker-layout">
                  {clip.productStickerSuggestion ? (
                    <small className="video-product-sticker-suggestion">
                      桌面区域建议：
                      {clip.productStickerSuggestion.tableSurfaceName ??
                        "table_surface"}
                      {clip.productStickerSuggestion.approximate
                        ? "（近似）"
                        : ""}
                    </small>
                  ) : null}
                  {typeof clip.overlayZOrder?.productSticker === "number" ? (
                    <small className="video-product-sticker-suggestion">
                      商品图层：
                      {clip.overlayZOrder.productSticker >= 1000
                        ? "顶部"
                        : clip.overlayZOrder.productSticker <= -1000
                          ? "底部"
                          : "默认"}
                    </small>
                  ) : null}
                  <label className="wb-field">
                    <span>
                      商品位置 X {Math.round((clip.productStickerX ?? 0.5) * 100)}%
                    </span>
                    <input
                      aria-label={`商品位置 X ${clip.clipCode}`}
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={Math.round((clip.productStickerX ?? 0.5) * 100)}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          productStickerX: Number(event.target.value) / 100,
                          productStickerY:
                            clip.productStickerY ??
                            clip.productStickerSuggestion?.y ??
                            0.8,
                          productStickerWidthRatio:
                            clip.productStickerWidthRatio ??
                            clip.productStickerSuggestion?.widthRatio ??
                            640 / 1080,
                        })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>
                      商品位置 Y {Math.round((clip.productStickerY ?? clip.productStickerSuggestion?.y ?? 0.8) * 100)}%
                    </span>
                    <input
                      aria-label={`商品位置 Y ${clip.clipCode}`}
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={Math.round((clip.productStickerY ?? clip.productStickerSuggestion?.y ?? 0.8) * 100)}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          productStickerX:
                            clip.productStickerX ??
                            clip.productStickerSuggestion?.x ??
                            0.5,
                          productStickerY: Number(event.target.value) / 100,
                          productStickerWidthRatio:
                            clip.productStickerWidthRatio ??
                            clip.productStickerSuggestion?.widthRatio ??
                            640 / 1080,
                        })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>
                      商品宽度 {Math.round((clip.productStickerWidthRatio ?? clip.productStickerSuggestion?.widthRatio ?? 640 / 1080) * 100)}%
                    </span>
                    <input
                      aria-label={`商品宽度 ${clip.clipCode}`}
                      type="range"
                      min="10"
                      max="100"
                      step="1"
                      value={Math.round(
                        (clip.productStickerWidthRatio ??
                          clip.productStickerSuggestion?.widthRatio ??
                          640 / 1080) *
                          100,
                      )}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          productStickerX:
                            clip.productStickerX ??
                            clip.productStickerSuggestion?.x ??
                            0.5,
                          productStickerY:
                            clip.productStickerY ??
                            clip.productStickerSuggestion?.y ??
                            0.8,
                          productStickerWidthRatio:
                            Number(event.target.value) / 100,
                        })
                      }
                    />
                  </label>
                </div>
              ) : null}
              <label className="wb-field video-overlay-toggle">
                <span>音效</span>
                <input
                  aria-label={`音效 ${clip.clipCode}`}
                  type="checkbox"
                  checked={clip.soundEffect ?? false}
                  disabled={!editable}
                  onChange={(event) =>
                    updateClip(index, { soundEffect: event.target.checked })
                  }
                />
              </label>
              {cropEnabled ? (
                <div className="video-crop-position">
                  <label className="wb-field">
                    <span>
                      裁切焦点 X {Math.round((clip.cropX ?? 0.5) * 100)}%
                    </span>
                    <input
                      aria-label={`裁切焦点 X ${clip.clipCode}`}
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={Math.round((clip.cropX ?? 0.5) * 100)}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          cropX: Number(event.target.value) / 100,
                          cropY: clip.cropY ?? 0.5,
                        })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>
                      裁切焦点 Y {Math.round((clip.cropY ?? 0.5) * 100)}%
                    </span>
                    <input
                      aria-label={`裁切焦点 Y ${clip.clipCode}`}
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={Math.round((clip.cropY ?? 0.5) * 100)}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          cropX: clip.cropX ?? 0.5,
                          cropY: Number(event.target.value) / 100,
                        })
                      }
                    />
                  </label>
                </div>
              ) : null}
              {hasSourceRange ? (
                <div className="video-source-range">
                  <label className="wb-field">
                    <span>素材入点（秒）</span>
                    <input
                      aria-label={`素材入点 ${clip.clipCode}`}
                      className="wb-input"
                      type="number"
                      step="0.01"
                      min={sourceLowerBound}
                      max={clip.sourceEndSeconds! - 0.01}
                      value={clip.sourceStartSeconds}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          sourceStartSeconds: Number(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>素材出点（秒）</span>
                    <input
                      aria-label={`素材出点 ${clip.clipCode}`}
                      className="wb-input"
                      type="number"
                      step="0.01"
                      min={clip.sourceStartSeconds! + 0.01}
                      max={sourceUpperBound}
                      value={clip.sourceEndSeconds}
                      disabled={!editable}
                      onChange={(event) =>
                        updateClip(index, {
                          sourceEndSeconds: Number(event.target.value),
                        })
                      }
                    />
                  </label>
                  <small>
                    固定可用范围 {sourceLowerBound.toFixed(2)}-
                    {sourceUpperBound?.toFixed(2) ?? "--"} 秒
                  </small>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      {posterTimeInvalid ? (
        <InlineNotice tone="warning" title="海报帧超出时间轴">
          海报帧必须位于成片有效时长内。
        </InlineNotice>
      ) : null}
      {audioClips.length ? (
        <div className="video-audio-editor">
          <header>
            <strong>配音轨</strong>
            <small>增益会随对应镜头固定，重新渲染时写入音频处理。</small>
          </header>
          {audioClips.map((clip, index) => (
            <label key={clip.clipCode} className="wb-field">
              <span>
                {clip.shotCode} · {clip.gainDb.toFixed(1)} dB
              </span>
              <input
                aria-label={`配音增益 ${clip.shotCode}`}
                type="range"
                min="-24"
                max="12"
                step="0.5"
                value={clip.gainDb}
                disabled={!editable}
                onChange={(event) =>
                  updateAudio(index, { gainDb: Number(event.target.value) })
                }
              />
            </label>
          ))}
        </div>
      ) : null}
      {subtitleTrack ? (
        <div className="video-subtitle-editor">
          <header>
            <strong>字幕轨</strong>
            <div className="video-subtitle-style">
              <label className="wb-field">
                <span>字幕样式</span>
                <select
                  aria-label="字幕样式"
                  className="wb-input"
                  value={subtitleStyle.preset}
                  disabled={!editable}
                  onChange={(event) =>
                    setSubtitleStyle((current) => ({
                      ...current,
                      preset:
                        event.target.value === "compact" ||
                        event.target.value === "large"
                          ? event.target.value
                          : "standard",
                    }))
                  }
                >
                  <option value="compact">紧凑</option>
                  <option value="standard">标准</option>
                  <option value="large">大字</option>
                </select>
              </label>
              <label className="wb-field">
                <span>字幕底部安全边距（像素）</span>
                <input
                  aria-label="字幕底部安全边距（像素）"
                  className="wb-input"
                  type="number"
                  min="80"
                  max="360"
                  step="1"
                  value={subtitleStyle.safeBottomPx}
                  disabled={!editable}
                  onChange={(event) =>
                    setSubtitleStyle((current) => ({
                      ...current,
                      safeBottomPx: Number(event.target.value),
                    }))
                  }
                />
              </label>
            </div>
          </header>
          {subtitleClips.map((clip, index) => (
            <div key={clip.clipCode}>
              <code>{clip.shotCode}</code>
              <label className="wb-field">
                <span>字幕文本</span>
                <textarea
                  aria-label={`字幕文本 ${clip.shotCode}`}
                  className="wb-input"
                  rows={2}
                  maxLength={500}
                  value={clip.subtitleText}
                  disabled={!editable}
                  onChange={(event) =>
                    updateSubtitle(index, { subtitleText: event.target.value })
                  }
                />
              </label>
              <label className="wb-field">
                <span>标题文本</span>
                <input
                  aria-label={`标题文本 ${clip.shotCode}`}
                  className="wb-input"
                  maxLength={160}
                  value={clip.headlineText}
                  disabled={!editable}
                  onChange={(event) =>
                    updateSubtitle(index, { headlineText: event.target.value })
                  }
                />
              </label>
              <label className="wb-field">
                <span>字幕位置</span>
                <select
                  aria-label={`字幕位置 ${clip.shotCode}`}
                  className="wb-input"
                  value={clip.captionPosition}
                  disabled={!editable}
                  onChange={(event) =>
                    updateSubtitle(index, {
                      captionPosition:
                        event.target.value === "center" ? "center" : "bottom",
                    })
                  }
                >
                  <option value="bottom">底部</option>
                  <option value="center">居中</option>
                </select>
              </label>
            </div>
          ))}
        </div>
      ) : null}
      {subtitleContentInvalid ? (
        <InlineNotice tone="warning" title="字幕文本不能为空">
          每个固定镜头均需保留一段字幕文本。
        </InlineNotice>
      ) : null}
      {subtitleStyleInvalid ? (
        <InlineNotice tone="warning" title="字幕安全边距无效">
          字幕底部安全边距必须在 80 到 360 像素之间。
        </InlineNotice>
      ) : null}
      <TimelineRevisionHistory plan={plan} />
      {editable ? (
        <div className="wb-form-actions">
          <button
            type="button"
            className="wb-button wb-button-primary"
              disabled={
                update.isPending ||
                totalSeconds < 30 ||
                totalSeconds > 120 ||
                subtitleContentInvalid ||
                subtitleStyleInvalid ||
                posterTimeInvalid
              }
            onClick={() => update.mutate()}
          >
            保存时间轴修订
          </button>
        </div>
      ) : (
        <InlineNotice tone="warning" title="时间轴已锁定">
          渲染任务已锁定。请创建新的成片分支进行调整。
        </InlineNotice>
      )}
      {update.error ? (
        <InlineNotice tone="danger" title="时间轴未保存">
          {text(update.error)}
        </InlineNotice>
      ) : null}
    </section>
  );
}

function WorkflowPanel({ plan }: { plan: FunctionalVideoPlan }) {
  if (!plan.workflowStages.length) return null;
  return (
    <section className="wb-section">
      <SectionHeader
        kicker="WORKFLOW RUN"
        title="生产阶段"
        actions={
          <StatusBadge
            label={`${plan.workflowStages.filter((stage) => stage.status === "succeeded").length}/${plan.workflowStages.length}`}
            tone="info"
          />
        }
      />
      <ol className="video-workflow">
        {plan.workflowStages.map((stage) => (
          <li key={`${stage.stageOrder}:${stage.stageName}`}>
            <span>{stage.stageOrder}</span>
            <div>
              <strong>{stageLabel(stage.stageName)}</strong>
              <small>
                attempt {stage.attempt}
                {stage.errorCode ? ` · ${stage.errorCode}` : ""}
              </small>
              {stage.errorMessage ? (
                <small className="video-stage-error">
                  {stage.errorMessage}
                </small>
              ) : null}
            </div>
            <StatusBadge label={stage.status} tone={stageTone(stage.status)} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function ReleaseCandidatePanel({ plan }: { plan: FunctionalVideoPlan }) {
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => functionalVideosApi.createReleaseCandidate(plan.planCode),
    onSuccess: (next) => {
      queryClient.setQueryData(["functional-video", plan.planCode], next);
      void queryClient.invalidateQueries({ queryKey: ["functional-videos"] });
    },
  });
  const eligible =
    plan.jobStatus === "succeeded" && plan.qualityReport.passed === true;
  return (
    <section className="wb-section">
      <SectionHeader
        kicker="RELEASE CANDIDATE"
        title="发布候选"
        actions={
          plan.release ? (
            <StatusBadge label={plan.release.status} tone="warning" />
          ) : undefined
        }
      />
      <div className="video-release-candidate">
        {plan.release ? (
          <>
            <span>
              <strong>{plan.release.releaseCode}</strong>
              <small>
                {plan.release.manifestCode} ·{" "}
                {plan.release.manifestFingerprint.slice(0, 12)}
              </small>
            </span>
            <a
              className="wb-button wb-button-secondary"
              href={`/production/releases?release=${encodeURIComponent(plan.release.releaseCode)}`}
            >
              查看 Manifest
            </a>
          </>
        ) : (
          <>
            <span>
              <strong>{eligible ? "可创建候选" : "等待渲染和 QC 通过"}</strong>
              <small>
                候选会固定时间轴、渲染配置、质量报告和成片校验和；不会批准或交付。
              </small>
            </span>
            <button
              type="button"
              className="wb-button wb-button-secondary"
              disabled={!eligible || create.isPending}
              onClick={() => create.mutate()}
            >
              <FileCheck2 size={15} aria-hidden="true" />
              创建发布候选
            </button>
          </>
        )}
      </div>
      {create.error ? (
        <InlineNotice tone="danger" title="发布候选未创建">
          {text(create.error)}
        </InlineNotice>
      ) : null}
    </section>
  );
}

function QualityPanel({ plan }: { plan: FunctionalVideoPlan }) {
  const checks = Object.entries(plan.qualityReport.checks);
  const passed = plan.qualityReport.passed === true;
  const { media, loudness, diagnostics } = plan.qualityReport;
  const anomalyGroups = [
    { label: "黑帧", segments: diagnostics.blackSegments },
    { label: "静音", segments: diagnostics.silenceSegments },
    { label: "冻结", segments: diagnostics.freezeSegments },
  ].filter((group) => group.segments.length);
  const hasDetails = Boolean(media || loudness || anomalyGroups.length);
  return (
    <>
      {checks.length || hasDetails ? (
        <section className="wb-section">
          <SectionHeader
            kicker="QC REPORT"
            title="质量检查"
            actions={
              <StatusBadge
                label={passed ? "通过" : "未通过"}
                tone={passed ? "success" : "danger"}
              />
            }
          />
          <ul className="video-quality-checks">
            {checks.map(([key, passedCheck]) => (
              <li key={key}>
                {passedCheck ? (
                  <CheckCircle2 size={15} aria-hidden="true" />
                ) : (
                  <CircleX size={15} aria-hidden="true" />
                )}
                <code>{key}</code>
                <StatusBadge
                  label={passedCheck ? "pass" : "blocked"}
                  tone={passedCheck ? "success" : "danger"}
                />
              </li>
            ))}
          </ul>
          {hasDetails ? (
            <div className="video-quality-diagnostics">
              {media ? (
                <div>
                  <span>媒体</span>
                  <strong>
                    {decimal(media.durationSeconds, " 秒")} · {media.width}x
                    {media.height}
                  </strong>
                  <small>
                    {media.videoCodec ?? "--"} / {media.audioCodec ?? "--"}
                    {media.audioSampleRate
                      ? ` · ${media.audioSampleRate} Hz`
                      : ""}
                  </small>
                </div>
              ) : null}
              {loudness ? (
                <div>
                  <span>响度</span>
                  <strong>
                    {decimal(loudness.integratedLufs, " LUFS")} · 峰值{" "}
                    {decimal(loudness.truePeakDb, " dB")}
                  </strong>
                  <small>LRA {decimal(loudness.lra)}</small>
                </div>
              ) : null}
              {anomalyGroups.map((group) => (
                <div key={group.label}>
                  <span>{group.label}</span>
                  <strong>{group.segments.length} 段</strong>
                  <small>
                    {group.segments
                      .map(
                        (segment) =>
                          `${decimal(segment.startSeconds, "s")}-${decimal(segment.endSeconds, "s")} (${decimal(segment.durationSeconds, "s")})`,
                      )
                      .join(" · ")}
                  </small>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
      <ReleaseCandidatePanel plan={plan} />
    </>
  );
}

function Detail({
  plan,
  onBranchCreated,
}: {
  plan: FunctionalVideoPlan;
  onBranchCreated: (plan: FunctionalVideoPlan) => void;
}) {
  const queryClient = useQueryClient();
  const [branchTitle, setBranchTitle] = useState("");
  const retry = useMutation({
    mutationFn: () => functionalVideosApi.retry(plan.planCode),
    onSuccess: (next) => {
      queryClient.setQueryData(["functional-video", plan.planCode], next);
      void queryClient.invalidateQueries({ queryKey: ["functional-videos"] });
    },
  });
  const branch = useMutation({
    mutationFn: () =>
      functionalVideosApi.branch(plan.planCode, {
        title: branchTitle.trim() || undefined,
      }),
    onSuccess: (next) => {
      setBranchTitle("");
      queryClient.setQueryData(["functional-video", next.planCode], next);
      queryClient.setQueryData<FunctionalVideoPlan[]>(
        ["functional-videos"],
        (current) => [
          next,
          ...(current ?? []).filter((item) => item.planCode !== next.planCode),
        ],
      );
      onBranchCreated(next);
      void queryClient.invalidateQueries({
        queryKey: ["functional-videos"],
        refetchType: "none",
      });
    },
  });
  const videoUrl = plan.artifacts.find(
    (artifact) => artifact.artifact_key === "video",
  )?.download_url;
  const posterUrl = plan.artifacts.find(
    (artifact) => artifact.artifact_key === "poster",
  )?.download_url;
  const contactSheetUrl = plan.artifacts.find(
    (artifact) => artifact.artifact_key === "contact_sheet",
  )?.download_url;
  const hasFrozenMaterialEvidence = Boolean(
      plan.renderProfile.visualAssets?.length ||
      plan.renderProfile.brandLogo ||
      plan.renderProfile.productSticker ||
      plan.renderProfile.backgroundMusic,
  );
  return (
    <div className="video-plan-detail">
      <section className="wb-section">
        <SectionHeader
          kicker={plan.planCode}
          title={plan.title}
          actions={
            <StatusBadge
              label={jobLabel(plan.jobStatus)}
              tone={jobTone(plan.jobStatus)}
            />
          }
        />
        <div className="video-plan-summary">
          <div>
            <span>渲染任务</span>
            <code>{plan.videoJobCode}</code>
          </div>
          <div>
            <span>当前阶段</span>
            <strong>
              {plan.currentStage
                ? stageLabel(plan.currentStage)
                : "等待 Worker"}
            </strong>
          </div>
          <div>
            <span>进度</span>
            <strong>{plan.progressPercent}%</strong>
          </div>
          <div>
            <span>画布</span>
            <strong>
              {plan.renderProfile.canvas
                ? `${plan.renderProfile.canvas.width}x${plan.renderProfile.canvas.height}`
                : "--"}
            </strong>
          </div>
        </div>
        <div className="video-progress">
          <i style={{ width: `${plan.progressPercent}%` }} />
        </div>
        {hasFrozenMaterialEvidence ? (
          <div className="video-frozen-assets">
            <span>冻结视觉素材</span>
            {plan.renderProfile.visualAssets?.map((asset) => (
              <code key={asset.assetCode}>
                {asset.assetCode} · {asset.checksumSha256.slice(0, 12)}
              </code>
            ))}
            {plan.renderProfile.visualSelection?.groups.map((group) => (
              <code key={group.groupCode}>
                分组 {group.title} · {group.groupCode} · {group.assetCodes.length} 项
              </code>
            ))}
            {plan.renderProfile.visualSelection?.materialPacks.map((pack) => (
              <code key={pack.packCode}>
                素材包 {pack.packCode} · r{pack.revisionNumber} · {pack.fingerprintSha256.slice(0, 12)}
              </code>
            ))}
            {plan.renderProfile.backgroundMusic ? (
              <code>
                BGM {plan.renderProfile.backgroundMusic.assetCode} · {plan.renderProfile.backgroundMusic.checksumSha256.slice(0, 12)} · {plan.renderProfile.backgroundMusic.gainDb.toFixed(1)} dB
              </code>
            ) : null}
            {plan.renderProfile.productSticker ? (
              <code>
                商品贴片 {plan.renderProfile.productSticker.assetCode} · {plan.renderProfile.productSticker.checksumSha256.slice(0, 12)}
              </code>
            ) : null}
            {plan.renderProfile.brandLogo ? (
              <code>
                品牌标识 {plan.renderProfile.brandLogo.assetCode} · {plan.renderProfile.brandLogo.checksumSha256.slice(0, 12)}
              </code>
            ) : null}
          </div>
        ) : null}
        {plan.errorMessage ? (
          <InlineNotice tone="danger" title="渲染任务失败">
            {plan.errorMessage}
          </InlineNotice>
        ) : (
          <InlineNotice tone="info" title="已固定内容项目输入">
            剧本与镜头来自内容项目；
            {hasFrozenMaterialEvidence
              ? "当前素材输入已经冻结，等待本地渲染 Worker 执行。"
              : "当前视觉源为已验证的基线素材，等待本地渲染 Worker 执行。"}
          </InlineNotice>
        )}
      </section>
      <FixedInputTrace plan={plan} />
      {videoUrl || posterUrl || contactSheetUrl ? (
        <section className="wb-section">
          <SectionHeader kicker="RENDER PREVIEW" title="成片预览" />
          <div className="video-render-preview-grid">
            {videoUrl ? (
              <video
                className="video-render-preview"
                controls
                playsInline
                src={videoUrl}
              />
            ) : null}
            {posterUrl ? (
              <figure className="video-poster-preview">
                <img src={posterUrl} alt="成片海报" />
                <figcaption>已渲染海报帧</figcaption>
              </figure>
            ) : null}
            {contactSheetUrl ? (
              <figure className="video-poster-preview">
                <img src={contactSheetUrl} alt="成片镜头联系表" />
                <figcaption>等间隔镜头联系表</figcaption>
              </figure>
            ) : null}
          </div>
        </section>
      ) : null}
      <WorkflowPanel plan={plan} />
      <TimelineEditor plan={plan} />
      {plan.jobStatus !== "queued" ? (
        <section className="wb-section">
          <SectionHeader kicker="EDITABLE BRANCH" title="继续剪辑" />
          <div className="video-branch-form">
            <label className="wb-field">
              <span>分支名称</span>
              <input
                className="wb-input"
                value={branchTitle}
                placeholder={`${plan.title} - 分支`}
                onChange={(event) => setBranchTitle(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="wb-button wb-button-primary"
              disabled={branch.isPending}
              onClick={() => branch.mutate()}
            >
              <GitFork size={15} aria-hidden="true" />
              创建可编辑分支
            </button>
          </div>
          {branch.error ? (
            <InlineNotice tone="danger" title="分支未创建">
              {text(branch.error)}
            </InlineNotice>
          ) : null}
        </section>
      ) : null}
      <QualityPanel plan={plan} />
      <section className="wb-section">
        <SectionHeader
          kicker="ARTIFACTS"
          title="成片与产物"
          actions={
            plan.jobStatus === "failed" ? (
              <button
                type="button"
                className="wb-button"
                disabled={retry.isPending}
                onClick={() => retry.mutate()}
              >
                <RefreshCw size={14} aria-hidden="true" />
                重新入队
              </button>
            ) : undefined
          }
        />
        {plan.artifacts.length ? (
          <div className="video-artifacts">
            {plan.artifacts.map((artifact) => (
              <div key={artifact.artifact_key}>
                <a className="wb-button" href={artifact.download_url}>
                  <Download size={14} aria-hidden="true" />
                  {artifact.artifact_key}
                </a>
                <small>
                  {artifact.stage_name ? stageLabel(artifact.stage_name) : "--"}{" "}
                  · {artifact.mime_type ?? "--"} · {bytes(artifact.file_size)}
                  {artifact.checksum_sha256
                    ? ` · ${artifact.checksum_sha256.slice(0, 12)}`
                    : ""}
                </small>
              </div>
            ))}
          </div>
        ) : (
          <EmptyBlock
            icon={Film}
            title="尚无渲染产物"
            detail="Worker 完成后会在此提供视频、海报、字幕和质量报告。"
          />
        )}
      </section>
      {retry.error ? (
        <InlineNotice tone="danger" title="重新入队失败">
          {text(retry.error)}
        </InlineNotice>
      ) : null}
    </div>
  );
}

export function VideoProductionPage() {
  const queryClient = useQueryClient();
  const [sourceKind, setSourceKind] = useState<"project" | "live_room">(
    "project",
  );
  const [projectCode, setProjectCode] = useState("");
  const [liveRoomPlanCode, setLiveRoomPlanCode] = useState("");
  const [duration, setDuration] = useState(55);
  const [visualAssetCodes, setVisualAssetCodes] = useState<string[]>([]);
  const [visualGroupCodes, setVisualGroupCodes] = useState<string[]>([]);
  const [visualMaterialPackCodes, setVisualMaterialPackCodes] = useState<
    string[]
  >([]);
  const [backgroundMusicAssetCode, setBackgroundMusicAssetCode] = useState("");
  const [backgroundMusicGainDb, setBackgroundMusicGainDb] = useState(-18);
  const [soundEffectAssetCode, setSoundEffectAssetCode] = useState("");
  const [soundEffectGainDb, setSoundEffectGainDb] = useState(-9);
  const [brandLogoAssetCode, setBrandLogoAssetCode] = useState("");
  const [productStickerAssetCode, setProductStickerAssetCode] = useState("");
  const [selected, setSelected] = useState("");
  const projects = useQuery({
    queryKey: ["content-projects"],
    queryFn: contentProjectsApi.list,
  });
  const liveRoomPlans = useQuery({
    queryKey: ["functional-live-rooms"],
    queryFn: functionalLiveRoomsApi.list,
  });
  const plans = useQuery({
    queryKey: ["functional-videos"],
    queryFn: functionalVideosApi.list,
  });
  const assets = useQuery({
    queryKey: ["assets"],
    queryFn: assetLibraryApi.listAssets,
  });
  const groups = useQuery({
    queryKey: ["assets", "groups"],
    queryFn: assetLibraryApi.listGroups,
  });
  const packs = useQuery({
    queryKey: ["assets", "packs"],
    queryFn: assetLibraryApi.listPacks,
  });
  useEffect(() => {
    if (!projectCode && projects.data?.[0])
      setProjectCode(projects.data[0].projectCode);
  }, [projectCode, projects.data]);
  useEffect(() => {
    if (!liveRoomPlanCode && liveRoomPlans.data?.[0])
      setLiveRoomPlanCode(liveRoomPlans.data[0].planCode);
  }, [liveRoomPlanCode, liveRoomPlans.data]);
  const active = plans.data?.some((plan) => plan.planCode === selected)
    ? selected
    : (plans.data?.[0]?.planCode ?? "");
  useEffect(() => {
    if (selected !== active) setSelected(active);
  }, [active, selected]);
  const detail = useQuery({
    queryKey: ["functional-video", active],
    queryFn: () => functionalVideosApi.get(active),
    enabled: Boolean(active),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.jobStatus ?? "")
        ? 2500
        : false,
  });
  const sourceReady =
    sourceKind === "project" ? Boolean(projectCode) : Boolean(liveRoomPlanCode);
  const localVideoAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.assetType === "VID" &&
      asset.mediaKind === "video" &&
      asset.executionCapability === "local_only",
  );
  const localVideoAssetCodes = new Set(
    localVideoAssets.map((asset) => asset.assetCode),
  );
  const assetsByCode = new Map(
    (assets.data ?? []).map((asset) => [asset.assetCode, asset]),
  );
  const groupsByCode = new Map(
    (groups.data ?? []).map((group) => [group.groupCode, group]),
  );
  const packsByCode = new Map(
    (packs.data ?? []).map((pack) => [pack.packCode, pack]),
  );
  const selectableGroups = (groups.data ?? []).filter(
    (group) =>
      group.assetCodes.length > 0 &&
      group.assetCodes.every((assetCode) => localVideoAssetCodes.has(assetCode)),
  );
  const selectablePacks = (packs.data ?? []).filter(
    (pack) =>
      pack.status === "published" &&
      pack.resolvedAssetCodes.length > 0 &&
      pack.resolvedAssetCodes.every((assetCode) =>
        localVideoAssetCodes.has(assetCode),
      ),
  );
  const localBackgroundMusicAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.mediaKind === "audio" &&
      asset.executionCapability === "local_only" &&
      asset.materialRoles.includes("background_music"),
  );
  const localSoundEffectAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.mediaKind === "audio" &&
      asset.executionCapability === "local_only" &&
      asset.materialRoles.includes("sound_effect"),
  );
  const localProductStickerAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.mediaKind === "image" &&
      asset.executionCapability === "local_only" &&
      asset.materialRoles.includes("product_display"),
  );
  const localBrandLogoAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.mediaKind === "image" &&
      asset.executionCapability === "local_only" &&
      asset.materialRoles.includes("brand_title"),
  );
  const visualSelectionCodes = (
    assetCodes = visualAssetCodes,
    groupCodes = visualGroupCodes,
    packCodes = visualMaterialPackCodes,
  ) =>
    Array.from(
      new Set([
        ...assetCodes,
        ...groupCodes.flatMap(
          (groupCode) => groupsByCode.get(groupCode)?.assetCodes ?? [],
        ),
        ...packCodes.flatMap(
          (packCode) => packsByCode.get(packCode)?.resolvedAssetCodes ?? [],
        ),
      ]),
    );
  const selectedVisualSourceCodes = visualSelectionCodes();
  const selectedVisualPreviewAssets = selectedVisualSourceCodes.flatMap(
    (assetCode) => {
      const asset = assetsByCode.get(assetCode);
      return asset?.mediaKind === "video" ? [asset] : [];
    },
  );
  const selectedBrandLogo = assetsByCode.get(brandLogoAssetCode);
  const selectedProductSticker = assetsByCode.get(productStickerAssetCode);
  const selectedBackgroundMusic = assetsByCode.get(backgroundMusicAssetCode);
  const selectedSoundEffect = assetsByCode.get(soundEffectAssetCode);
  const toggleVisualAsset = (assetCode: string) =>
    setVisualAssetCodes((current) =>
      current.includes(assetCode)
        ? current.filter((code) => code !== assetCode)
        : current.length < 6
          ? [...current, assetCode]
          : current,
    );
  const toggleVisualGroup = (groupCode: string) =>
    setVisualGroupCodes((current) =>
      current.includes(groupCode)
        ? current.filter((code) => code !== groupCode)
        : [...current, groupCode],
    );
  const toggleVisualMaterialPack = (packCode: string) =>
    setVisualMaterialPackCodes((current) =>
      current.includes(packCode)
        ? current.filter((code) => code !== packCode)
        : [...current, packCode],
    );
  const create = useMutation({
    mutationFn: () =>
      functionalVideosApi.create(
        sourceKind === "project"
          ? {
              project_code: projectCode,
              target_duration_seconds: duration,
              ...(visualAssetCodes.length
                ? { visual_asset_codes: visualAssetCodes }
                : {}),
              ...(visualGroupCodes.length
                ? { visual_group_codes: visualGroupCodes }
                : {}),
              ...(visualMaterialPackCodes.length
                ? { visual_material_pack_codes: visualMaterialPackCodes }
                : {}),
              ...(brandLogoAssetCode
                ? { brand_logo_asset_code: brandLogoAssetCode }
                : {}),
              ...(productStickerAssetCode
                ? { product_sticker_asset_code: productStickerAssetCode }
                : {}),
              ...(backgroundMusicAssetCode
                ? {
                    background_music_asset_code: backgroundMusicAssetCode,
                    background_music_gain_db: backgroundMusicGainDb,
                  }
                : {}),
              ...(soundEffectAssetCode
                ? {
                    sound_effect_asset_code: soundEffectAssetCode,
                    sound_effect_gain_db: soundEffectGainDb,
                  }
                : {}),
            }
          : {
              live_room_plan_code: liveRoomPlanCode,
              target_duration_seconds: duration,
              ...(visualAssetCodes.length
                ? { visual_asset_codes: visualAssetCodes }
                : {}),
              ...(visualGroupCodes.length
                ? { visual_group_codes: visualGroupCodes }
                : {}),
              ...(visualMaterialPackCodes.length
                ? { visual_material_pack_codes: visualMaterialPackCodes }
                : {}),
              ...(brandLogoAssetCode
                ? { brand_logo_asset_code: brandLogoAssetCode }
                : {}),
              ...(productStickerAssetCode
                ? { product_sticker_asset_code: productStickerAssetCode }
                : {}),
              ...(backgroundMusicAssetCode
                ? {
                    background_music_asset_code: backgroundMusicAssetCode,
                    background_music_gain_db: backgroundMusicGainDb,
                  }
                : {}),
              ...(soundEffectAssetCode
                ? {
                    sound_effect_asset_code: soundEffectAssetCode,
                    sound_effect_gain_db: soundEffectGainDb,
                  }
                : {}),
            },
      ),
    onSuccess: (plan) => {
      setSelected(plan.planCode);
      void queryClient.invalidateQueries({ queryKey: ["functional-videos"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (sourceReady) create.mutate();
  };
  return (
    <div className="video-plan-layout">
      <aside className="wb-section video-plan-rail">
        <SectionHeader kicker="RENDERED VIDEO" title="成片生产" />
        <form className="video-plan-form" onSubmit={submit}>
          <label className="wb-field">
            <span>内容来源</span>
            <select
              aria-label="内容来源"
              className="wb-input"
              value={sourceKind}
              onChange={(event) =>
                setSourceKind(event.target.value as "project" | "live_room")
              }
            >
              <option value="project">内容项目</option>
              <option value="live_room">直播间计划</option>
            </select>
          </label>
          {sourceKind === "project" ? (
            <label className="wb-field">
              <span>内容项目</span>
              <select
                className="wb-input"
                value={projectCode}
                onChange={(event) => setProjectCode(event.target.value)}
              >
                {projects.data?.map((project) => (
                  <option key={project.projectCode} value={project.projectCode}>
                    {project.title}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="wb-field">
              <span>直播间计划</span>
              <select
                aria-label="直播间计划"
                className="wb-input"
                value={liveRoomPlanCode}
                onChange={(event) => setLiveRoomPlanCode(event.target.value)}
              >
                {liveRoomPlans.data?.map((plan) => (
                  <option key={plan.planCode} value={plan.planCode}>
                    {plan.expectedTitle} · {plan.planCode}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="wb-field">
            <span>目标时长（秒）</span>
            <input
              className="wb-input"
              type="number"
              min="30"
              max="120"
              value={duration}
              onChange={(event) => setDuration(Number(event.target.value))}
            />
          </label>
          {localVideoAssets.length || selectableGroups.length || selectablePacks.length ? (
            <fieldset className="video-visual-assets">
              <legend>视觉素材（{selectedVisualSourceCodes.length}/6）</legend>
              {localVideoAssets.map((asset) => (
                <div className="video-visual-option" key={asset.assetCode}>
                  <video
                    aria-label={`预览 ${asset.title}`}
                    muted
                    playsInline
                    preload="metadata"
                    src={assetPreviewUrl(asset.assetCode)}
                  />
                  <label>
                    <input
                      type="checkbox"
                      aria-label={`选择 ${asset.title}`}
                      checked={visualAssetCodes.includes(asset.assetCode)}
                      disabled={
                        !visualAssetCodes.includes(asset.assetCode) &&
                        visualSelectionCodes([
                          ...visualAssetCodes,
                          asset.assetCode,
                        ]).length > 6
                      }
                      onChange={() => toggleVisualAsset(asset.assetCode)}
                    />
                    <span>{asset.title}</span>
                    <code>{asset.assetCode}</code>
                  </label>
                </div>
              ))}
              {selectableGroups.map((group) => (
                <label key={group.groupCode}>
                  <input
                    type="checkbox"
                    aria-label={`选择分组 ${group.title}`}
                    checked={visualGroupCodes.includes(group.groupCode)}
                    disabled={
                      !visualGroupCodes.includes(group.groupCode) &&
                      visualSelectionCodes(
                        visualAssetCodes,
                        [...visualGroupCodes, group.groupCode],
                      ).length > 6
                    }
                    onChange={() => toggleVisualGroup(group.groupCode)}
                  />
                  <span>分组 · {group.title}</span>
                  <code>{group.groupCode} · {group.assetCodes.length} 项</code>
                </label>
              ))}
              {selectablePacks.map((pack) => (
                <label key={pack.packCode}>
                  <input
                    type="checkbox"
                    aria-label={`选择素材包 ${pack.title}`}
                    checked={visualMaterialPackCodes.includes(pack.packCode)}
                    disabled={
                      !visualMaterialPackCodes.includes(pack.packCode) &&
                      visualSelectionCodes(
                        visualAssetCodes,
                        visualGroupCodes,
                        [...visualMaterialPackCodes, pack.packCode],
                      ).length > 6
                    }
                    onChange={() => toggleVisualMaterialPack(pack.packCode)}
                  />
                  <span>素材包 · {pack.title}</span>
                  <code>{pack.packCode} · r{pack.revisionNumber} · {pack.resolvedAssetCodes.length} 项</code>
                </label>
              ))}
            </fieldset>
          ) : null}
          {selectedVisualPreviewAssets.length ? (
            <div className="video-selected-previews">
              {selectedVisualPreviewAssets.map((asset) => (
                <LocalMaterialPreview key={asset.assetCode} asset={asset} />
              ))}
            </div>
          ) : null}
          {localBrandLogoAssets.length ? (
            <>
              <label className="wb-field">
                <span>品牌标识</span>
                <select
                  aria-label="品牌标识"
                  className="wb-input"
                  value={brandLogoAssetCode}
                  onChange={(event) => setBrandLogoAssetCode(event.target.value)}
                >
                  <option value="">使用基线标识</option>
                  {localBrandLogoAssets.map((asset) => (
                    <option key={asset.assetCode} value={asset.assetCode}>
                      {asset.title} · {asset.assetCode}
                    </option>
                  ))}
                </select>
              </label>
              {selectedBrandLogo ? <LocalMaterialPreview asset={selectedBrandLogo} /> : null}
            </>
          ) : null}
          {localProductStickerAssets.length ? (
            <>
              <label className="wb-field">
                <span>商品贴片</span>
                <select
                  aria-label="商品贴片"
                  className="wb-input"
                  value={productStickerAssetCode}
                  onChange={(event) =>
                    setProductStickerAssetCode(event.target.value)
                  }
                >
                  <option value="">使用基线贴片</option>
                  {localProductStickerAssets.map((asset) => (
                    <option key={asset.assetCode} value={asset.assetCode}>
                      {asset.title} · {asset.assetCode}
                    </option>
                  ))}
                </select>
              </label>
              {selectedProductSticker ? <LocalMaterialPreview asset={selectedProductSticker} /> : null}
            </>
          ) : null}
          {localBackgroundMusicAssets.length ? (
            <>
              <label className="wb-field">
                <span>背景音乐</span>
                <select
                  aria-label="背景音乐"
                  className="wb-input"
                  value={backgroundMusicAssetCode}
                  onChange={(event) =>
                    setBackgroundMusicAssetCode(event.target.value)
                  }
                >
                  <option value="">不使用</option>
                  {localBackgroundMusicAssets.map((asset) => (
                    <option key={asset.assetCode} value={asset.assetCode}>
                      {asset.title} · {asset.assetCode}
                    </option>
                  ))}
                </select>
              </label>
              {selectedBackgroundMusic ? (
                <LocalMaterialPreview asset={selectedBackgroundMusic} />
              ) : null}
              <label className="wb-field">
                <span>背景音乐增益 {backgroundMusicGainDb.toFixed(1)} dB</span>
                <input
                  aria-label="背景音乐增益"
                  type="range"
                  min="-36"
                  max="-6"
                  step="0.5"
                  value={backgroundMusicGainDb}
                  disabled={!backgroundMusicAssetCode}
                  onChange={(event) =>
                    setBackgroundMusicGainDb(Number(event.target.value))
                  }
                />
              </label>
            </>
          ) : null}
          {localSoundEffectAssets.length ? (
            <>
              <label className="wb-field">
                <span>音效</span>
                <select
                  aria-label="音效"
                  className="wb-input"
                  value={soundEffectAssetCode}
                  onChange={(event) =>
                    setSoundEffectAssetCode(event.target.value)
                  }
                >
                  <option value="">不使用</option>
                  {localSoundEffectAssets.map((asset) => (
                    <option key={asset.assetCode} value={asset.assetCode}>
                      {asset.title} · {asset.assetCode}
                    </option>
                  ))}
                </select>
              </label>
              {selectedSoundEffect ? (
                <LocalMaterialPreview asset={selectedSoundEffect} />
              ) : null}
              <label className="wb-field">
                <span>音效增益 {soundEffectGainDb.toFixed(1)} dB</span>
                <input
                  aria-label="音效增益"
                  type="range"
                  min="-24"
                  max="6"
                  step="0.5"
                  value={soundEffectGainDb}
                  disabled={!soundEffectAssetCode}
                  onChange={(event) =>
                    setSoundEffectGainDb(Number(event.target.value))
                  }
                />
              </label>
            </>
          ) : null}
          <button
            className="wb-button wb-button-primary"
            disabled={!sourceReady || create.isPending}
          >
            <Send size={15} aria-hidden="true" />
            创建渲染任务
          </button>
          {create.error ? (
            <InlineNotice tone="danger" title="无法创建成片任务">
              {text(create.error)}
            </InlineNotice>
          ) : null}
        </form>
        <div className="video-plan-list">
          {plans.data?.map((plan) => (
            <button
              type="button"
              key={plan.planCode}
              className={plan.planCode === active ? "active" : undefined}
              onClick={() => setSelected(plan.planCode)}
            >
              <span>
                <strong>{plan.title}</strong>
                <code>{plan.planCode}</code>
                <small>
                  {plan.progressPercent}% · {plan.currentStage ?? "queued"}
                </small>
              </span>
              <StatusBadge
                label={jobLabel(plan.jobStatus)}
                tone={jobTone(plan.jobStatus)}
              />
            </button>
          ))}
        </div>
      </aside>
      <main className="video-plan-main">
        {plans.isLoading || projects.isLoading || liveRoomPlans.isLoading ? (
          <LoadingBlock />
        ) : detail.data ? (
          <Detail
            plan={detail.data}
            onBranchCreated={(next) => setSelected(next.planCode)}
          />
        ) : (
          <EmptyBlock
            icon={Film}
            title="创建第一个成片任务"
            detail="内容项目或其直播间计划会被编译为垂直视频时间轴并提交给渲染 Worker。"
          />
        )}
      </main>
    </div>
  );
}
