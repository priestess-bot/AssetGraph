import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  AlertTriangle,
  FileImage,
  Film,
  Grid2X2,
  ImagePlus,
  Layers3,
  List,
  PackageOpen,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Upload,
  Sparkles,
  X,
} from "lucide-react";
import { PageHeader } from "../product/components";
import { EmptyBlock, InlineNotice, LoadingBlock, StatusBadge } from "../workbench/components";
import { productCopy, productLabel, productTitle } from "../workbench/productLanguage";
import {
  assetLibraryApi,
  type ExecutionCapability,
  type LibraryAsset,
  type MaterialRole,
  type RightsStatus,
  type MaterialPack,
  type AssetGap,
} from "./api";
import { maituApi } from "../maitu/api";
import type { AnalysisConflict } from "../maitu/types";
import {
  assetMatchesQuery,
  DEFAULT_GEOMETRY,
  geometryFromRules,
  MATERIAL_ROLES,
  rulesFromGeometry,
  setRelativeRuleHardness,
  setTablePlacement,
  type Geometry,
  type RelativeRoleRule,
} from "./libraryModel";

const MEDIA_KINDS = ["image", "video", "audio", "document", "font_file", "other"];
type EditableCapability = Exclude<ExecutionCapability, "maitu_bound">;
const CAPABILITIES: EditableCapability[] = ["local_only", "reference_only", "unavailable", "unclassified"];

function toggle<T>(items: T[], value: T): T[] {
  return items.includes(value) ? items.filter((item) => item !== value) : [...items, value];
}

function kindFromFile(file: File): { assetType: string; mediaKind: string } {
  if (file.type.startsWith("image/")) return { assetType: "IMG", mediaKind: "image" };
  if (file.type.startsWith("video/")) return { assetType: "VID", mediaKind: "video" };
  if (file.type.startsWith("audio/")) return { assetType: "AUD", mediaKind: "audio" };
  return { assetType: "DOC", mediaKind: "document" };
}

function AssetImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File>();
  const [title, setTitle] = useState("");
  const [roles, setRoles] = useState<MaterialRole[]>([]);
  const [capability, setCapability] = useState<EditableCapability>("local_only");
  const importAsset = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("请选择素材文件");
      const kind = kindFromFile(file);
      const created = await assetLibraryApi.createAsset({ title: title.trim() || file.name.replace(/\.[^.]+$/, ""), original_filename: file.name, asset_type: kind.assetType, media_kind: kind.mediaKind, material_roles: roles, execution_capability: capability, file_ext: file.name.split(".").pop(), mime_type: file.type, file_size: file.size, source_system: "local_upload" });
      await assetLibraryApi.uploadFile(created.assetCode, file);
      return created;
    },
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["assets"] }); onClose(); setFile(undefined); setTitle(""); setRoles([]); },
  });
  return <Dialog.Root open={open} onOpenChange={(value) => { if (!value) onClose(); }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="asset-import-dialog"><header><div><Dialog.Title>导入素材</Dialog.Title><Dialog.Description>选择文件并明确它在直播间或成片中的用途。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header><div className="asset-import-body"><label className={`asset-dropzone ${file ? "has-file" : ""}`}><input type="file" accept="image/*,video/*,audio/*,.pdf,.txt" onChange={(event) => { const next = event.target.files?.[0]; setFile(next); if (next && !title) setTitle(next.name.replace(/\.[^.]+$/, "")); }} /><Upload size={24} aria-hidden="true" /><strong>{file ? file.name : "选择图片、视频、音频或文档"}</strong><span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "单次导入一份素材，上传后可继续批量操作"}</span></label><label className="wb-field"><span>素材名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="用于搜索和选择的名称" /></label><div className="asset-import-options"><div><span>素材用途</span><div>{MATERIAL_ROLES.map((role) => <button type="button" key={role} className={roles.includes(role) ? "selected" : undefined} onClick={() => setRoles((current) => toggle(current, role))}>{roles.includes(role) ? <Check size={12} aria-hidden="true" /> : null}{productLabel(role, "其他用途")}</button>)}</div></div><label className="wb-field"><span>可用于</span><select className="wb-input" value={capability} onChange={(event) => setCapability(event.target.value as EditableCapability)}>{CAPABILITIES.map((value) => <option key={value} value={value}>{productLabel(value)}</option>)}</select><small>麦兔可用状态会在库存核对成功后自动获得</small></label></div>{importAsset.error ? <InlineNotice tone="danger" title="素材没有导入">请选择有效文件并确认服务连接。</InlineNotice> : null}</div><footer><button className="wb-button" type="button" onClick={onClose}>取消</button><button className="wb-button wb-button-primary" type="button" disabled={!file || !title.trim() || importAsset.isPending} onClick={() => importAsset.mutate()}>{importAsset.isPending ? "正在上传" : "导入素材"}</button></footer></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function ConstraintEditor({ asset, onSaved }: { asset: LibraryAsset; onSaved: () => void }) {
  const profile = useQuery({ queryKey: ["assets", asset.assetCode, "constraints"], queryFn: () => assetLibraryApi.getConstraintProfile(asset.assetCode), retry: false });
  const [geometry, setGeometry] = useState<Geometry>(() => ({ ...DEFAULT_GEOMETRY, aboveRoles: [], belowRoles: [], sourceRules: [] }));
  useEffect(() => { setGeometry({ ...DEFAULT_GEOMETRY, aboveRoles: [], belowRoles: [], sourceRules: [] }); }, [asset.assetCode]);
  useEffect(() => { if (profile.data) setGeometry(geometryFromRules(profile.data.constraints)); }, [profile.data]);
  const save = useMutation({ mutationFn: () => assetLibraryApi.writeConstraintProfile(asset.assetCode, rulesFromGeometry(geometry)), onSuccess: () => { void profile.refetch(); onSaved(); } });
  const number = (key: "x" | "y" | "width" | "height", label: string) => <label><span>{label}</span><input type="number" min={0} max={1} step={0.01} value={geometry[key]} onChange={(event) => setGeometry((current) => ({ ...current, [key]: Math.min(1, Math.max(0, Number(event.target.value))) }))} /></label>;
  const toggleRelativeRole = (direction: "above" | "below", role: MaterialRole) => setGeometry((current) => {
    const currentKey = direction === "above" ? "aboveRoles" : "belowRoles";
    const oppositeKey = direction === "above" ? "belowRoles" : "aboveRoles";
    const selected = current[currentKey].some((item) => item.role === role);
    if (direction === "above" && role === "background" && current.onTable && selected) return current;
    return {
      ...current,
      [currentKey]: selected
        ? current[currentKey].filter((item) => item.role !== role)
        : [...current[currentKey], { role, hard: true }],
      [oppositeKey]: current[oppositeKey].filter((item) => item.role !== role),
      layer: direction === "above" && current.layer === "bottom" || direction === "below" && current.layer === "top" ? "normal" : current.layer,
      onTable: direction === "below" && role === "background" ? false : current.onTable,
      tableInjectedBackground: role === "background" ? false : current.tableInjectedBackground,
    };
  });
  const toggleHardness = (direction: "above" | "below", item: RelativeRoleRule) => {
    setGeometry((current) => setRelativeRuleHardness(current, direction, item.role, !item.hard));
  };
  const relativeRoles = MATERIAL_ROLES.filter((role) => !asset.materialRoles.includes(role));
  const relativeRuleGroup = (direction: "above" | "below", label: string) => {
    const values = direction === "above" ? geometry.aboveRoles : geometry.belowRoles;
    return <section className="asset-relative-rule-group"><span>{label}</span><div>{relativeRoles.map((role) => {
      const item = values.find((value) => value.role === role);
      const lockedByTable = direction === "above" && role === "background" && geometry.onTable;
      const effectiveHard = lockedByTable || item?.hard === true;
      return <div className={`asset-relative-role-control ${item ? "selected" : ""}`} key={`${direction}-${role}`}><button className="asset-relative-role-toggle" type="button" aria-pressed={Boolean(item)} disabled={lockedByTable} title={lockedByTable ? "桌面摆放已要求位于背景上方" : undefined} onClick={() => toggleRelativeRole(direction, role)}>{item ? <Check size={11} aria-hidden="true" /> : null}{productLabel(role, "其他用途")}</button>{item ? <button className={`asset-relative-hardness-toggle ${effectiveHard ? "is-hard" : "is-soft"}`} type="button" disabled={lockedByTable} aria-label={`${productLabel(role, "其他用途")}关系强度：${effectiveHard ? "必须" : "尽量"}${lockedByTable ? "，由桌面摆放约束固定" : `，点击改为${effectiveHard ? "尽量" : "必须"}`}`} title={lockedByTable ? "桌面摆放必须位于背景上方" : `当前为“${effectiveHard ? "必须" : "尽量"}”，点击切换`} onClick={() => toggleHardness(direction, item)}>{effectiveHard ? "必须" : "尽量"}</button> : null}</div>;
    })}</div></section>;
  };
  const layerOptions: Array<{ value: Geometry["layer"]; label: string }> = [{ value: "normal", label: "自动" }, { value: "top", label: "始终置顶" }, { value: "bottom", label: "始终置底" }];
  if (profile.isLoading) return <LoadingBlock label="正在读取布局约束" />;
  return <div className="asset-constraint-product"><div className="asset-placement-preview"><div className="asset-phone-frame"><span>直播画布</span><i style={{ left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, width: `${geometry.width * 100}%`, height: `${geometry.height * 100}%` }}>{productTitle(asset.title, "素材")}</i><b>桌面区域</b></div></div><div className="asset-constraint-controls"><h3>位置与大小</h3><div className="asset-geometry-fields">{number("x", "左侧")}{number("y", "顶部")}{number("width", "宽度")}{number("height", "高度")}</div><label className="asset-switch"><input type="checkbox" checked={geometry.preserveAspect} onChange={(event) => setGeometry((current) => ({ ...current, preserveAspect: event.target.checked }))} /><span />保持原始宽高比</label><h3>图层关系</h3><div className="asset-segmented">{layerOptions.map(({ value, label }) => <button key={value} type="button" className={geometry.layer === value ? "active" : undefined} onClick={() => setGeometry((current) => ({ ...current, layer: value, forbidTop: value === "top" ? false : current.forbidTop, aboveRoles: value === "bottom" ? [] : current.aboveRoles, belowRoles: value === "top" ? [] : current.belowRoles, onTable: value === "bottom" ? false : current.onTable, tableInjectedBackground: value === "bottom" ? false : current.tableInjectedBackground }))}>{label}</button>)}</div><label className="asset-switch"><input type="checkbox" checked={geometry.forbidTop} disabled={geometry.layer === "top"} onChange={(event) => setGeometry((current) => ({ ...current, forbidTop: event.target.checked }))} /><span />禁止成为最上层图层</label><div className="asset-relative-layer-rules">{relativeRuleGroup("above", "位于这些素材上方")}{relativeRuleGroup("below", "位于这些素材下方")}</div><label className="asset-switch"><input type="checkbox" checked={geometry.onTable} onChange={(event) => setGeometry((current) => setTablePlacement(current, event.target.checked))} /><span />商品需摆放在背景桌面上，并位于背景上方</label><button className="wb-button wb-button-primary" type="button" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "正在保存" : "保存约束"}</button>{save.error ? <InlineNotice tone="danger" title="约束没有保存">当前图层规则互相冲突，或位置和尺寸超出画布。</InlineNotice> : null}</div></div>;
}

