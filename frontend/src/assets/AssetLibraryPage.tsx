import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, FolderPlus, PackagePlus, Plus, Save, Search, TriangleAlert } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge } from "../workbench/components";
import { type AssetGap, type ConstraintRule, type ExecutionCapability, type LibraryAsset, type MaterialPack, type MaterialRole, assetLibraryApi } from "./api";

const ROLES: MaterialRole[] = ["background", "product_display", "digital_human", "brand_title", "promotion_text", "decoration_foreground", "supporting_video", "voice", "background_music", "sound_effect"];
const MEDIA_KINDS = ["image", "video", "audio", "digital_human", "text", "template_preview", "document"];
const CONSTRAINT_KINDS = ["allowed_region", "forbidden_region", "preserve_aspect_ratio", "size_range", "scale_range", "pin_layer_top", "pin_layer_bottom", "above_role", "below_role", "avoid_overlap", "table_surface"];

type Tab = "materials" | "groups" | "packs" | "gaps";

function message(error: unknown): string { return error instanceof Error ? error.message : "操作未完成"; }
function codes(value: string): string[] { return Array.from(new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))); }

function ClassificationEditor({ asset, onSaved }: { asset: LibraryAsset; onSaved: () => void }) {
  const [mediaKind, setMediaKind] = useState(asset.mediaKind ?? "");
  const [roles, setRoles] = useState<string[]>(asset.materialRoles);
  const [capability, setCapability] = useState<ExecutionCapability>(asset.executionCapability);
  const mutation = useMutation({ mutationFn: () => assetLibraryApi.updateClassification(asset.assetCode, { media_kind: mediaKind || undefined, material_roles: roles, execution_capability: capability }), onSuccess: onSaved });
  const toggle = (role: string) => setRoles((current) => current.includes(role) ? current.filter((item) => item !== role) : [...current, role]);
  return <section className="asset-detail-panel">
    <SectionHeader kicker={asset.assetCode} title={asset.title} />
    <div className="wb-form-grid">
      <label className="wb-field"><span>媒体类型</span><select className="wb-input" value={mediaKind} onChange={(event) => setMediaKind(event.target.value)}><option value="">待确认</option>{MEDIA_KINDS.map((kind) => <option key={kind}>{kind}</option>)}</select></label>
      <label className="wb-field"><span>执行能力</span><select className="wb-input" value={capability} onChange={(event) => setCapability(event.target.value as ExecutionCapability)}>{["unclassified", "maitu_bound", "local_only", "reference_only", "unavailable"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <div className="wb-field wide"><span>业务角色</span><div className="asset-role-options">{ROLES.map((role) => <label key={role}><input type="checkbox" checked={roles.includes(role)} onChange={() => toggle(role)} />{role}</label>)}</div></div>
    </div>
    {mutation.error ? <InlineNotice tone="danger" title="无法保存分类">{message(mutation.error)}</InlineNotice> : null}
    <div className="wb-form-actions"><button type="button" className="wb-button wb-button-primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}><Save size={14} aria-hidden="true" />保存分类</button></div>
  </section>;
}

function ConstraintEditor({ assetCode }: { assetCode: string }) {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({ queryKey: ["assets", "constraint-profile", assetCode], queryFn: () => assetLibraryApi.getConstraintProfile(assetCode), retry: false });
  const [rules, setRules] = useState<ConstraintRule[]>([]);
  const [loaded, setLoaded] = useState(false);
  if (!loaded && profileQuery.data) { setRules(profileQuery.data.constraints); setLoaded(true); }
  const mutation = useMutation({ mutationFn: () => assetLibraryApi.writeConstraintProfile(assetCode, rules), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["assets", "constraint-profile", assetCode] }) });
  const update = (index: number, field: keyof ConstraintRule, value: unknown) => setRules((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item));
  return <section className="asset-detail-panel"><SectionHeader kicker="CONSTRAINT PROFILE" title="位置与图层约束" />
    <div className="asset-constraint-list">{rules.map((rule, index) => <div key={`${rule.kind}:${index}`} className="asset-constraint-row"><select className="wb-input" value={rule.kind} onChange={(event) => update(index, "kind", event.target.value)}>{CONSTRAINT_KINDS.map((kind) => <option key={kind}>{kind}</option>)}</select><label><input type="checkbox" checked={rule.hard} onChange={(event) => update(index, "hard", event.target.checked)} />硬约束</label><input className="wb-input" value={JSON.stringify(rule.parameters)} aria-label="约束参数 JSON" onChange={(event) => { try { update(index, "parameters", JSON.parse(event.target.value)); } catch { /* retain the last valid parameters */ } }} /><button type="button" className="wb-button" title="删除约束" onClick={() => setRules((current) => current.filter((_, itemIndex) => itemIndex !== index))}>删除</button></div>)}</div>
    <div className="wb-form-actions"><button type="button" className="wb-button" onClick={() => setRules((current) => [...current, { kind: "preserve_aspect_ratio", hard: true, parameters: {} }])}><Plus size={14} aria-hidden="true" />添加约束</button><button type="button" className="wb-button wb-button-primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}><Save size={14} aria-hidden="true" />保存新修订</button></div>
    {mutation.error ? <InlineNotice tone="danger" title="约束保存失败">{message(mutation.error)}</InlineNotice> : null}
  </section>;
}

