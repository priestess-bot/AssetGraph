import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronRight,
  FileVideo,
  Library,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Upload,
  Video,
  X,
} from "lucide-react";
import { PageHeader, ProgressSteps } from "../product/components";
import { EmptyBlock, InlineNotice, LoadingBlock, StatusBadge, formatDate, formatDuration } from "../workbench/components";
import { productLabel } from "../workbench/productLanguage";
import { liveResearchApi } from "./api";
import type { CaptureSession, RecordingUploadReceipt, RoomTemplate } from "./types";

function playbackUrl(session?: CaptureSession): string | undefined {
  return session?.playback_url ?? session?.media_chunks?.[0]?.media_url;
}

function RecordingWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState(0);
  const [sourceRoomId, setSourceRoomId] = useState("");
  const [sourceRoomTitle, setSourceRoomTitle] = useState("");
  const [file, setFile] = useState<File>();
  const [uploadProgress, setUploadProgress] = useState(0);
  const [receipt, setReceipt] = useState<RecordingUploadReceipt>();
  const [selectedSegments, setSelectedSegments] = useState<number[]>([]);
  const [editedSegments, setEditedSegments] = useState<Record<number, string>>({});
  const [templateTitle, setTemplateTitle] = useState("");
  const [targetCategory, setTargetCategory] = useState("");
  const session = useQuery({ queryKey: ["live-research", "session", receipt?.session_code], queryFn: () => liveResearchApi.getCaptureSession(receipt!.session_code), enabled: Boolean(receipt), refetchInterval: step === 1 ? 3000 : false });
  const timeline = useQuery({ queryKey: ["live-research", "timeline", receipt?.session_code], queryFn: () => liveResearchApi.getTimeline(receipt!.session_code), enabled: Boolean(receipt) && step >= 1, retry: false });
  const upload = useMutation({
    mutationFn: () => { if (!file) throw new Error("请选择录屏文件"); setUploadProgress(0); return liveResearchApi.uploadRecording({ sourceRoomId: sourceRoomId.trim(), sourceRoomTitle: sourceRoomTitle.trim(), file }, setUploadProgress); },
    onSuccess: (value) => { setReceipt(value); setTemplateTitle(`${value.source_room_title} 内容模板`); setStep(1); void queryClient.invalidateQueries({ queryKey: ["live-research"] }); },
  });
  useEffect(() => {
    const segments = timeline.data?.asr_segments ?? [];
    if (segments.length && !selectedSegments.length) setSelectedSegments(segments.map((_, index) => index));
  }, [selectedSegments.length, timeline.data?.asr_segments]);
  const createTemplate = useMutation({
    mutationFn: () => {
      if (!receipt) throw new Error("录屏尚未上传");
      const segments = timeline.data?.asr_segments ?? [];
      const reviewed = selectedSegments.map((index) => ({ moduleKey: "main", exampleText: (editedSegments[index] ?? segments[index]?.text ?? "").trim(), sourceSessionCode: receipt.session_code, startMs: Math.round((segments[index]?.start_seconds ?? 0) * 1000), endMs: Math.round((segments[index]?.end_seconds ?? 0) * 1000) })).filter((item) => item.exampleText);
      const duration = Math.round((session.data?.duration_seconds ?? receipt.duration_seconds) * 1000);
      return liveResearchApi.createContentStrategyTemplate({ title: templateTitle.trim(), sourceTargetCode: receipt.target_code, sourceSessionCodes: [receipt.session_code], targetCategory: targetCategory.trim() || "通用直播", compatibilityTags: [], modules: [{ moduleKey: "main", title: "主体内容", purpose: "根据已清洗录屏总结直播内容节奏", sourceSessionCode: receipt.session_code, startMs: 0, endMs: duration }], moduleRecipes: [{ moduleKey: "main", guidance: reviewed.map((item) => item.exampleText).join("；").slice(0, 1000) || "围绕直播目标组织主体内容" }], durationPolicy: { targetDurationSeconds: Math.round(duration / 1000) }, productRotationPolicy: {}, interactionPolicy: {}, conversionPolicy: {}, hostStyle: {}, reviewedExamples: reviewed, materialCues: [] });
    },
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }); onClose(); },
  });
  const resetClose = () => { setStep(0); setReceipt(undefined); setFile(undefined); setUploadProgress(0); setSelectedSegments([]); setEditedSegments({}); upload.reset(); createTemplate.reset(); onClose(); };
  const segments = timeline.data?.asr_segments ?? [];
  const canReview = Boolean(session.data?.status === "completed" || timeline.data);
  return <Dialog.Root open={open} onOpenChange={(value) => { if (!value) resetClose(); }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="template-wizard-dialog"><header><div><Dialog.Title>从录屏创建模板</Dialog.Title><Dialog.Description>上传录屏后，检查解析结果、清洗文字并发布为可选内容模板。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header><div className="template-wizard-body"><ProgressSteps current={step} items={["上传录屏", "解析内容", "清洗文字", "审核模板"]} />
    {step === 0 ? <section className="template-upload-step"><div className="template-step-heading"><h2>上传直播录屏</h2><p>平台自动采集不是必需条件，本地 MP4、MOV、MKV 或 WebM 均可。</p></div><div className="template-upload-grid"><label className="wb-field"><span>来源直播间 ID</span><input className="wb-input" value={sourceRoomId} onChange={(event) => setSourceRoomId(event.target.value)} placeholder="例如 893746120" /></label><label className="wb-field"><span>来源直播间名称</span><input className="wb-input" value={sourceRoomTitle} onChange={(event) => setSourceRoomTitle(event.target.value)} placeholder="例如 品牌夏季专场" /></label></div><label className={`template-recording-drop ${file ? "has-file" : ""}`}><input ref={fileRef} type="file" accept="video/mp4,video/quicktime,video/webm,.mkv" onChange={(event) => setFile(event.target.files?.[0])} /><Upload size={28} aria-hidden="true" /><strong>{file?.name ?? "选择录屏文件"}</strong><span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "视频会在本地服务中完成校验、抽帧和解析"}</span></label>{upload.isPending ? <div className="template-upload-progress"><div><i style={{ width: `${uploadProgress}%` }} /></div><span>{uploadProgress < 100 ? `正在上传 ${uploadProgress}%` : "上传完成，正在校验媒体"}</span></div> : null}{upload.error ? <InlineNotice tone="danger" title="录屏没有上传">检查文件格式、直播间信息和服务连接后重试。</InlineNotice> : null}</section> : null}
    {step === 1 ? <section className="template-analysis-step"><div className="template-step-heading"><h2>解析直播内容</h2><p>录屏会分别完成语音、画面文字、关键帧和结构分析，失败步骤可单独重试。</p></div><div className="template-analysis-layout"><div className="template-analysis-video">{playbackUrl(session.data) ? <video controls src={playbackUrl(session.data)} /> : <div><Video size={30} aria-hidden="true" /><span>媒体正在准备</span></div>}</div><div className="template-analysis-status">{[["语音转写", timeline.data?.asr_segments.length], ["画面文字", timeline.data?.visual_segments.filter((item) => item.label.includes("文字")).length], ["场景结构", timeline.data?.visual_segments.length], ["关键画面", timeline.data?.keyframes.length]].map(([label, count]) => <div key={String(label)}><span className={Number(count) > 0 ? "done" : "running"}>{Number(count) > 0 ? <Check size={14} aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}</span><span><strong>{label}</strong><small>{Number(count) > 0 ? `已获得 ${count} 条结果` : "正在处理"}</small></span></div>)}</div></div>{session.error ? <InlineNotice tone="warning" title="解析状态暂时不可用">录屏已保存，可以稍后从录屏列表继续。</InlineNotice> : null}</section> : null}
    {step === 2 ? <section className="template-clean-step"><div className="template-step-heading"><h2>清洗可复用内容</h2><p>取消不应进入模板的内容，并直接修正错字、金额或敏感信息。</p></div><div className="template-clean-layout"><div className="template-clean-video">{playbackUrl(session.data) ? <video controls src={playbackUrl(session.data)} /> : null}</div><div className="template-transcript-list">{segments.length ? segments.map((segment, index) => <article key={`${segment.start_seconds}:${index}`} className={selectedSegments.includes(index) ? "selected" : ""}><label><input type="checkbox" checked={selectedSegments.includes(index)} onChange={() => setSelectedSegments((current) => current.includes(index) ? current.filter((item) => item !== index) : [...current, index])} /><time>{formatDuration(segment.start_seconds)}</time></label><textarea rows={2} value={editedSegments[index] ?? segment.text} onChange={(event) => setEditedSegments((current) => ({ ...current, [index]: event.target.value }))} /></article>) : <EmptyBlock title="尚未获得语音文字" detail="可以返回解析步骤刷新，或稍后从录屏列表继续。" />}</div></div></section> : null}
    {step === 3 ? <section className="template-review-step"><div className="template-step-heading"><h2>确认模板信息</h2><p>外部平面录屏只作为内容策略和近似视觉参考，不会被当作可执行麦兔布局。</p></div><div className="template-review-grid"><label className="wb-field"><span>模板名称</span><input className="wb-input" value={templateTitle} onChange={(event) => setTemplateTitle(event.target.value)} /></label><label className="wb-field"><span>适用内容类型</span><input className="wb-input" value={targetCategory} onChange={(event) => setTargetCategory(event.target.value)} placeholder="例如：家居好物、食品品鉴" /></label></div><div className="template-review-summary"><div><span>来源直播间</span><strong>{receipt?.source_room_title}</strong></div><div><span>录屏时长</span><strong>{formatDuration(receipt?.duration_seconds ?? 0)}</strong></div><div><span>纳入文字</span><strong>{selectedSegments.length} 段</strong></div><div><span>布局使用方式</span><strong>近似参考</strong></div><div><span>构建方式</span><strong>不可直接执行</strong></div></div><InlineNotice tone="info" title="发布后可以做什么">项目可以引用该模板的内容节奏、节目结构和已清洗示例；直播间布局仍由素材约束和麦兔画布重新构建。</InlineNotice>{createTemplate.error ? <InlineNotice tone="danger" title="模板没有创建">请确认模板名称和录屏解析结果后重试。</InlineNotice> : null}</section> : null}
  </div><footer><button type="button" className="wb-button" onClick={step ? () => setStep((current) => current - 1) : resetClose}>{step ? "上一步" : "取消"}</button><div>{step === 0 ? <button className="wb-button wb-button-primary" type="button" disabled={!file || !sourceRoomId.trim() || !sourceRoomTitle.trim() || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? "正在上传" : "上传并解析"}</button> : step === 1 ? <button className="wb-button wb-button-primary" type="button" disabled={!canReview} onClick={() => setStep(2)}>清洗解析结果<ChevronRight size={15} aria-hidden="true" /></button> : step === 2 ? <button className="wb-button wb-button-primary" type="button" onClick={() => setStep(3)}>审核模板<ChevronRight size={15} aria-hidden="true" /></button> : <button className="wb-button wb-button-primary" type="button" disabled={!templateTitle.trim() || createTemplate.isPending} onClick={() => createTemplate.mutate()}>{createTemplate.isPending ? "正在创建" : "创建模板草稿"}</button>}</div></footer></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function TemplateInspector({ template, onClose }: { template: RoomTemplate; onClose: () => void }) {
  const queryClient = useQueryClient();
  const publish = useMutation({ mutationFn: () => liveResearchApi.publishTemplate(template.template_code, template.latest_revision), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }) });
  const archive = useMutation({ mutationFn: () => liveResearchApi.archiveTemplate(template.template_code), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }); onClose(); } });
  return <aside className="template-inspector"><header><div><h2>{template.title}</h2><p>最近更新 {formatDate(template.updated_at)}</p></div><button className="product-icon-button" type="button" title="关闭详情" onClick={onClose}><X size={18} aria-hidden="true" /></button></header><div className="template-inspector-hero">{template.source_playback_url ? <video controls preload="metadata" src={template.source_playback_url} /> : <div><Library size={30} aria-hidden="true" /><span>内容策略模板</span></div>}</div><div className="template-readiness"><div><span>内容</span><StatusBadge label={template.contentReadiness} tone={template.contentReadiness === "ready" ? "success" : "warning"} /></div><div><span>布局</span><StatusBadge label={template.layout_fidelity} tone="info" /></div><div><span>构建</span><StatusBadge label={template.buildability} tone={template.buildability === "executable" ? "success" : "neutral"} /></div></div><div className="template-inspector-body"><section><h3>内容结构</h3>{template.contentStrategy.programOutline.length ? template.contentStrategy.programOutline.map((item, index) => <article key={`${item.moduleKey}:${index}`}><b>{index + 1}</b><span><strong>{item.title}</strong><p>{item.purpose || "未补充结构说明"}</p><small>{formatDuration(item.startMs / 1000)} - {formatDuration(item.endMs / 1000)}</small></span></article>) : template.scenes.length ? template.scenes.map((scene, index) => <article key={scene.scene_code ?? index}><b>{index + 1}</b><span><strong>{scene.title}</strong><p>{scene.purpose || "场景结构参考"}</p><small>{formatDuration(scene.start_seconds)} - {formatDuration(scene.end_seconds)}</small></span></article>) : <EmptyBlock title="尚未整理内容结构" />}</section><section><h3>使用边界</h3><p>{template.buildability === "executable" ? "该模板包含经过验证的布局，可进入构建流程。" : "该模板来自外部平面录屏，只能参考内容节奏和近似视觉，不能直接写入麦兔图层。"}</p></section>{publish.error || archive.error ? <InlineNotice tone="danger" title="操作没有完成">刷新模板状态后重试。</InlineNotice> : null}</div><footer>{template.status !== "published" && template.status !== "archived" ? <button className="wb-button wb-button-primary" type="button" disabled={publish.isPending} onClick={() => publish.mutate()}>{publish.isPending ? "正在发布" : "发布模板"}</button> : null}{template.status !== "archived" ? <button className="wb-button" type="button" disabled={archive.isPending} onClick={() => archive.mutate()}>停用模板</button> : null}</footer></aside>;
}