function AssetInspector({ asset, onClose }: { asset: LibraryAsset; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [section, setSection] = useState<"info" | "usage" | "constraints">("info");
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [mediaKind, setMediaKind] = useState(asset.mediaKind ?? "");
  const [roles, setRoles] = useState(asset.materialRoles as MaterialRole[]);
  const [capability, setCapability] = useState<EditableCapability>(asset.executionCapability === "maitu_bound" ? "local_only" : asset.executionCapability);
  const [rights, setRights] = useState<RightsStatus>(asset.rightsStatus);
  const [rightsNote, setRightsNote] = useState(asset.rightsNote ?? "");
  useEffect(() => { setMediaKind(asset.mediaKind ?? ""); setRoles(asset.materialRoles as MaterialRole[]); setCapability(asset.executionCapability === "maitu_bound" ? "local_only" : asset.executionCapability); setRights(asset.rightsStatus); setRightsNote(asset.rightsNote ?? ""); }, [asset]);
  const refresh = async () => queryClient.invalidateQueries({ queryKey: ["assets"] });
  const classification = useMutation({ mutationFn: () => assetLibraryApi.updateClassification(asset.assetCode, { media_kind: mediaKind || undefined, material_roles: roles, ...(asset.executionCapability === "maitu_bound" ? {} : { execution_capability: capability }), classification_review_status: "confirmed", classification_confidence: 1, classification_evidence: { source: "manual_operator", previous_review_status: asset.classificationReviewStatus } }), onSuccess: refresh });
  const usage = useMutation({ mutationFn: () => assetLibraryApi.updateRights(asset.assetCode, { status: rights, note: rightsNote }), onSuccess: refresh });
  const isVideo = asset.mediaKind === "video" || asset.assetType === "VID";
  const previewUrl = assetLibraryApi.previewUrl(asset.assetCode);
  const isImage = !isVideo && (asset.mediaKind === "image" || asset.assetType === "IMG");
  const explanation = typeof asset.classificationEvidence.explanation === "string" ? asset.classificationEvidence.explanation : undefined;
  return <><aside className="asset-product-inspector"><header><div><h2>{asset.title}</h2><p>{productLabel(asset.mediaKind ?? asset.assetType, "素材")} · {productLabel(asset.executionCapability)}</p></div><button className="product-icon-button" type="button" title="关闭详情" onClick={onClose}><X size={18} aria-hidden="true" /></button></header><div className={`asset-inspector-preview ${isImage ? "is-clickable" : ""}`}>{isVideo ? <video controls preload="metadata" playsInline src={previewUrl} /> : isImage ? <button type="button" aria-label="放大查看素材" title="点击放大查看" onClick={() => setLightboxOpen(true)}><img src={previewUrl} alt={asset.title} /><span>点击放大查看</span></button> : <img src={previewUrl} alt={asset.title} />}</div><nav>{[["info", "基本信息"], ["usage", "使用状态"], ["constraints", "布局约束"]].map(([value, label]) => <button type="button" key={value} className={section === value ? "active" : undefined} onClick={() => setSection(value as typeof section)}>{label}</button>)}</nav><div className="asset-inspector-content">{section === "info" ? <><InlineNotice tone={asset.classificationReviewStatus === "review_required" ? "warning" : "neutral"} title={productLabel(asset.classificationReviewStatus)}>{explanation ?? (asset.classificationReviewStatus === "review_required" ? "名称和画面不足以可靠判断，请确认用途和图层规则。" : "用途来自素材信息推断，保存后将标记为人工确认。")}</InlineNotice><div className="asset-inspector-fields"><label className="wb-field"><span>媒体类型</span><select className="wb-input" value={mediaKind} onChange={(event) => setMediaKind(event.target.value)}><option value="">待确认</option>{MEDIA_KINDS.map((value) => <option key={value} value={value}>{productLabel(value)}</option>)}</select></label><label className="wb-field"><span>可用于</span>{asset.executionCapability === "maitu_bound" ? <div className="asset-derived-capability"><strong>可用于麦兔</strong><small>已通过麦兔素材库存核对</small></div> : <select className="wb-input" value={capability} onChange={(event) => setCapability(event.target.value as EditableCapability)}>{CAPABILITIES.map((value) => <option key={value} value={value}>{productLabel(value)}</option>)}</select>}</label></div><div className="asset-role-picker"><span>素材用途</span><div>{MATERIAL_ROLES.map((role) => <button type="button" key={role} className={roles.includes(role) ? "selected" : undefined} onClick={() => setRoles((current) => toggle(current, role))}>{roles.includes(role) ? <Check size={12} aria-hidden="true" /> : null}{productLabel(role, "其他用途")}</button>)}</div></div><button className="wb-button wb-button-primary" type="button" disabled={classification.isPending} onClick={() => classification.mutate()}>{asset.classificationReviewStatus === "review_required" ? "确认并保存" : "保存基本信息"}</button>{classification.error ? <InlineNotice tone="danger" title="基本信息没有保存">请检查素材用途和可用范围。</InlineNotice> : null}</> : section === "usage" ? <><InlineNotice tone={rights === "approved" ? "success" : "warning"} title={rights === "approved" ? "这份素材可以用于生成" : "这份素材暂时不会进入可执行方案"} /><label className="wb-field"><span>使用状态</span><select className="wb-input" value={rights} onChange={(event) => setRights(event.target.value as RightsStatus)}>{(["pending", "approved", "restricted", "revoked"] as RightsStatus[]).map((value) => <option key={value} value={value}>{productLabel(value)}</option>)}</select></label><label className="wb-field"><span>使用依据或限制</span><textarea rows={4} value={rightsNote} onChange={(event) => setRightsNote(event.target.value)} placeholder="例如：品牌自有素材，仅用于当前品牌项目" /></label><button className="wb-button wb-button-primary" type="button" disabled={usage.isPending || rightsNote.trim().length < 3} onClick={() => usage.mutate()}>保存使用状态</button></> : <ConstraintEditor asset={asset} onSaved={() => void refresh()} />}</div></aside>{isImage ? <Dialog.Root open={lightboxOpen} onOpenChange={setLightboxOpen}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay asset-media-lightbox-overlay" /><Dialog.Content className="asset-media-lightbox"><Dialog.Title className="asset-media-lightbox-title">{asset.title}</Dialog.Title><Dialog.Description className="asset-media-lightbox-description">素材放大预览</Dialog.Description><img src={previewUrl} alt={asset.title} /><Dialog.Close className="product-icon-button asset-media-lightbox-close" title="关闭放大预览"><X size={20} aria-hidden="true" /></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root> : null}</>;
}

function assetDisplayRank(asset: LibraryAsset): number {
  const isImportedLocal = asset.sourceSystem === "maitu" && asset.status === "stored" && asset.executionCapability === "local_only";
  if (isImportedLocal && asset.mediaKind === "image") return 0;
  if (isImportedLocal && asset.mediaKind === "video") return 1;
  if (asset.sourceSystem === "local_upload" && asset.status === "stored") return 2;
  if (asset.status === "stored") return 3;
  return 4;
}

function AssetPreview({ asset }: { asset: LibraryAsset }) {
  const inferredKind = asset.mediaKind ?? (asset.assetType === "VID" ? "video" : asset.assetType === "IMG" ? "image" : undefined);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [hovering, setHovering] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const Icon = inferredKind === "video" ? Film : FileImage;
  useEffect(() => {
    if (inferredKind !== "video" || !hovering || !videoRef.current) return;
    const video = videoRef.current;
    void video.play().catch(() => undefined);
    return () => {
      video.pause();
      video.currentTime = 0;
    };
  }, [hovering, inferredKind]);
  if (inferredKind !== "image" && inferredKind !== "video") {
    return <div className="asset-thumb-placeholder"><Icon size={28} aria-hidden="true" /><span>暂不支持预览</span></div>;
  }
  if (inferredKind === "video") {
    const posterUrl = assetLibraryApi.previewUrl(asset.assetCode, "poster");
    const hoverUrl = assetLibraryApi.previewUrl(asset.assetCode, "hover");
    return <span className="asset-thumb-video-preview" onMouseEnter={() => { setHovering(true); setState("loading"); }} onMouseLeave={() => { setHovering(false); setState("ready"); }}>
      {state !== "ready" ? <div className="asset-thumb-placeholder"><Icon size={28} aria-hidden="true" /><span>{state === "error" ? "暂无预览" : hovering ? "正在缓冲预览" : "正在读取首帧"}</span></div> : null}
      {!hovering ? <img className={state === "ready" ? undefined : "asset-thumb-media-pending"} loading="lazy" src={posterUrl} alt="" onLoad={() => setState("ready")} onError={() => setState("error")} /> : <video ref={videoRef} autoPlay loop muted playsInline preload="metadata" poster={posterUrl} src={hoverUrl} onLoadedData={() => setState("ready")} onError={() => setState("error")} />}
    </span>;
  }
  return <>{state !== "ready" ? <div className="asset-thumb-placeholder"><Icon size={28} aria-hidden="true" /><span>{state === "error" ? "暂无预览" : "正在加载"}</span></div> : null}<img className={state === "ready" ? undefined : "asset-thumb-media-pending"} loading="lazy" src={assetLibraryApi.previewUrl(asset.assetCode, "thumbnail")} alt="" onLoad={() => setState("ready")} onError={() => setState("error")} /></>;
}

function compactAssetPreviewUrl(assetCode: string, mediaKind?: string, assetType?: string): string {
  const kind = mediaKind ?? (assetType === "VID" ? "video" : assetType === "IMG" ? "image" : undefined);
  return assetLibraryApi.previewUrl(assetCode, kind === "image" || kind === "video" ? "thumbnail" : undefined);
}

function SelectedGroupCreator({ assets, selected, onClose }: { assets: LibraryAsset[]; selected: string[]; onClose: () => void }) {
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const members = assets.filter((asset) => selected.includes(asset.assetCode));
  const create = useMutation({
    mutationFn: () => assetLibraryApi.createGroup({ title: title.trim(), description: description.trim() || undefined, asset_codes: selected }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["assets", "groups"] });
      onClose();
    },
  });
  const reason = !title.trim() ? "请先填写素材组名称" : !members.length ? "至少选择一份素材" : undefined;
  return <section className="asset-inline-editor asset-selected-group-creator"><header><div><h3>新建素材组</h3><p>当前已选素材会加入这个分组，同一份素材仍可加入其他分组。</p></div><button className="product-icon-button" type="button" title="关闭" onClick={onClose}><X size={16} aria-hidden="true" /></button></header><div className="asset-pack-fields"><label className="product-field"><span>素材组名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：夏季家居主视觉" /></label><label className="product-field wide"><span>说明（可选）</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="适用主题、品牌或使用场景" /></label></div><div className="asset-pack-members">{members.map((asset) => <div key={asset.assetCode} className="asset-selected-group-member"><img src={compactAssetPreviewUrl(asset.assetCode, asset.mediaKind, asset.assetType)} alt="" /><span><strong>{asset.title}</strong><small>{productLabel(asset.mediaKind ?? asset.assetType, "素材")}</small></span></div>)}</div><footer><button className="product-secondary-button" type="button" onClick={onClose}>取消</button><button className="product-primary-button" type="button" disabled={Boolean(reason) || create.isPending} onClick={() => create.mutate()}>创建素材组</button></footer>{reason ? <small className="product-helper-copy">{reason}</small> : null}{create.error ? <InlineNotice tone="danger" title="素材组没有创建">请检查分组名称和当前选中的素材后重试。</InlineNotice> : null}</section>;
}