function MaterialTab({ assets }: { assets: LibraryAsset[] }) {
  const queryClient = useQueryClient();
  const [selectedCode, setSelectedCode] = useState("");
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [filename, setFilename] = useState("");
  const create = useMutation({ mutationFn: () => assetLibraryApi.createAsset({ title, original_filename: filename, asset_type: "IMG", material_roles: [], execution_capability: "local_only" }), onSuccess: (created) => { setSelectedCode(created.assetCode); setShowCreate(false); setTitle(""); setFilename(""); void queryClient.invalidateQueries({ queryKey: ["assets", "library"] }); } });
  const filtered = useMemo(() => assets.filter((item) => `${item.assetCode} ${item.title} ${item.materialRoles.join(" ")}`.toLowerCase().includes(query.toLowerCase())), [assets, query]);
  const selected = assets.find((item) => item.assetCode === selectedCode) ?? filtered[0];
  return <div className="asset-library-layout"><section className="wb-section"><SectionHeader kicker="MATERIAL LIBRARY" title="素材" actions={<button type="button" className="wb-button wb-button-primary" onClick={() => setShowCreate((value) => !value)}><Plus size={14} aria-hidden="true" />新建素材</button>} />
    {showCreate ? <form className="asset-inline-form" onSubmit={(event: FormEvent) => { event.preventDefault(); if (title.trim() && filename.trim()) create.mutate(); }}><label className="wb-field"><span>名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="wb-field"><span>文件名</span><input className="wb-input" value={filename} onChange={(event) => setFilename(event.target.value)} /></label><button className="wb-button wb-button-primary" disabled={create.isPending}>创建</button></form> : null}
    <label className="asset-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选素材编码、名称或角色" /></label>
    <div className="asset-list">{filtered.map((item) => <button key={item.assetCode} type="button" className={selected?.assetCode === item.assetCode ? "active" : undefined} onClick={() => setSelectedCode(item.assetCode)}><span><strong>{item.title}</strong><code>{item.assetCode}</code><small>{item.materialRoles.join(" / ") || "未分类"}</small></span><StatusBadge label={item.executionCapability} tone={item.executionCapability === "maitu_bound" ? "success" : item.executionCapability === "unclassified" ? "warning" : "neutral"} /></button>)}</div>
    {!filtered.length ? <EmptyBlock icon={Boxes} title="尚无匹配素材" /> : null}</section>
    <div>{selected ? <><ClassificationEditor key={selected.assetCode} asset={selected} onSaved={() => void queryClient.invalidateQueries({ queryKey: ["assets", "library"] })} /><ConstraintEditor key={`constraints:${selected.assetCode}`} assetCode={selected.assetCode} /></> : <EmptyBlock icon={Boxes} title="选择一个素材" detail="创建或同步素材后可设置分类与约束。" />}</div></div>;
}