function TemplateLibrary({ templates, onSelect }: { templates: RoomTemplate[]; onSelect: (template: RoomTemplate) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const filtered = templates.filter((template) => (status === "all" || template.status === status) && template.title.toLowerCase().includes(query.toLowerCase()));
  return <><div className="template-library-toolbar"><label><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索模板名称" aria-label="搜索直播模板" /></label><div>{[["all", "全部"], ["published", "已发布"], ["draft", "草稿"], ["archived", "已停用"]].map(([value, label]) => <button type="button" key={value} className={status === value ? "active" : undefined} onClick={() => setStatus(value)}>{label}</button>)}</div><span>{filtered.length} 个模板</span></div>{filtered.length ? <div className="template-card-grid">{filtered.map((template) => <button type="button" key={template.template_code} onClick={() => onSelect(template)}><div className="template-card-preview">{template.source_playback_url ? <video muted preload="metadata" src={template.source_playback_url} /> : <div><Sparkles size={24} aria-hidden="true" /></div>}<StatusBadge label={template.status} tone={template.status === "published" ? "success" : "neutral"} /></div><div className="template-card-copy"><strong>{template.title}</strong><small>{template.templateKind === "content_strategy" ? "内容策略" : "视觉布局参考"}</small><dl><div><dt>内容</dt><dd>{productLabel(template.contentReadiness)}</dd></div><div><dt>布局</dt><dd>{productLabel(template.layout_fidelity)}</dd></div><div><dt>构建</dt><dd>{productLabel(template.buildability)}</dd></div></dl></div></button>)}</div> : <EmptyBlock icon={Library} title="没有匹配的模板" detail="调整筛选条件，或从直播录屏创建新模板。" />}</>;
}

function RecordingList({ sessions }: { sessions: CaptureSession[] }) {
  const [selected, setSelected] = useState(sessions[0]?.session_code ?? "");
  useEffect(() => { if (!selected && sessions[0]) setSelected(sessions[0].session_code); }, [selected, sessions]);
  const current = sessions.find((item) => item.session_code === selected);
  const timeline = useQuery({ queryKey: ["live-research", "timeline", selected], queryFn: () => liveResearchApi.getTimeline(selected), enabled: Boolean(selected), retry: false });
  return <div className="recording-workspace"><aside>{sessions.length ? sessions.map((session) => <button type="button" key={session.session_code} className={session.session_code === selected ? "active" : undefined} onClick={() => setSelected(session.session_code)}><span className="recording-thumb">{session.poster_url ? <img src={session.poster_url} alt="" /> : <FileVideo size={20} aria-hidden="true" />}</span><span><strong>{session.title}</strong><small>{formatDuration(session.duration_seconds)} · {formatDate(session.started_at)}</small></span><StatusBadge label={session.status} tone={session.status === "completed" ? "success" : "warning"} /></button>) : <EmptyBlock icon={FileVideo} title="还没有录屏" />}</aside><section>{current ? <><header><div><h2>{current.title}</h2><p>{formatDuration(current.duration_seconds)} · {productLabel(current.status)}</p></div></header><div className="recording-review-layout"><div className="recording-player">{playbackUrl(current) ? <video controls src={playbackUrl(current)} /> : <EmptyBlock icon={Video} title="录屏媒体正在准备" />}</div><div className="recording-transcript"><h3>语音与画面内容</h3>{timeline.isLoading ? <LoadingBlock /> : timeline.data?.asr_segments.length ? timeline.data.asr_segments.map((segment, index) => <p key={`${segment.start_seconds}:${index}`}><time>{formatDuration(segment.start_seconds)}</time><span>{segment.text}</span></p>) : <EmptyBlock title="尚无语音文字" detail="解析完成后会在这里按时间展示。" />}</div></div></> : <EmptyBlock title="选择一份录屏查看" />}</section></div>;
}

export function TemplateLibraryProductPage({ search }: { search: string }) {
  const params = new URLSearchParams(search);
  const [tab, setTab] = useState<"library" | "recordings">(params.get("view") === "sessions" ? "recordings" : "library");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [selected, setSelected] = useState<RoomTemplate>();
  const templates = useQuery({ queryKey: ["live-research", "templates"], queryFn: liveResearchApi.listTemplates });
  const sessions = useQuery({ queryKey: ["live-research", "sessions"], queryFn: liveResearchApi.listCaptureSessions, enabled: tab === "recordings" });
  const requestedTemplate = params.get("template");
  useEffect(() => { if (requestedTemplate && templates.data) setSelected(templates.data.find((item) => item.template_code === requestedTemplate)); }, [requestedTemplate, templates.data]);
  return <div className={`template-product-page ${selected ? "has-inspector" : ""}`}><RecordingWizard open={wizardOpen} onClose={() => setWizardOpen(false)} /><PageHeader eyebrow="内容基础" title="直播模板" description="从直播录屏提取可复用的内容策略，并明确区分视觉参考和可执行布局。" actions={<button className="wb-button wb-button-primary" type="button" onClick={() => setWizardOpen(true)}><Plus size={16} aria-hidden="true" />从录屏创建模板</button>} /><nav className="template-product-tabs"><button type="button" className={tab === "library" ? "active" : undefined} onClick={() => setTab("library")}><Library size={15} aria-hidden="true" />模板库</button><button type="button" className={tab === "recordings" ? "active" : undefined} onClick={() => setTab("recordings")}><FileVideo size={15} aria-hidden="true" />录屏与解析</button></nav>{tab === "library" ? templates.isLoading ? <LoadingBlock label="正在读取模板库" /> : <TemplateLibrary templates={templates.data ?? []} onSelect={setSelected} /> : sessions.isLoading ? <LoadingBlock label="正在读取录屏" /> : <RecordingList sessions={sessions.data ?? []} />}{selected ? <TemplateInspector template={selected} onClose={() => setSelected(undefined)} /> : null}</div>;
}