function GroupBatchActions({ groups, groupCode, onGroupCodeChange, onAdd, adding, onCreate }: { groups: Array<{ groupCode: string; title: string }>; groupCode: string; onGroupCodeChange: (value: string) => void; onAdd: () => void; adding: boolean; onCreate: () => void }) {
  const hasGroups = groups.length > 0;
  return <><select aria-label="选择已有素材组" value={groupCode} disabled={!hasGroups} onChange={(event) => onGroupCodeChange(event.target.value)}><option value="">选择素材组</option>{groups.map((item) => <option key={item.groupCode} value={item.groupCode}>{item.title}</option>)}</select><button className="wb-button wb-button-primary" type="button" disabled={!groupCode || adding} title={!hasGroups ? "当前还没有素材组，请先新建一个素材组" : !groupCode ? "请选择一个已有素材组" : "将当前选择加入素材组"} onClick={onAdd}>确认加入</button><span role="status">{hasGroups ? (groupCode ? "已选择一个素材组" : "请选择已有素材组，或新建素材组") : "当前还没有素材组，请先新建一个素材组"}</span><button className="wb-button" type="button" onClick={onCreate}><Plus size={15} aria-hidden="true" />新建素材组</button></>;
}

function MaterialView({ assets, selected, onSelect }: { assets: LibraryAsset[]; selected: string[]; onSelect: (code: string, multi: boolean) => void }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("all");
  const [kind, setKind] = useState("all");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [batchMode, setBatchMode] = useState<"group" | "role">();
  const [groupCode, setGroupCode] = useState("");
  const [batchRole, setBatchRole] = useState<MaterialRole>("product_display");
  const [creatingGroup, setCreatingGroup] = useState(false);
  const groups = useQuery({ queryKey: ["assets","groups"], queryFn: assetLibraryApi.listGroups });
  const addToGroup = useMutation({ mutationFn: () => { const group = groups.data?.find((item) => item.groupCode === groupCode); if (!group) throw new Error("请选择素材组"); return assetLibraryApi.replaceGroupMembers(group.groupCode,[...new Set([...group.assetCodes,...selected])]); }, onSuccess: () => { setBatchMode(undefined); void client.invalidateQueries({ queryKey:["assets","groups"] }); } });
  const applyRole = useMutation({ mutationFn: () => Promise.all(assets.filter((item) => selected.includes(item.assetCode)).map((item) => assetLibraryApi.updateClassification(item.assetCode,{ media_kind:item.mediaKind, material_roles:[...new Set([...item.materialRoles,batchRole])], ...(item.executionCapability === "maitu_bound" ? {} : { execution_capability:item.executionCapability }), classification_review_status:"confirmed", classification_confidence:1, classification_evidence:{ source:"manual_operator", action:"batch_role_append" } }))), onSuccess: () => { setBatchMode(undefined); void client.invalidateQueries({ queryKey:["assets"] }); } });
  const orderedAssets = useMemo(() => assets.map((asset, index) => ({ asset, index })).sort((left, right) => assetDisplayRank(left.asset) - assetDisplayRank(right.asset) || left.index - right.index).map(({ asset }) => asset), [assets]);
  const filtered = useMemo(() => orderedAssets.filter((asset) => (role === "all" || asset.materialRoles.includes(role)) && (kind === "all" || asset.mediaKind === kind) && assetMatchesQuery(asset, query)), [orderedAssets, kind, query, role]);
  return <><div className="asset-product-toolbar"><label><Search size={15} aria-hidden="true" /><input aria-label="搜索素材" placeholder="搜索素材名称或编号" value={query} onChange={(event) => setQuery(event.target.value)} /></label><select aria-label="按媒体类型筛选" value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">全部媒体</option>{MEDIA_KINDS.map((value) => <option key={value} value={value}>{productLabel(value)}</option>)}</select><select aria-label="按用途筛选" value={role} onChange={(event) => setRole(event.target.value)}><option value="all">全部用途</option>{MATERIAL_ROLES.map((value) => <option key={value} value={value}>{productLabel(value, "其他用途")}</option>)}</select><span>{filtered.length} 份素材</span><div><button type="button" className={view === "grid" ? "active" : undefined} title="网格视图" onClick={() => setView("grid")}><Grid2X2 size={16} aria-hidden="true" /></button><button type="button" className={view === "list" ? "active" : undefined} title="列表视图" onClick={() => setView("list")}><List size={16} aria-hidden="true" /></button></div></div>{selected.length > 1 ? <div className="asset-batch-bar"><strong>已选择 {selected.length} 份素材</strong>{batchMode === "group" ? <GroupBatchActions groups={groups.data ?? []} groupCode={groupCode} onGroupCodeChange={setGroupCode} onAdd={() => addToGroup.mutate()} adding={addToGroup.isPending} onCreate={() => setCreatingGroup(true)} /> : batchMode === "role" ? <><select value={batchRole} onChange={(event) => setBatchRole(event.target.value as MaterialRole)}>{MATERIAL_ROLES.map((value) => <option key={value} value={value}>{productLabel(value,"其他用途")}</option>)}</select><button className="wb-button wb-button-primary" type="button" disabled={applyRole.isPending} onClick={() => applyRole.mutate()}>确认追加</button></> : <span>可批量加入分组或追加用途</span>}<button className="wb-button" type="button" onClick={() => setBatchMode(batchMode === "group" ? undefined : "group")}>加入分组</button><button className="wb-button" type="button" onClick={() => setBatchMode(batchMode === "role" ? undefined : "role")}>追加用途</button></div> : null}{creatingGroup ? <SelectedGroupCreator assets={assets} selected={selected} onClose={() => setCreatingGroup(false)} /> : null}{filtered.length ? <div className={`asset-product-${view}`}>{filtered.map((asset) => <button type="button" key={asset.assetCode} className={selected.includes(asset.assetCode) ? "selected" : undefined} onClick={(event) => onSelect(asset.assetCode, event.ctrlKey || event.metaKey)}><div className="asset-thumb"><AssetPreview asset={asset} /><span className="asset-select-check">{selected.includes(asset.assetCode) ? <Check size={13} aria-hidden="true" /> : null}</span></div><div className="asset-card-copy"><strong>{asset.title}</strong><small>{productLabel(asset.mediaKind ?? asset.assetType, "素材")} · {asset.materialRoles.map((item) => productLabel(item, "其他用途")).join("、") || "待设定用途"}</small><div><StatusBadge label={asset.classificationReviewStatus} tone={asset.classificationReviewStatus === "review_required" ? "warning" : "neutral"} /><StatusBadge label={asset.rightsStatus} tone={asset.rightsStatus === "approved" ? "success" : "warning"} /><StatusBadge label={asset.executionCapability} tone="neutral" /></div></div></button>)}</div> : <EmptyBlock icon={FileImage} title="没有匹配的素材" detail="调整筛选条件，或导入新的素材文件。" />}</>;
}