function GroupsTab({ groups }: { groups: Awaited<ReturnType<typeof assetLibraryApi.listGroups>> }) {
  const queryClient = useQueryClient(); const [title, setTitle] = useState(""); const [assetCodes, setAssetCodes] = useState("");
  const create = useMutation({ mutationFn: () => assetLibraryApi.createGroup({ title, asset_codes: codes(assetCodes) }), onSuccess: () => { setTitle(""); setAssetCodes(""); void queryClient.invalidateQueries({ queryKey: ["assets", "groups"] }); } });
  return <div className="asset-library-layout"><section className="wb-section"><SectionHeader kicker="MULTI-MEMBERSHIP" title="素材分组" /><form className="asset-stack-form" onSubmit={(event: FormEvent) => { event.preventDefault(); if (title.trim()) create.mutate(); }}><label className="wb-field"><span>分组名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="wb-field"><span>素材编码（逗号或换行分隔）</span><textarea className="wb-textarea" value={assetCodes} onChange={(event) => setAssetCodes(event.target.value)} /></label><button className="wb-button wb-button-primary" disabled={create.isPending}><FolderPlus size={14} aria-hidden="true" />创建分组</button></form>{create.error ? <InlineNotice tone="danger" title="分组创建失败">{message(create.error)}</InlineNotice> : null}</section>
  <section className="wb-section"><SectionHeader kicker="GROUPS" title="当前分组" />{groups.length ? <div className="asset-summary-list">{groups.map((group) => <div key={group.groupCode}><span><strong>{group.title}</strong><code>{group.groupCode}</code><small>{group.assetCodes.join("、") || "尚无成员"}</small></span><StatusBadge label={`${group.assetCount} 项`} tone="info" /></div>)}</div> : <EmptyBlock icon={FolderPlus} title="尚无分组" />}</section></div>;
}

function PacksTab({ groups, packs }: { groups: Awaited<ReturnType<typeof assetLibraryApi.listGroups>>; packs: MaterialPack[] }) {
  const queryClient = useQueryClient(); const [title, setTitle] = useState(""); const [role, setRole] = useState<string>("background"); const [kind, setKind] = useState<"asset" | "group">("group"); const [code, setCode] = useState(""); const [entries, setEntries] = useState<MaterialPack["entries"]>([]);
  const create = useMutation({ mutationFn: () => assetLibraryApi.createPack({ title, role, entries }), onSuccess: () => { setTitle(""); setEntries([]); void queryClient.invalidateQueries({ queryKey: ["assets", "packs"] }); } });
  return <div className="asset-library-layout"><section className="wb-section"><SectionHeader kicker="MATERIAL PACK" title="素材包" /><div className="asset-stack-form"><label className="wb-field"><span>素材包名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="wb-field"><span>角色</span><select className="wb-input" value={role} onChange={(event) => setRole(event.target.value)}>{ROLES.map((item) => <option key={item}>{item}</option>)}</select></label><div className="asset-pack-entry"><select className="wb-input" value={kind} onChange={(event) => setKind(event.target.value as "asset" | "group")}><option value="group">分组</option><option value="asset">素材</option></select><input className="wb-input" value={code} onChange={(event) => setCode(event.target.value)} placeholder={kind === "group" ? "AG-GRP-*" : "AG-IMG-*"} /><button type="button" className="wb-button" disabled={!code.trim()} onClick={() => { setEntries((current) => [...current, { selection_kind: kind, selection_code: code.trim(), mode: "optional", min_occurrences: 0 }]); setCode(""); }}>添加</button></div>{entries.length ? <ul className="asset-entry-list">{entries.map((item, index) => <li key={`${item.selection_kind}:${item.selection_code}:${index}`}><code>{item.selection_kind}:{item.selection_code}</code><button type="button" title="删除" onClick={() => setEntries((current) => current.filter((_, itemIndex) => itemIndex !== index))}>删除</button></li>)}</ul> : null}<button type="button" className="wb-button wb-button-primary" disabled={!title.trim() || !entries.length || create.isPending} onClick={() => create.mutate()}><PackagePlus size={14} aria-hidden="true" />创建素材包</button>{create.error ? <InlineNotice tone="danger" title="素材包创建失败">{message(create.error)}</InlineNotice> : null}</div></section>
  <section className="wb-section"><SectionHeader kicker="RESOLVED PREVIEW" title="解析预览" />{packs.length ? <div className="asset-summary-list">{packs.map((pack) => <div key={pack.packCode}><span><strong>{pack.title}</strong><code>{pack.packCode} · r{pack.revisionNumber}</code><small>{pack.resolvedAssetCodes.join("、") || "没有可用素材"}</small></span><StatusBadge label={pack.role} tone="info" /></div>)}</div> : <EmptyBlock icon={PackagePlus} title="尚无素材包" detail={groups.length ? "可将一个或多个分组加入素材包。" : "先创建素材分组或填写素材编码。"} />}</section></div>;
}

function GapsTab({ gaps }: { gaps: AssetGap[] }) {
  const queryClient = useQueryClient(); const [title, setTitle] = useState(""); const [role, setRole] = useState("background"); const [severity, setSeverity] = useState("medium");
  const create = useMutation({ mutationFn: () => assetLibraryApi.createGap({ title, role, severity }), onSuccess: () => { setTitle(""); void queryClient.invalidateQueries({ queryKey: ["assets", "gaps"] }); } });
  return <div className="asset-library-layout"><section className="wb-section"><SectionHeader kicker="ASSET GAP" title="素材缺口" /><form className="asset-stack-form" onSubmit={(event: FormEvent) => { event.preventDefault(); if (title.trim()) create.mutate(); }}><label className="wb-field"><span>缺口描述</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：用于桌面摆放的白葡萄酒商品图" /></label><label className="wb-field"><span>所需角色</span><select className="wb-input" value={role} onChange={(event) => setRole(event.target.value)}>{ROLES.map((item) => <option key={item}>{item}</option>)}</select></label><label className="wb-field"><span>严重度</span><select className="wb-input" value={severity} onChange={(event) => setSeverity(event.target.value)}>{["low", "medium", "high", "critical"].map((item) => <option key={item}>{item}</option>)}</select></label><button className="wb-button wb-button-primary" disabled={!title.trim() || create.isPending}><TriangleAlert size={14} aria-hidden="true" />登记缺口</button></form></section>
  <section className="wb-section"><SectionHeader kicker="OPEN GAPS" title="待处理缺口" />{gaps.length ? <div className="asset-summary-list">{gaps.map((gap) => <div key={gap.gapCode}><span><strong>{gap.title}</strong><code>{gap.gapCode}</code><small>{gap.role} · {gap.status}</small></span><StatusBadge label={gap.severity} tone={gap.severity === "critical" ? "danger" : gap.severity === "high" ? "warning" : "neutral"} /></div>)}</div> : <EmptyBlock icon={TriangleAlert} title="没有开放缺口" />}</section></div>;
}

export function AssetLibraryPage() {
  const [tab, setTab] = useState<Tab>("materials");
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets });
  const groups = useQuery({ queryKey: ["assets", "groups"], queryFn: assetLibraryApi.listGroups });
  const packs = useQuery({ queryKey: ["assets", "packs"], queryFn: assetLibraryApi.listPacks });
  const gaps = useQuery({ queryKey: ["assets", "gaps"], queryFn: assetLibraryApi.listGaps });
  const loading = assets.isLoading || groups.isLoading || packs.isLoading || gaps.isLoading;
  const problem = assets.error ?? groups.error ?? packs.error ?? gaps.error;
  return <div><div className="wb-tabs" role="tablist" aria-label="素材库视图">{[["materials", "素材", Boxes], ["groups", "分组", FolderPlus], ["packs", "素材包", PackagePlus], ["gaps", "缺口", TriangleAlert]].map(([key, label, Icon]) => { const Component = Icon as typeof Boxes; return <button key={key as string} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "active" : undefined} onClick={() => setTab(key as Tab)}><Component size={15} aria-hidden="true" />{label as string}</button>; })}</div>
    {loading ? <LoadingBlock /> : problem ? <InlineNotice tone="danger" title="素材库无法加载">{message(problem)}</InlineNotice> : tab === "materials" ? <MaterialTab assets={assets.data ?? []} /> : tab === "groups" ? <GroupsTab groups={groups.data ?? []} /> : tab === "packs" ? <PacksTab groups={groups.data ?? []} packs={packs.data ?? []} /> : <GapsTab gaps={gaps.data ?? []} />}
  </div>;
}