function GroupView({ assets }: { assets: LibraryAsset[] }) {
  const queryClient = useQueryClient();
  const groups = useQuery({ queryKey: ["assets", "groups"], queryFn: assetLibraryApi.listGroups });
  const [title, setTitle] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const create = useMutation({ mutationFn: () => assetLibraryApi.createGroup({ title: title.trim(), asset_codes: members }), onSuccess: async () => { setTitle(""); setMembers([]); await queryClient.invalidateQueries({ queryKey: ["assets", "groups"] }); } });
  const archive = useMutation({ mutationFn: assetLibraryApi.archiveGroup, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assets", "groups"] }) });
  const reason = !title.trim() ? "请先填写分组名称" : !members.length ? "至少选择一份素材" : undefined;
  return <div className="asset-groups-workspace"><section className="asset-group-create"><h2>创建素材组</h2><p>同一份素材可以加入多个素材组。</p><label className="wb-field"><span>分组名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：夏季家居主视觉" /></label><div className="asset-group-member-picker"><span>选择素材</span>{assets.map((asset) => <label key={asset.assetCode}><input type="checkbox" checked={members.includes(asset.assetCode)} onChange={() => setMembers((current) => toggle(current, asset.assetCode))} /><img src={compactAssetPreviewUrl(asset.assetCode, asset.mediaKind, asset.assetType)} alt="" /><span>{asset.title}</span></label>)}</div><button className="wb-button wb-button-primary" type="button" disabled={Boolean(reason) || create.isPending} title={reason} onClick={() => create.mutate()}><Plus size={15} aria-hidden="true" />创建分组</button>{reason ? <small className="product-helper-copy">{reason}</small> : null}{create.error ? <InlineNotice tone="danger" title="素材组没有创建">请检查分组名称和选中的素材后重试。</InlineNotice> : null}</section><section className="asset-group-list"><header><h2>已有分组</h2><span>{groups.data?.length ?? 0} 个</span></header>{groups.isLoading ? <LoadingBlock /> : groups.data?.length ? groups.data.map((group) => <article key={group.groupCode}><div className="asset-group-stack">{group.assetCodes.slice(0, 3).map((code) => <img key={code} src={assetLibraryApi.previewUrl(code, "thumbnail")} alt="" />)}{!group.assetCodes.length ? <Layers3 size={22} aria-hidden="true" /> : null}</div><span><strong>{group.title}</strong><small>{group.assetCount} 份素材</small><p>{group.description || "暂无备注"}</p></span><button type="button" className="product-icon-button" title="删除分组" onClick={() => archive.mutate(group.groupCode)}><Trash2 size={15} aria-hidden="true" /></button></article>) : <EmptyBlock icon={Layers3} title="还没有素材组" />}</section></div>;
}

function PackCreator({ assets, onClose }: { assets: LibraryAsset[]; onClose: () => void }) {
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"total" | "classification">("total");
  const [role, setRole] = useState("background");
  const [members, setMembers] = useState<string[]>([]);
  const create = useMutation({ mutationFn: () => assetLibraryApi.createPack({ title, description, pack_kind: kind, role: kind === "classification" ? role : undefined, entries: members.map((code) => ({ selection_kind: "asset", selection_code: code, material_role: kind === "classification" ? role : assets.find((item) => item.assetCode === code)?.materialRoles[0] ?? "background", mode: "required", min_occurrences: 1, max_occurrences: 1, applicable_scope: { kind: "whole_room", scene_types: [], scene_codes: [] }, pack_constraints: [] })) }), onSuccess: () => { void client.invalidateQueries({ queryKey: ["assets", "packs"] }); onClose(); } });
  return <div className="asset-inline-editor"><header><div><h3>新建素材包</h3><p>把一组常用素材保存为可复用选材方案。</p></div><button className="product-icon-button" type="button" title="关闭" onClick={onClose}><X size={16} /></button></header><div className="asset-pack-fields"><label className="product-field"><span>素材包名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="product-field"><span>用途</span><select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="total">整套直播间素材</option><option value="classification">单一用途素材</option></select></label>{kind === "classification" ? <label className="product-field"><span>素材用途</span><select value={role} onChange={(event) => setRole(event.target.value)}>{MATERIAL_ROLES.map((item) => <option key={item} value={item}>{productLabel(item, "其他用途")}</option>)}</select></label> : null}<label className="product-field wide"><span>说明</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="适用主题、品牌或使用场景" /></label></div><div className="asset-pack-members">{assets.map((item) => <label key={item.assetCode}><input type="checkbox" checked={members.includes(item.assetCode)} onChange={() => setMembers((current) => toggle(current,item.assetCode))} /><img src={compactAssetPreviewUrl(item.assetCode, item.mediaKind, item.assetType)} alt="" /><span><strong>{item.title}</strong><small>{item.materialRoles.map((value) => productLabel(value,"素材")).join("、") || "待设置用途"}</small></span></label>)}</div><footer><button className="product-secondary-button" type="button" onClick={onClose}>取消</button><button className="product-primary-button" type="button" disabled={!title.trim() || !members.length || create.isPending} onClick={() => create.mutate()}>保存素材包</button></footer>{create.error ? <small className="product-error-copy">素材包没有保存，请检查名称和所选素材。</small> : null}</div>;
}

function GapCreator({ assets, onClose }: { assets: LibraryAsset[]; onClose: () => void }) {
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [role, setRole] = useState("background");
  const [severity, setSeverity] = useState("medium");
  const [impact, setImpact] = useState("");
  const [alternatives, setAlternatives] = useState<string[]>([]);
  const create = useMutation({ mutationFn: () => assetLibraryApi.createGap({ title, role, severity, gap_type: "material_missing", impact_summary: impact, specification: { desired_role: role }, source_context: { source: "operator" }, alternative_asset_codes: alternatives }), onSuccess: () => { void client.invalidateQueries({ queryKey: ["assets", "gaps"] }); onClose(); } });
  return <div className="asset-inline-editor"><header><div><h3>登记素材缺口</h3><p>记录当前缺少什么，以及它会影响哪些制作任务。</p></div><button className="product-icon-button" type="button" title="关闭" onClick={onClose}><X size={16} /></button></header><div className="asset-pack-fields"><label className="product-field"><span>缺口名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="product-field"><span>需要的用途</span><select value={role} onChange={(event) => setRole(event.target.value)}>{MATERIAL_ROLES.map((item) => <option key={item} value={item}>{productLabel(item,"其他用途")}</option>)}</select></label><label className="product-field"><span>影响程度</span><select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="low">可以稍后补充</option><option value="medium">影响部分场景</option><option value="high">阻止方案生成</option></select></label><label className="product-field wide"><span>影响说明</span><input value={impact} onChange={(event) => setImpact(event.target.value)} placeholder="例如：缺少桌面背景，商品无法自然摆放" /></label></div><div className="asset-pack-members"><span className="asset-member-caption">可接受的替代素材</span>{assets.filter((item) => item.materialRoles.includes(role)).map((item) => <label key={item.assetCode}><input type="checkbox" checked={alternatives.includes(item.assetCode)} onChange={() => setAlternatives((current) => toggle(current,item.assetCode))} /><img src={compactAssetPreviewUrl(item.assetCode, item.mediaKind, item.assetType)} alt="" /><span><strong>{item.title}</strong><small>可作为替代</small></span></label>)}</div><footer><button className="product-secondary-button" type="button" onClick={onClose}>取消</button><button className="product-primary-button" type="button" disabled={!title.trim() || !impact.trim() || create.isPending} onClick={() => create.mutate()}>登记缺口</button></footer>{create.error ? <small className="product-error-copy">素材缺口没有保存，请检查必填内容。</small> : null}</div>;
}

function PackGapView({ mode, assets }: { mode: "packs" | "gaps"; assets: LibraryAsset[] }) {
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [resolutions, setResolutions] = useState<Record<string,string>>({});
  const query = useQuery<MaterialPack[] | AssetGap[]>({ queryKey: ["assets", mode], queryFn: async () => mode === "packs" ? assetLibraryApi.listPacks() : assetLibraryApi.listGaps() });
  const publish = useMutation({ mutationFn: assetLibraryApi.publishPack, onSuccess: () => client.invalidateQueries({ queryKey: ["assets","packs"] }) });
  const resolve = useMutation({ mutationFn: ({ gapCode, assetCode }: { gapCode: string; assetCode: string }) => assetLibraryApi.updateGap(gapCode,{ status: "resolved", resolution_asset_code: assetCode, actor: "functional-operator", resolution_evidence: { note: "运营人员选择可用替代素材" } }), onSuccess: () => client.invalidateQueries({ queryKey: ["assets","gaps"] }) });
  if (query.isLoading) return <LoadingBlock />;
  const values = query.data ?? [];
  return <section className="asset-simple-list"><header><div><h2>{mode === "packs" ? "素材包" : "素材缺口"}</h2><p>{mode === "packs" ? "将常用素材组合成可复用选材方案。" : "查看生成所缺少的素材，并选择可用替代。"}</p></div><button className="wb-button wb-button-primary" type="button" onClick={() => setCreating(true)}><Plus size={15} aria-hidden="true" />{mode === "packs" ? "新建素材包" : "登记缺口"}</button></header>{creating ? mode === "packs" ? <PackCreator assets={assets} onClose={() => setCreating(false)} /> : <GapCreator assets={assets} onClose={() => setCreating(false)} /> : null}{values.length ? <div>{mode === "packs" ? (values as MaterialPack[]).map((item) => <article key={item.packCode}><div className="asset-simple-icon"><PackageOpen size={18} /></div><span><strong>{item.title}</strong><small>{item.entries.length} 条选材规则 · {item.description || "暂无说明"}</small></span><StatusBadge label={item.status} tone={item.status === "published" ? "success" : "warning"} />{item.status === "draft" ? <button className="product-secondary-button" type="button" disabled={publish.isPending} onClick={() => publish.mutate(item.packCode)}>发布使用</button> : null}</article>) : (values as AssetGap[]).map((item) => <article key={item.gapCode}><div className="asset-simple-icon"><SlidersHorizontal size={18} /></div><span><strong>{item.title}</strong><small>{productLabel(item.role,"素材")} · {item.impactSummary || "等待补充影响说明"}</small></span><StatusBadge label={item.status} tone={item.status === "resolved" ? "success" : "warning"} />{item.status !== "resolved" ? <div className="asset-gap-resolution"><select value={resolutions[item.gapCode] ?? ""} onChange={(event) => setResolutions((current) => ({ ...current,[item.gapCode]:event.target.value }))}><option value="">选择替代素材</option>{[...new Set([...item.alternativeAssetCodes,...assets.filter((asset) => asset.materialRoles.includes(item.role)).map((asset) => asset.assetCode)])].map((code) => <option key={code} value={code}>{assets.find((asset) => asset.assetCode === code)?.title ?? "可用素材"}</option>)}</select><button className="product-primary-button" type="button" disabled={!resolutions[item.gapCode] || resolve.isPending} onClick={() => resolve.mutate({ gapCode:item.gapCode, assetCode:resolutions[item.gapCode]! })}>标记已解决</button></div> : null}</article>)}</div> : <EmptyBlock icon={mode === "packs" ? PackageOpen : SlidersHorizontal} title={mode === "packs" ? "还没有素材包" : "当前没有素材缺口"} />}</section>;
}

function AnalysisView() {
  const client = useQueryClient();
  const [run, setRun] = useState("");
  const runs = useQuery({ queryKey: ["maitu","runs"], queryFn: maituApi.listRuns });
  useEffect(() => { if (!run && runs.data?.[0]) setRun(runs.data[0].run_code); }, [run,runs.data]);
  const analyses = useQuery({ queryKey: ["maitu","video-analyses",run], queryFn: () => maituApi.listVideoAnalyses(run), enabled:Boolean(run) });
  const conflicts = useQuery({ queryKey: ["maitu","analysis-conflicts",run], queryFn: () => maituApi.listConflicts(run), enabled:Boolean(run) });
  const resolve = useMutation({ mutationFn: ({ item, choice }: { item: AnalysisConflict; choice: "provisional" | "gemini" | "replace_asset" }) => maituApi.resolveConflict(run,item.conflict_code,choice), onSuccess: () => client.invalidateQueries({ queryKey:["maitu","analysis-conflicts",run] }) });
  return <section className="asset-analysis-product"><header><div><h2>素材分析</h2><p>查看视频素材的画面结论，并处理会影响选材的分析分歧。</p></div><label className="product-field"><span>内容项目运行</span><select value={run} onChange={(event) => setRun(event.target.value)}><option value="">选择项目运行</option>{runs.data?.map((item) => <option key={item.run_code} value={item.run_code}>{item.title}</option>)}</select></label></header>{analyses.isLoading ? <LoadingBlock label="正在读取素材分析" /> : <div className="asset-analysis-grid">{analyses.data?.map((item) => <article key={item.analysis_code}><div className="asset-analysis-preview"><Film size={24} /></div><span><strong>{item.asset_title}</strong><small>{item.provisional_summary || item.gemini_summary || "等待分析结论"}</small></span><StatusBadge label={item.gemini_status === "succeeded" ? "分析已确认" : item.provisional_source !== "none" ? "已有初步结论" : "等待分析"} tone={item.gemini_status === "succeeded" ? "success" : "warning"} /></article>)}</div>}{!analyses.isLoading && !analyses.data?.length ? <EmptyBlock icon={Sparkles} title="当前没有待分析视频" detail="视频素材参与项目选材后，会在这里显示分析结论。" /> : null}{conflicts.data?.filter((item) => !item.resolution).length ? <div className="asset-analysis-conflicts"><h3>需要人工判断</h3>{conflicts.data.filter((item) => !item.resolution).map((item) => <article key={item.conflict_code}><AlertTriangle size={17} /><span><strong>{productCopy(item.field,"画面分析存在分歧")}</strong><small>初步结论：{item.provisional_value || "未给出"} · 补充分析：{item.gemini_value || "未给出"}</small></span><div><button type="button" className="product-secondary-button" onClick={() => resolve.mutate({ item,choice:"provisional" })}>保留初步结论</button><button type="button" className="product-primary-button" onClick={() => resolve.mutate({ item,choice:"gemini" })}>采用补充分析</button><button type="button" className="product-secondary-button" onClick={() => resolve.mutate({ item,choice:"replace_asset" })}>更换素材</button></div></article>)}</div> : null}</section>;
}

export function AssetLibraryProductPage({ search }: { search: string }) {
  const params = new URLSearchParams(search);
  const [tab, setTab] = useState<"materials" | "groups" | "packs" | "gaps" | "analysis">(() => { const value = params.get("tab") ?? (params.get("panel") === "analysis" ? "analysis" : ""); return value === "groups" || value === "packs" || value === "gaps" || value === "analysis" ? value : "materials"; });
  const [importOpen, setImportOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>(params.get("asset") ? [params.get("asset")!] : []);
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const active = assets.data?.find((asset) => asset.assetCode === selected.at(-1));
  const changeTab = (value: typeof tab) => { setTab(value); setSelected([]); };
  const tabs: Array<{ value: typeof tab; label: string; icon: typeof FileImage }> = [{ value: "materials", label: "全部素材", icon: FileImage }, { value: "groups", label: "素材组", icon: Layers3 }, { value: "packs", label: "素材包", icon: PackageOpen }, { value: "gaps", label: "素材缺口", icon: ShieldCheck }, { value: "analysis", label: "素材分析", icon: Sparkles }];
  return <div className={`asset-product-page ${active ? "has-inspector" : ""}`}><AssetImportDialog open={importOpen} onClose={() => setImportOpen(false)} /><PageHeader eyebrow="内容基础" title="素材库" description="管理素材用途、使用状态、布局约束、分组和选材方案。" actions={<button className="wb-button wb-button-primary" type="button" onClick={() => setImportOpen(true)}><ImagePlus size={16} aria-hidden="true" />导入素材</button>} /><nav className="asset-product-tabs">{tabs.map((item) => { const Icon = item.icon; return <button type="button" key={item.value} className={tab === item.value ? "active" : undefined} onClick={() => changeTab(item.value)}><Icon size={15} aria-hidden="true" />{item.label}</button>; })}</nav>{assets.isLoading ? <LoadingBlock label="正在读取素材库" /> : assets.error ? <EmptyBlock title="素材库暂时无法读取" detail="请检查服务连接后刷新。" /> : tab === "materials" ? <MaterialView assets={assets.data ?? []} selected={selected} onSelect={(code, multi) => setSelected((current) => multi ? toggle(current, code) : current.length === 1 && current[0] === code ? [] : [code])} /> : tab === "groups" ? <GroupView assets={assets.data ?? []} /> : tab === "analysis" ? <AnalysisView /> : <PackGapView mode={tab} assets={assets.data ?? []} />}{active ? <AssetInspector asset={active} onClose={() => setSelected([])} /> : null}</div>;
}
