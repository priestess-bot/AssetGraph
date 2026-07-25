import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  FolderPlus,
  PackagePlus,
  Plus,
  Save,
  Search,
  TriangleAlert,
} from "lucide-react";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../workbench/components";
import {
  type AssetGap,
  type AssetEffectSummary,
  type ConstraintRule,
  type ExecutionCapability,
  type LibraryAsset,
  type MaterialPack,
  type MaterialRole,
  assetLibraryApi,
} from "./api";

const ROLES: MaterialRole[] = [
  "background",
  "product_display",
  "digital_human",
  "brand_title",
  "promotion_text",
  "decoration_foreground",
  "supporting_video",
  "voice",
  "background_music",
  "sound_effect",
];
const MEDIA_KINDS = [
  "image",
  "video",
  "audio",
  "digital_human",
  "text",
  "template_preview",
  "document",
];
const CONSTRAINT_KINDS = [
  "allowed_region",
  "forbidden_region",
  "provide_named_region",
  "require_named_region",
  "preserve_aspect_ratio",
  "size_range",
  "scale_range",
  "crop_policy",
  "rotation_policy",
  "pin_layer_top",
  "pin_layer_bottom",
  "above_role",
  "below_role",
  "avoid_overlap",
  "align_anchor",
  "distance_range",
  "loop_policy",
  "mute_policy",
  "volume_range",
  "table_surface",
];
const CONSTRAINT_LABELS: Record<string, string> = {
  allowed_region: "允许区域",
  forbidden_region: "禁止区域",
  provide_named_region: "定义命名区域",
  require_named_region: "要求命名区域",
  preserve_aspect_ratio: "保持等比例",
  size_range: "尺寸范围",
  scale_range: "缩放范围",
  crop_policy: "裁剪策略",
  rotation_policy: "旋转策略",
  pin_layer_top: "置于顶层",
  pin_layer_bottom: "置于底层",
  above_role: "置于角色之上",
  below_role: "置于角色之下",
  avoid_overlap: "避免遮挡",
  align_anchor: "锚点对齐",
  distance_range: "距离范围",
  loop_policy: "循环策略",
  mute_policy: "静音策略",
  volume_range: "音量范围",
  table_surface: "桌面摆放区域",
};
type ConstraintParameter = {
  key: string;
  label: string;
  type: "text" | "number" | "role" | "select";
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
};
const CONSTRAINT_PARAMETERS: Record<string, ConstraintParameter[]> = {
  allowed_region: [
    { key: "x", label: "X", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "y", label: "Y", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "width", label: "宽", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "height", label: "高", type: "number", min: 0, max: 1, step: 0.01 },
  ],
  forbidden_region: [
    { key: "x", label: "X", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "y", label: "Y", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "width", label: "宽", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "height", label: "高", type: "number", min: 0, max: 1, step: 0.01 },
  ],
  provide_named_region: [
    { key: "name", label: "区域名称", type: "text" },
    { key: "x", label: "X", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "y", label: "Y", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "width", label: "宽", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "height", label: "高", type: "number", min: 0, max: 1, step: 0.01 },
  ],
  require_named_region: [{ key: "region", label: "区域名称", type: "text" }],
  preserve_aspect_ratio: [],
  size_range: [
    {
      key: "min_width",
      label: "最小宽",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
    {
      key: "max_width",
      label: "最大宽",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
    {
      key: "min_height",
      label: "最小高",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
    {
      key: "max_height",
      label: "最大高",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
  ],
  scale_range: [
    { key: "min_scale", label: "最小缩放", type: "number", min: 0, step: 0.01 },
    { key: "max_scale", label: "最大缩放", type: "number", min: 0, step: 0.01 },
  ],
  crop_policy: [
    {
      key: "policy",
      label: "裁剪",
      type: "select",
      options: ["contain", "cover", "forbid"],
    },
  ],
  rotation_policy: [
    {
      key: "policy",
      label: "旋转",
      type: "select",
      options: ["forbid", "allow"],
    },
  ],
  pin_layer_top: [],
  pin_layer_bottom: [],
  above_role: [{ key: "role", label: "目标角色", type: "role" }],
  below_role: [{ key: "role", label: "目标角色", type: "role" }],
  avoid_overlap: [
    { key: "role", label: "目标角色", type: "role" },
    {
      key: "max_overlap",
      label: "最大重叠",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
  ],
  align_anchor: [
    {
      key: "anchor",
      label: "自身锚点",
      type: "select",
      options: [
        "top_left",
        "top_center",
        "top_right",
        "center",
        "bottom_left",
        "bottom_center",
        "bottom_right",
      ],
    },
    { key: "region", label: "目标命名区域", type: "text" },
  ],
  distance_range: [
    { key: "role", label: "目标角色", type: "role" },
    {
      key: "min",
      label: "最小距离",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
    {
      key: "max",
      label: "最大距离",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
  ],
  loop_policy: [
    {
      key: "policy",
      label: "循环",
      type: "select",
      options: ["required", "forbidden"],
    },
  ],
  mute_policy: [
    {
      key: "policy",
      label: "静音",
      type: "select",
      options: ["muted", "unmuted"],
    },
  ],
  volume_range: [
    {
      key: "min",
      label: "最小音量",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
    {
      key: "max",
      label: "最大音量",
      type: "number",
      min: 0,
      max: 1,
      step: 0.01,
    },
  ],
  table_surface: [
    { key: "name", label: "桌面区域名", type: "text" },
    { key: "x", label: "X", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "y", label: "Y", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "width", label: "宽", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "height", label: "高", type: "number", min: 0, max: 1, step: 0.01 },
    { key: "product_role", label: "承载商品角色", type: "role" },
    {
      key: "product_anchor",
      label: "商品锚点",
      type: "select",
      options: ["bottom_center", "center", "bottom_left", "bottom_right"],
    },
  ],
};

type Tab = "materials" | "groups" | "packs" | "gaps";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "操作未完成";
}
function codes(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function ClassificationEditor({
  asset,
  onSaved,
}: {
  asset: LibraryAsset;
  onSaved: () => void;
}) {
  const [mediaKind, setMediaKind] = useState(asset.mediaKind ?? "");
  const [roles, setRoles] = useState<string[]>(asset.materialRoles);
  const [capability, setCapability] = useState<ExecutionCapability>(
    asset.executionCapability,
  );
  const mutation = useMutation({
    mutationFn: () =>
      assetLibraryApi.updateClassification(asset.assetCode, {
        media_kind: mediaKind || undefined,
        material_roles: roles,
        execution_capability: capability,
      }),
    onSuccess: onSaved,
  });
  const toggle = (role: string) =>
    setRoles((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    );
  return (
    <section className="asset-detail-panel">
      <SectionHeader kicker={asset.assetCode} title={asset.title} />
      <div className="wb-form-grid">
        <label className="wb-field">
          <span>媒体类型</span>
          <select
            className="wb-input"
            value={mediaKind}
            onChange={(event) => setMediaKind(event.target.value)}
          >
            <option value="">待确认</option>
            {MEDIA_KINDS.map((kind) => (
              <option key={kind}>{kind}</option>
            ))}
          </select>
        </label>
        <label className="wb-field">
          <span>执行能力</span>
          <select
            className="wb-input"
            value={capability}
            onChange={(event) =>
              setCapability(event.target.value as ExecutionCapability)
            }
          >
            {[
              "unclassified",
              "maitu_bound",
              "local_only",
              "reference_only",
              "unavailable",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <div className="wb-field wide">
          <span>业务角色</span>
          <div className="asset-role-options">
            {ROLES.map((role) => (
              <label key={role}>
                <input
                  type="checkbox"
                  checked={roles.includes(role)}
                  onChange={() => toggle(role)}
                />
                {role}
              </label>
            ))}
          </div>
        </div>
      </div>
      {mutation.error ? (
        <InlineNotice tone="danger" title="无法保存分类">
          {message(mutation.error)}
        </InlineNotice>
      ) : null}
      <div className="wb-form-actions">
        <button
          type="button"
          className="wb-button wb-button-primary"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          <Save size={14} aria-hidden="true" />
          保存分类
        </button>
      </div>
    </section>
  );
}

function defaultConstraintParameters(kind: string): Record<string, unknown> {
  if (kind === "provide_named_region")
    return { name: "safe_zone", x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
  if (kind === "table_surface")
    return {
      name: "table_surface",
      x: 0.1,
      y: 0.58,
      width: 0.8,
      height: 0.28,
      product_role: "product_display",
      product_anchor: "bottom_center",
    };
  if (kind === "allowed_region" || kind === "forbidden_region")
    return { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
  if (kind === "require_named_region") return { region: "safe_zone" };
  if (
    kind === "above_role" ||
    kind === "below_role" ||
    kind === "avoid_overlap"
  )
    return { role: "digital_human" };
  if (kind === "align_anchor")
    return { anchor: "bottom_center", region: "table_surface" };
  if (kind === "crop_policy") return { policy: "contain" };
  if (kind === "rotation_policy") return { policy: "forbid" };
  if (kind === "loop_policy") return { policy: "required" };
  if (kind === "mute_policy") return { policy: "unmuted" };
  return {};
}

function RegionPreview({
  parameters,
}: {
  parameters: Record<string, unknown>;
}) {
  const values = ["x", "y", "width", "height"].map((key) =>
    typeof parameters[key] === "number"
      ? parameters[key]
      : Number(parameters[key]),
  );
  if (values.some((value) => !Number.isFinite(value))) return null;
  const [x, y, width, height] = values.map((value) =>
    Math.min(1, Math.max(0, value)),
  );
  return (
    <div className="asset-region-preview" aria-label="归一化区域预览">
      <span
        style={{
          left: `${x * 100}%`,
          top: `${y * 100}%`,
          width: `${Math.min(width, 1 - x) * 100}%`,
          height: `${Math.min(height, 1 - y) * 100}%`,
        }}
      />
    </div>
  );
}

function ConstraintParameters({
  rule,
  onChange,
}: {
  rule: ConstraintRule;
  onChange: (parameters: Record<string, unknown>) => void;
}) {
  const fields = CONSTRAINT_PARAMETERS[rule.kind] ?? [];
  const set = (key: string, value: string | number | undefined) => {
    const next = { ...rule.parameters };
    if (value === undefined || value === "") delete next[key];
    else next[key] = value;
    onChange(next);
  };
  const value = (key: string): string => {
    const parameter = rule.parameters[key];
    return typeof parameter === "string" || typeof parameter === "number"
      ? String(parameter)
      : "";
  };
  const hasGeometry = [
    "allowed_region",
    "forbidden_region",
    "provide_named_region",
    "table_surface",
  ].includes(rule.kind);
  return (
    <div className="asset-constraint-parameters">
      {fields.length ? (
        <div className="asset-constraint-fields">
          {fields.map((field) => (
            <label key={field.key}>
              <span>{field.label}</span>
              {field.type === "role" ? (
                <select
                  className="wb-input"
                  aria-label={`约束参数：${field.label}`}
                  value={value(field.key)}
                  onChange={(event) => set(field.key, event.target.value)}
                >
                  <option value="">选择角色</option>
                  {ROLES.map((role) => (
                    <option key={role}>{role}</option>
                  ))}
                </select>
              ) : field.type === "select" ? (
                <select
                  className="wb-input"
                  aria-label={`约束参数：${field.label}`}
                  value={value(field.key)}
                  onChange={(event) => set(field.key, event.target.value)}
                >
                  {field.options?.map((option) => (
                    <option key={option}>{option}</option>
                  ))}
                </select>
              ) : (
                <input
                  className="wb-input"
                  aria-label={`约束参数：${field.label}`}
                  type={field.type}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={value(field.key)}
                  onChange={(event) => {
                    if (field.type === "number") {
                      const nextValue = event.target.value;
                      set(
                        field.key,
                        nextValue === ""
                          ? undefined
                          : Number.isFinite(Number(nextValue))
                            ? Number(nextValue)
                            : undefined,
                      );
                    } else set(field.key, event.target.value);
                  }}
                />
              )}
            </label>
          ))}
        </div>
      ) : (
        <small>该规则不需要额外参数。</small>
      )}
      {hasGeometry ? <RegionPreview parameters={rule.parameters} /> : null}
    </div>
  );
}

function constraintSummary(rule: ConstraintRule): string {
  const parameters = Object.entries(rule.parameters)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
  return `${CONSTRAINT_LABELS[rule.kind] ?? rule.kind} · ${rule.hard ? "硬" : "软"}${parameters ? ` · ${parameters}` : ""}`;
}

function ConstraintEditor({ assetCode }: { assetCode: string }) {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({
    queryKey: ["assets", "constraint-profile", assetCode],
    queryFn: () => assetLibraryApi.getConstraintProfile(assetCode),
    retry: false,
  });
  const revisionsQuery = useQuery({
    queryKey: ["assets", "constraint-profile", assetCode, "revisions"],
    queryFn: () => assetLibraryApi.listConstraintProfileRevisions(assetCode),
    enabled: Boolean(profileQuery.data),
    retry: false,
  });
  const [rules, setRules] = useState<ConstraintRule[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!loaded && profileQuery.data) {
      setRules(profileQuery.data.constraints);
      setLoaded(true);
    }
  }, [loaded, profileQuery.data]);
  const mutation = useMutation({
    mutationFn: () => assetLibraryApi.writeConstraintProfile(assetCode, rules),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["assets", "constraint-profile", assetCode],
        }),
        queryClient.invalidateQueries({
          queryKey: ["assets", "constraint-profile", assetCode, "revisions"],
        }),
      ]);
    },
  });
  const update = (index: number, field: keyof ConstraintRule, value: unknown) =>
    setRules((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item,
      ),
    );
  return (
    <section className="asset-detail-panel">
      <SectionHeader kicker="CONSTRAINT PROFILE" title="位置与图层约束" />
      <div className="asset-constraint-list">
        {rules.map((rule, index) => (
          <div key={`${rule.kind}:${index}`} className="asset-constraint-row">
            <div className="asset-constraint-heading">
              <label>
                <span>约束类型</span>
                <select
                  className="wb-input"
                  value={rule.kind}
                  onChange={(event) => {
                    const kind = event.target.value;
                    setRules((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index
                          ? {
                              ...item,
                              kind,
                              parameters: defaultConstraintParameters(kind),
                            }
                          : item,
                      ),
                    );
                  }}
                >
                  {CONSTRAINT_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {CONSTRAINT_LABELS[kind] ?? kind}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={rule.hard}
                  onChange={(event) =>
                    update(index, "hard", event.target.checked)
                  }
                />
                硬约束
              </label>
            </div>
            <ConstraintParameters
              rule={rule}
              onChange={(parameters) => update(index, "parameters", parameters)}
            />
            <button
              type="button"
              className="wb-icon-button"
              title="删除约束"
              onClick={() =>
                setRules((current) =>
                  current.filter((_, itemIndex) => itemIndex !== index),
                )
              }
            >
              删除
            </button>
          </div>
        ))}
      </div>
      <div className="wb-form-actions">
        <button
          type="button"
          className="wb-button"
          onClick={() =>
            setRules((current) => [
              ...current,
              { kind: "preserve_aspect_ratio", hard: true, parameters: {} },
            ])
          }
        >
          <Plus size={14} aria-hidden="true" />
          添加约束
        </button>
        <button
          type="button"
          className="wb-button wb-button-primary"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          <Save size={14} aria-hidden="true" />
          保存新修订
        </button>
      </div>
      {mutation.error ? (
        <InlineNotice tone="danger" title="约束保存失败">
          {message(mutation.error)}
        </InlineNotice>
      ) : null}
      {revisionsQuery.data?.length ? (
        <div className="asset-revision-history">
          <strong>约束修订历史</strong>
          {revisionsQuery.data.map((revision, index) => {
            const prior = revisionsQuery.data?.[index + 1];
            const currentRules = revision.constraints.map(constraintSummary);
            const priorRules = prior?.constraints.map(constraintSummary) ?? [];
            const added = currentRules.filter(
              (rule) => !priorRules.includes(rule),
            );
            const removed = priorRules.filter(
              (rule) => !currentRules.includes(rule),
            );
            return (
              <div key={revision.revisionNumber}>
                <small>
                  r{revision.revisionNumber}
                  {revision.revisionNumber === profileQuery.data?.revisionNumber
                    ? " · 当前"
                    : ""}{" "}
                  · {revision.profileCode} ·{" "}
                  {revision.fingerprintSha256.slice(0, 12)}
                </small>
                {currentRules.map((rule) => (
                  <small key={rule}>{rule}</small>
                ))}
                {prior ? (
                  <small>
                    与 r{prior.revisionNumber} 差异：
                    {added.length ? `新增 ${added.join("；")}` : ""}
                    {added.length && removed.length ? "；" : ""}
                    {removed.length ? `移除 ${removed.join("；")}` : ""}
                    {!added.length && !removed.length ? "无结构化变化" : ""}
                  </small>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
      {revisionsQuery.error ? (
        <InlineNotice tone="warning" title="约束修订历史暂不可用">
          {message(revisionsQuery.error)}
        </InlineNotice>
      ) : null}
    </section>
  );
}

function SelectionPreviewPanel() {
  const [role, setRole] = useState<string>("background");
  const [carrier, setCarrier] = useState<"live_room" | "rendered_video">(
    "live_room",
  );
  const preview = useMutation({
    mutationFn: () =>
      assetLibraryApi.previewSelection({ role, carrier_kind: carrier }),
  });
  return (
    <section className="asset-detail-panel">
      <SectionHeader kicker="SELECTION PREVIEW" title="选材解释" />
      <div className="wb-form-grid">
        <label className="wb-field">
          <span>所需角色</span>
          <select
            className="wb-input"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {ROLES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="wb-field">
          <span>目标载体</span>
          <select
            className="wb-input"
            value={carrier}
            onChange={(event) =>
              setCarrier(event.target.value as "live_room" | "rendered_video")
            }
          >
            <option value="live_room">直播间草稿</option>
            <option value="rendered_video">成片渲染</option>
          </select>
        </label>
      </div>
      <div className="wb-form-actions">
        <button
          type="button"
          className="wb-button wb-button-primary"
          disabled={preview.isPending}
          onClick={() => preview.mutate()}
        >
          <Search size={14} aria-hidden="true" />
          预览候选
        </button>
      </div>
      {preview.data ? (
        <div className="asset-selection-preview">
          <div>
            <strong>候选 {preview.data.candidates.length}</strong>
            {preview.data.candidates.map((candidate) => (
              <article key={candidate.assetCode}>
                <code>{candidate.assetCode}</code>
                <span>{candidate.title}</span>
                <b>{candidate.score}</b>
                <small>
                  {candidate.reasons.join(" / ")}
                  {candidate.constraintProfile
                    ? ` · ${candidate.constraintProfile.profileCode} r${candidate.constraintProfile.revisionNumber}`
                    : ""}
                  {candidate.qualifiedEffectRefs.length
                    ? ` · 效果 ${candidate.qualifiedEffectRefs.map((effect) => `${effect.effectCode} r${effect.revisionNumber}`).join(", ")}`
                    : ""}
                </small>
              </article>
            ))}
          </div>
          <div>
            <strong>排除 {preview.data.excluded.length}</strong>
            {preview.data.excluded.map((candidate) => (
              <article key={candidate.assetCode}>
                <code>{candidate.assetCode}</code>
                <span>{candidate.title}</span>
                <small>{candidate.exclusionCodes.join(" / ")}</small>
              </article>
            ))}
          </div>
          <InlineNotice tone="warning" title="尚未验证门禁">
            {preview.data.unverifiedGates.join(" / ")}
          </InlineNotice>
        </div>
      ) : null}
      {preview.error ? (
        <InlineNotice tone="danger" title="选材预览失败">
          {message(preview.error)}
        </InlineNotice>
      ) : null}
    </section>
  );
}

function AssetRelationsPanel({
  asset,
  groups,
  packs,
  gaps,
}: {
  asset: LibraryAsset;
  groups: Awaited<ReturnType<typeof assetLibraryApi.listGroups>>;
  packs: MaterialPack[];
  gaps: AssetGap[];
}) {
  const effectsQuery = useQuery({
    queryKey: ["assets", "effects", asset.assetCode],
    queryFn: () => assetLibraryApi.listEffectSummaries(asset.assetCode),
    retry: false,
  });
  const groupRelations = groups.filter((group) =>
    group.assetCodes.includes(asset.assetCode),
  );
  const packRelations = packs.filter((pack) =>
    pack.resolvedAssetCodes.includes(asset.assetCode),
  );
  const gapRelations = gaps.filter(
    (gap) =>
      gap.resolutionAssetCode === asset.assetCode ||
      gap.alternativeAssetCodes.includes(asset.assetCode),
  );
  const effects = effectsQuery.data ?? [];
  const eligibleEffect = effects.find(
    (effect) => effect.automaticRecommendationEligible,
  );
  const recommendation = effectRecommendation(effects, eligibleEffect);
  return (
    <section className="asset-detail-panel">
      <SectionHeader kicker="EFFECTS AND RELATIONS" title="效果与关系" />
      <div className="asset-summary-list">
        <div>
          <span>
            <strong>自动推荐资格</strong>
            <small>{recommendation.detail}</small>
          </span>
          <StatusBadge label={recommendation.label} tone={recommendation.tone} />
        </div>
        {effectsQuery.isError ? (
          <InlineNotice tone="warning" title="效果归因不可用">
            效果归因数据暂时不可读取，已禁用自动推荐。
          </InlineNotice>
        ) : null}
        {effects.map((effect) => (
          <EffectSummaryRow key={`${effect.effectCode}:r${effect.revisionNumber}`} effect={effect} />
        ))}
        {groupRelations.map((group) => (
          <div key={`group:${group.groupCode}`}>
            <span>
              <strong>{group.title}</strong>
              <small>素材分组 · {group.groupCode}</small>
            </span>
            <StatusBadge label="分组成员" tone="info" />
          </div>
        ))}
        {packRelations.map((pack) => (
          <div key={`pack:${pack.packCode}`}>
            <span>
              <strong>{pack.title}</strong>
              <small>
                素材包 · {pack.packCode} · r
                {pack.publishedRevisionNumber ?? pack.revisionNumber}
              </small>
            </span>
            <StatusBadge
              label={pack.revisionStatus === "published" ? "已发布" : "草稿"}
              tone={pack.revisionStatus === "published" ? "success" : "warning"}
            />
          </div>
        ))}
        {gapRelations.map((gap) => (
          <div key={`gap:${gap.gapCode}`}>
            <span>
              <strong>{gap.title}</strong>
              <small>
                素材缺口 · {gap.gapCode} ·{" "}
                {gap.resolutionAssetCode === asset.assetCode
                  ? "固定解决素材"
                  : "备选素材"}
              </small>
            </span>
            <StatusBadge
              label={gap.status}
              tone={gap.status === "resolved" ? "success" : "warning"}
            />
          </div>
        ))}
        {!groupRelations.length &&
        !packRelations.length &&
        !gapRelations.length ? (
          <small>该素材尚未与分组、素材包或缺口建立关系。</small>
        ) : null}
      </div>
    </section>
  );
}

function effectRecommendation(
  effects: AssetEffectSummary[],
  eligibleEffect?: AssetEffectSummary,
): { label: string; detail: string; tone: "success" | "warning" | "neutral" } {
  if (eligibleEffect) {
    return {
      label: "可自动推荐",
      tone: "success",
      detail: `效果 ${eligibleEffect.effectCode} 已审核，具有关联性证据并覆盖 ${eligibleEffect.selectedSessionCount} 个场次。`,
    };
  }
  if (!effects.length) {
    return {
      label: "样本不足",
      tone: "warning",
      detail: "当前素材没有直接归因效果样本，不能自动推荐。",
    };
  }
  const minimum = effects[0].automaticRecommendationMinimumSessionCount;
  const highestSampleCount = Math.max(
    ...effects.map((effect) => effect.selectedSessionCount),
  );
  if (highestSampleCount < minimum) {
    return {
      label: "样本不足",
      tone: "warning",
      detail: `现有归因版本覆盖最多 ${highestSampleCount} 个场次，至少需要 ${minimum} 个场次才可自动推荐。`,
    };
  }
  return {
    label: "需人工判断",
    tone: "neutral",
    detail: "现有归因版本尚未同时满足审核与关联性证据要求，不能自动推荐。",
  };
}

function EffectSummaryRow({ effect }: { effect: AssetEffectSummary }) {
  const label = effect.automaticRecommendationEligible
    ? "可推荐"
    : effect.status === "approved"
      ? "证据不足"
      : "待审核";
  return (
    <div>
      <span>
        <strong>{effect.metricKey}</strong>
        <small>
          {effect.effectCode} · r{effect.revisionNumber} · {effect.evidenceLevel} · {effect.selectedSessionCount} 个场次
        </small>
      </span>
      <StatusBadge
        label={label}
        tone={effect.automaticRecommendationEligible ? "success" : "warning"}
      />
    </div>
  );
}

function BatchClassificationEditor({
  assets,
  onSaved,
}: {
  assets: LibraryAsset[];
  onSaved: () => void;
}) {
  const [assetCodes, setAssetCodes] = useState<string[]>([]);
  const [mediaKind, setMediaKind] = useState("");
  const [roles, setRoles] = useState<string[]>([]);
  const [capability, setCapability] =
    useState<ExecutionCapability>("unclassified");
  const mutation = useMutation({
    mutationFn: () =>
      assetLibraryApi.updateClassifications({
        asset_codes: assetCodes,
        media_kind: mediaKind,
        material_roles: roles,
        execution_capability: capability,
      }),
    onSuccess: () => {
      setAssetCodes([]);
      onSaved();
    },
  });
  useEffect(
    () =>
      setAssetCodes((current) =>
        current.filter((code) =>
          assets.some((asset) => asset.assetCode === code),
        ),
      ),
    [assets],
  );
  const toggle = (role: string) =>
    setRoles((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    );
  return (
    <section className="asset-detail-panel">
      <SectionHeader kicker="BULK CORRECTION" title="批量校正分类" />
      <div className="wb-form-grid">
        <label className="wb-field wide">
          <span>待校正素材</span>
          <select
            className="wb-input"
            aria-label="待校正素材"
            multiple
            value={assetCodes}
            onChange={(event) =>
              setAssetCodes(
                Array.from(
                  event.currentTarget.selectedOptions,
                  (option) => option.value,
                ),
              )
            }
          >
            {assets.map((asset) => (
              <option key={asset.assetCode} value={asset.assetCode}>
                {asset.title} · {asset.assetCode} · {asset.executionCapability}
              </option>
            ))}
          </select>
        </label>
        <label className="wb-field">
          <span>媒体类型</span>
          <select
            className="wb-input"
            value={mediaKind}
            onChange={(event) => setMediaKind(event.target.value)}
          >
            <option value="">请选择</option>
            {MEDIA_KINDS.map((kind) => (
              <option key={kind}>{kind}</option>
            ))}
          </select>
        </label>
        <label className="wb-field">
          <span>执行能力</span>
          <select
            className="wb-input"
            value={capability}
            onChange={(event) =>
              setCapability(event.target.value as ExecutionCapability)
            }
          >
            {[
              "unclassified",
              "maitu_bound",
              "local_only",
              "reference_only",
              "unavailable",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <div className="wb-field wide">
          <span>业务角色</span>
          <div className="asset-role-options">
            {ROLES.map((role) => (
              <label key={role}>
                <input
                  type="checkbox"
                  checked={roles.includes(role)}
                  onChange={() => toggle(role)}
                />
                {role}
              </label>
            ))}
          </div>
        </div>
      </div>
      <div className="wb-form-actions">
        <button
          type="button"
          className="wb-button wb-button-primary"
          disabled={!assetCodes.length || !mediaKind || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          <Save size={14} aria-hidden="true" />
          校正 {assetCodes.length} 个素材
        </button>
      </div>
      {mutation.error ? (
        <InlineNotice tone="danger" title="批量校正失败">
          {message(mutation.error)}
        </InlineNotice>
      ) : null}
    </section>
  );
}

function MaterialTab({
  assets,
  groups,
  packs,
  gaps,
}: {
  assets: LibraryAsset[];
  groups: Awaited<ReturnType<typeof assetLibraryApi.listGroups>>;
  packs: MaterialPack[];
  gaps: AssetGap[];
}) {
  const queryClient = useQueryClient();
  const [selectedCode, setSelectedCode] = useState("");
  const [query, setQuery] = useState("");
  const [onlyUnclassified, setOnlyUnclassified] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [filename, setFilename] = useState("");
  const create = useMutation({
    mutationFn: () =>
      assetLibraryApi.createAsset({
        title,
        original_filename: filename,
        asset_type: "IMG",
        material_roles: [],
        execution_capability: "local_only",
      }),
    onSuccess: (created) => {
      setSelectedCode(created.assetCode);
      setShowCreate(false);
      setTitle("");
      setFilename("");
      void queryClient.invalidateQueries({ queryKey: ["assets", "library"] });
    },
  });
  const filtered = useMemo(
    () =>
      assets.filter(
        (item) =>
          `${item.assetCode} ${item.title} ${item.materialRoles.join(" ")}`
            .toLowerCase()
            .includes(query.toLowerCase()) &&
          (!onlyUnclassified ||
            item.executionCapability === "unclassified" ||
            !item.mediaKind),
      ),
    [assets, query, onlyUnclassified],
  );
  const selected =
    assets.find((item) => item.assetCode === selectedCode) ?? filtered[0];
  return (
    <div className="asset-library-layout">
      <section className="wb-section">
        <SectionHeader
          kicker="MATERIAL LIBRARY"
          title="素材"
          actions={
            <button
              type="button"
              className="wb-button wb-button-primary"
              onClick={() => setShowCreate((value) => !value)}
            >
              <Plus size={14} aria-hidden="true" />
              新建素材
            </button>
          }
        />
        {showCreate ? (
          <form
            className="asset-inline-form"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (title.trim() && filename.trim()) create.mutate();
            }}
          >
            <label className="wb-field">
              <span>名称</span>
              <input
                className="wb-input"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label className="wb-field">
              <span>文件名</span>
              <input
                className="wb-input"
                value={filename}
                onChange={(event) => setFilename(event.target.value)}
              />
            </label>
            <button
              className="wb-button wb-button-primary"
              disabled={create.isPending}
            >
              创建
            </button>
          </form>
        ) : null}
        <label className="asset-search">
          <Search size={15} aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="筛选素材编码、名称或角色"
          />
        </label>
        <label className="wb-field">
          <input
            type="checkbox"
            checked={onlyUnclassified}
            onChange={(event) => setOnlyUnclassified(event.target.checked)}
          />
          仅看待确认分类
        </label>
        <div className="asset-list">
          {filtered.map((item) => (
            <button
              key={item.assetCode}
              type="button"
              className={
                selected?.assetCode === item.assetCode ? "active" : undefined
              }
              onClick={() => setSelectedCode(item.assetCode)}
            >
              <span>
                <strong>{item.title}</strong>
                <code>{item.assetCode}</code>
                <small>
                  {item.mediaKind ?? "媒体类型待确认"} ·{" "}
                  {item.materialRoles.join(" / ") || "业务角色待确认"}
                </small>
              </span>
              <StatusBadge
                label={item.executionCapability}
                tone={
                  item.executionCapability === "maitu_bound"
                    ? "success"
                    : item.executionCapability === "unclassified"
                      ? "warning"
                      : "neutral"
                }
              />
            </button>
          ))}
        </div>
        {!filtered.length ? (
          <EmptyBlock icon={Boxes} title="尚无匹配素材" />
        ) : null}
      </section>
      <div>
        <BatchClassificationEditor
          assets={filtered}
          onSaved={() =>
            void queryClient.invalidateQueries({
              queryKey: ["assets", "library"],
            })
          }
        />
        {selected ? (
          <>
            <ClassificationEditor
              key={selected.assetCode}
              asset={selected}
              onSaved={() =>
                void queryClient.invalidateQueries({
                  queryKey: ["assets", "library"],
                })
              }
            />
            <ConstraintEditor
              key={`constraints:${selected.assetCode}`}
              assetCode={selected.assetCode}
            />
            <AssetRelationsPanel
              asset={selected}
              groups={groups}
              packs={packs}
              gaps={gaps}
            />
            <SelectionPreviewPanel />
          </>
        ) : (
          <>
            <EmptyBlock
              icon={Boxes}
              title="选择一个素材"
              detail="创建或同步素材后可设置分类与约束。"
            />
            <SelectionPreviewPanel />
          </>
        )}
      </div>
    </div>
  );
}

function GroupsTab({
  groups,
  assets,
}: {
  groups: Awaited<ReturnType<typeof assetLibraryApi.listGroups>>;
  assets: LibraryAsset[];
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [assetCodes, setAssetCodes] = useState("");
  const [selectedGroupCode, setSelectedGroupCode] = useState("");
  const [memberCodes, setMemberCodes] = useState<string[]>([]);
  const selected =
    groups.find((group) => group.groupCode === selectedGroupCode) ?? groups[0];
  useEffect(() => {
    if (selected && selected.groupCode !== selectedGroupCode)
      setSelectedGroupCode(selected.groupCode);
  }, [selected, selectedGroupCode]);
  useEffect(() => {
    if (selected) setMemberCodes(selected.assetCodes);
  }, [selected?.groupCode, selected?.assetCodes.join(",")]);
  const create = useMutation({
    mutationFn: () =>
      assetLibraryApi.createGroup({ title, asset_codes: codes(assetCodes) }),
    onSuccess: (group) => {
      setTitle("");
      setAssetCodes("");
      setSelectedGroupCode(group.groupCode);
      void queryClient.invalidateQueries({ queryKey: ["assets", "groups"] });
    },
  });
  const replace = useMutation({
    mutationFn: () =>
      assetLibraryApi.replaceGroupMembers(selectedGroupCode, memberCodes),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["assets", "groups"] }),
  });
  const toggleMember = (assetCode: string) =>
    setMemberCodes((current) =>
      current.includes(assetCode)
        ? current.filter((code) => code !== assetCode)
        : [...current, assetCode],
    );
  return (
    <div className="asset-library-layout">
      <section className="wb-section">
        <SectionHeader kicker="MULTI-MEMBERSHIP" title="素材分组" />
        <form
          className="asset-stack-form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (title.trim()) create.mutate();
          }}
        >
          <label className="wb-field">
            <span>分组名称</span>
            <input
              className="wb-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>初始素材编码（逗号或换行分隔）</span>
            <textarea
              className="wb-textarea"
              value={assetCodes}
              onChange={(event) => setAssetCodes(event.target.value)}
            />
          </label>
          <button
            className="wb-button wb-button-primary"
            disabled={create.isPending}
          >
            <FolderPlus size={14} aria-hidden="true" />
            创建分组
          </button>
        </form>
        {create.error ? (
          <InlineNotice tone="danger" title="分组创建失败">
            {message(create.error)}
          </InlineNotice>
        ) : null}
        <div className="asset-group-list">
          {groups.map((group) => (
            <button
              type="button"
              key={group.groupCode}
              className={
                group.groupCode === selected?.groupCode ? "active" : undefined
              }
              onClick={() => setSelectedGroupCode(group.groupCode)}
            >
              <span>
                <strong>{group.title}</strong>
                <code>{group.groupCode}</code>
                <small>{group.assetCodes.join("、") || "尚无成员"}</small>
              </span>
              <StatusBadge label={`${group.assetCount} 项`} tone="info" />
            </button>
          ))}
        </div>
        {!groups.length ? (
          <EmptyBlock icon={FolderPlus} title="尚无分组" />
        ) : null}
      </section>
      <section className="wb-section">
        {selected ? (
          <>
            <SectionHeader kicker={selected.groupCode} title="分组成员" />
            <div className="asset-group-member-list">
              {assets.map((asset) => (
                <label key={asset.assetCode}>
                  <input
                    type="checkbox"
                    checked={memberCodes.includes(asset.assetCode)}
                    onChange={() => toggleMember(asset.assetCode)}
                  />
                  <span>
                    <strong>{asset.title}</strong>
                    <small>
                      {asset.assetCode} ·{" "}
                      {asset.materialRoles.join(" / ") || "未分类"}
                    </small>
                  </span>
                </label>
              ))}
            </div>
            <div className="wb-form-actions">
              <button
                type="button"
                className="wb-button wb-button-primary"
                disabled={replace.isPending}
                onClick={() => replace.mutate()}
              >
                <Save size={14} aria-hidden="true" />
                更新成员
              </button>
            </div>
            {replace.error ? (
              <InlineNotice tone="danger" title="分组成员未更新">
                {message(replace.error)}
              </InlineNotice>
            ) : null}
          </>
        ) : (
          <EmptyBlock icon={FolderPlus} title="选择一个分组" />
        )}
      </section>
    </div>
  );
}

function PackEntryList({
  entries,
  onRemove,
}: {
  entries: MaterialPack["entries"];
  onRemove: (index: number) => void;
}) {
  if (!entries.length) return null;
  return (
    <ul className="asset-entry-list">
      {entries.map((item, index) => (
        <li key={`${item.selection_kind}:${item.selection_code}:${index}`}>
          <code>
            {item.selection_kind}:{item.selection_code}
          </code>
          <small>
            {item.material_role ?? "未限定角色"} · {item.mode} ·{" "}
            {item.min_occurrences} 至 {item.max_occurrences ?? "不限"} 次 ·{" "}
            {item.applicable_scope.kind}
            {item.alternative_set_key
              ? ` · 备选组 ${item.alternative_set_key}`
              : ""}
          </small>
          <button type="button" title="删除" onClick={() => onRemove(index)}>
            删除
          </button>
        </li>
      ))}
    </ul>
  );
}

function packEntrySummary(entry: MaterialPack["entries"][number]): string {
  return `${entry.material_role ? `${entry.material_role}:` : ""}${entry.mode}:${entry.selection_kind}:${entry.selection_code} (${entry.min_occurrences}-${entry.max_occurrences ?? "*"})`;
}

function PackEntryFields({
  packKind,
  packRole,
  onAdd,
}: {
  packKind: MaterialPack["packKind"];
  packRole?: string;
  onAdd: (entry: MaterialPack["entries"][number]) => void;
}) {
  const [kind, setKind] =
    useState<MaterialPack["entries"][number]["selection_kind"]>("group");
  const [code, setCode] = useState("");
  const [role, setRole] = useState(packRole ?? "background");
  const [mode, setMode] =
    useState<MaterialPack["entries"][number]["mode"]>("optional");
  const [minimum, setMinimum] = useState("0");
  const [maximum, setMaximum] = useState("");
  const [scopeKind, setScopeKind] =
    useState<MaterialPack["entries"][number]["applicable_scope"]["kind"]>(
      "whole_room",
    );
  const [scopeValues, setScopeValues] = useState("");
  const [alternativeSetKey, setAlternativeSetKey] = useState("");
  const min = Math.max(0, Number(minimum) || 0);
  const max = maximum.trim() ? Number(maximum) : undefined;
  const occurrenceValid =
    (mode === "optional" || min >= 1) &&
    (max === undefined || (Number.isInteger(max) && max >= min && max >= 1));
  const add = () => {
    if (
      !code.trim() ||
      !occurrenceValid ||
      (mode === "alternative" && !alternativeSetKey.trim())
    )
      return;
    const scopeCodes = codes(scopeValues);
    if (scopeKind !== "whole_room" && !scopeCodes.length) return;
    onAdd({
      selection_kind: kind,
      selection_code: code.trim(),
      material_role: packKind === "classification" ? packRole : role,
      mode,
      min_occurrences: min,
      max_occurrences: max,
      applicable_scope: {
        kind: scopeKind,
        scene_types: scopeKind === "scene_types" ? scopeCodes : [],
        scene_codes: scopeKind === "scene_codes" ? scopeCodes : [],
      },
      pack_constraints: [],
      alternative_set_key:
        mode === "alternative" ? alternativeSetKey.trim() : undefined,
    });
    setCode("");
    setMinimum("0");
    setMaximum("");
    setScopeValues("");
    setAlternativeSetKey("");
  };
  return (
    <div className="asset-stack-form">
      <div className="asset-pack-entry">
        <select
          className="wb-input"
          value={kind}
          onChange={(event) => setKind(event.target.value as typeof kind)}
        >
          <option value="group">分组</option>
          <option value="asset">素材</option>
          {packKind === "total" ? (
            <option value="category_pack">分类包</option>
          ) : null}
        </select>
        <input
          className="wb-input"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder={
            kind === "group"
              ? "AG-GRP-*"
              : kind === "category_pack"
                ? "AG-PACK-*"
                : "AG-IMG-*"
          }
        />
        {packKind === "total" ? (
          <select
            className="wb-input"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {ROLES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        ) : (
          <small>{packRole}</small>
        )}
        <select
          className="wb-input"
          value={mode}
          onChange={(event) => setMode(event.target.value as typeof mode)}
        >
          <option value="required">必须</option>
          <option value="optional">可选</option>
          <option value="alternative">备选</option>
        </select>
        <input
          className="wb-input"
          type="number"
          min="0"
          value={minimum}
          onChange={(event) => setMinimum(event.target.value)}
          aria-label="最少出现次数"
        />
        <input
          className="wb-input"
          type="number"
          min="1"
          value={maximum}
          onChange={(event) => setMaximum(event.target.value)}
          placeholder="最多"
          aria-label="最多出现次数"
        />
      </div>
      <div className="asset-pack-entry">
        <select
          className="wb-input"
          value={scopeKind}
          onChange={(event) =>
            setScopeKind(event.target.value as typeof scopeKind)
          }
        >
          <option value="whole_room">全房间</option>
          <option value="scene_types">场景类型</option>
          <option value="scene_codes">场景编码</option>
        </select>
        {scopeKind !== "whole_room" ? (
          <input
            className="wb-input"
            value={scopeValues}
            onChange={(event) => setScopeValues(event.target.value)}
            placeholder="多个值用逗号或换行分隔"
          />
        ) : (
          <small>适用于全房间</small>
        )}
        {mode === "alternative" ? (
          <input
            className="wb-input"
            value={alternativeSetKey}
            onChange={(event) => setAlternativeSetKey(event.target.value)}
            placeholder="备选集合标识"
          />
        ) : null}
        <button
          type="button"
          className="wb-button"
          disabled={
            !code.trim() ||
            !occurrenceValid ||
            (scopeKind !== "whole_room" && !codes(scopeValues).length) ||
            (mode === "alternative" && !alternativeSetKey.trim())
          }
          onClick={add}
        >
          添加条目
        </button>
      </div>
    </div>
  );
}

function ExclusiveRoles({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <div className="asset-role-options">
      {ROLES.map((role) => (
        <label key={role}>
          <input
            type="checkbox"
            checked={value.includes(role)}
            onChange={() =>
              onChange(
                value.includes(role)
                  ? value.filter((item) => item !== role)
                  : [...value, role],
              )
            }
          />
          排他 {role}
        </label>
      ))}
    </div>
  );
}

function PackRevisionEditor({
  pack,
  onSaved,
}: {
  pack: MaterialPack;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [entries, setEntries] = useState<MaterialPack["entries"]>(pack.entries);
  const [exclusiveRoles, setExclusiveRoles] = useState(pack.exclusiveRoles);
  const revisions = useQuery({
    queryKey: ["assets", "packs", pack.packCode, "revisions"],
    queryFn: () => assetLibraryApi.listPackRevisions(pack.packCode),
  });
  const previousRevision = revisions.data?.find(
    (revision) => revision.revisionNumber === pack.revisionNumber - 1,
  );
  const currentEntries = new Set(pack.entries.map(packEntrySummary));
  const previousEntries = new Set(
    previousRevision?.entries.map(packEntrySummary) ?? [],
  );
  const addedEntries = [...currentEntries].filter(
    (entry) => !previousEntries.has(entry),
  );
  const removedEntries = [...previousEntries].filter(
    (entry) => !currentEntries.has(entry),
  );
  useEffect(() => {
    setEntries(pack.entries);
    setExclusiveRoles(pack.exclusiveRoles);
  }, [pack.packCode, pack.revisionNumber, pack.entries, pack.exclusiveRoles]);
  const revise = useMutation({
    mutationFn: () =>
      assetLibraryApi.createPackRevision(pack.packCode, {
        expected_revision: pack.revisionNumber,
        entries,
        ...(exclusiveRoles.length || pack.exclusiveRoles.length
          ? { exclusive_roles: exclusiveRoles }
          : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["assets", "packs"] });
      void queryClient.invalidateQueries({
        queryKey: ["assets", "packs", pack.packCode, "revisions"],
      });
      onSaved();
    },
  });
  return (
    <section className="asset-detail-panel">
      <SectionHeader
        kicker={`${pack.packCode} · r${pack.revisionNumber + 1}`}
        title="创建素材包新修订"
      />
      <p className="asset-revision-note">
        保存时分组和分类包都会展开为明确素材编码；已确认直播间始终使用冻结快照。
      </p>
      <PackEntryFields
        packKind={pack.packKind}
        packRole={pack.role}
        onAdd={(entry) => setEntries((current) => [...current, entry])}
      />
      <ExclusiveRoles value={exclusiveRoles} onChange={setExclusiveRoles} />
      <PackEntryList
        entries={entries}
        onRemove={(index) =>
          setEntries((current) =>
            current.filter((_, itemIndex) => itemIndex !== index),
          )
        }
      />
      <div className="wb-form-actions">
        <button
          type="button"
          className="wb-button wb-button-primary"
          disabled={!entries.length || revise.isPending}
          onClick={() => revise.mutate()}
        >
          <Save size={14} aria-hidden="true" />
          创建 r{pack.revisionNumber + 1}
        </button>
      </div>
      {revise.error ? (
        <InlineNotice tone="danger" title="素材包修订未创建">
          {message(revise.error)}
        </InlineNotice>
      ) : null}
      {previousRevision ? (
        <div className="asset-revision-diff">
          <strong>与 r{previousRevision.revisionNumber} 差异</strong>
          {addedEntries.length ? (
            <small>新增：{addedEntries.join("；")}</small>
          ) : null}
          {removedEntries.length ? (
            <small>移除：{removedEntries.join("；")}</small>
          ) : null}
          {!addedEntries.length && !removedEntries.length ? (
            <small>条目没有结构化变化。</small>
          ) : null}
        </div>
      ) : null}
      <div className="asset-revision-history">
        <strong>修订历史</strong>
        {revisions.isLoading ? (
          <small>正在读取历史...</small>
        ) : (
          (revisions.data?.map((revision) => (
            <small key={revision.revisionNumber}>
              r{revision.revisionNumber} · {revision.status} ·{" "}
              {revision.entries.length} 个条目 ·{" "}
              {revision.fingerprintSha256.slice(0, 12)}
            </small>
          )) ?? null)
        )}
        {revisions.error ? <small>修订历史暂不可用</small> : null}
      </div>
    </section>
  );
}

function PacksTab({
  groups,
  packs,
}: {
  groups: Awaited<ReturnType<typeof assetLibraryApi.listGroups>>;
  packs: MaterialPack[];
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [packKind, setPackKind] =
    useState<MaterialPack["packKind"]>("classification");
  const [role, setRole] = useState<string>("background");
  const [entries, setEntries] = useState<MaterialPack["entries"]>([]);
  const [exclusiveRoles, setExclusiveRoles] = useState<string[]>([]);
  const [selectedPackCode, setSelectedPackCode] = useState("");
  const selectedPack =
    packs.find((item) => item.packCode === selectedPackCode) ?? packs[0];
  useEffect(() => {
    if (selectedPack && selectedPack.packCode !== selectedPackCode)
      setSelectedPackCode(selectedPack.packCode);
  }, [selectedPack, selectedPackCode]);
  const create = useMutation({
    mutationFn: () =>
      assetLibraryApi.createPack({
        title,
        pack_kind: packKind,
        role: packKind === "classification" ? role : undefined,
        entries,
        exclusive_roles: exclusiveRoles,
      }),
    onSuccess: (created) => {
      setTitle("");
      setEntries([]);
      setExclusiveRoles([]);
      setSelectedPackCode(created.packCode);
      void queryClient.invalidateQueries({ queryKey: ["assets", "packs"] });
    },
  });
  const publish = useMutation({
    mutationFn: (packCode: string) => assetLibraryApi.publishPack(packCode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["assets", "packs"] });
    },
  });
  return (
    <div className="asset-library-layout">
      <section className="wb-section">
        <SectionHeader kicker="MATERIAL PACK" title="素材包" />
        <div className="asset-stack-form">
          <label className="wb-field">
            <span>素材包名称</span>
            <input
              className="wb-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>素材包类型</span>
            <select
              className="wb-input"
              value={packKind}
              onChange={(event) => {
                setPackKind(event.target.value as MaterialPack["packKind"]);
                setEntries([]);
              }}
            >
              <option value="classification">分类素材包</option>
              <option value="total">总体素材包</option>
            </select>
          </label>
          {packKind === "classification" ? (
            <label className="wb-field">
              <span>唯一角色</span>
              <select
                className="wb-input"
                value={role}
                onChange={(event) => setRole(event.target.value)}
              >
                {ROLES.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          ) : null}
          <PackEntryFields
            packKind={packKind}
            packRole={role}
            onAdd={(entry) => setEntries((current) => [...current, entry])}
          />
          <ExclusiveRoles value={exclusiveRoles} onChange={setExclusiveRoles} />
          <PackEntryList
            entries={entries}
            onRemove={(index) =>
              setEntries((current) =>
                current.filter((_, itemIndex) => itemIndex !== index),
              )
            }
          />
          <button
            type="button"
            className="wb-button wb-button-primary"
            disabled={!title.trim() || !entries.length || create.isPending}
            onClick={() => create.mutate()}
          >
            <PackagePlus size={14} aria-hidden="true" />
            创建素材包
          </button>
          {create.error ? (
            <InlineNotice tone="danger" title="素材包创建失败">
              {message(create.error)}
            </InlineNotice>
          ) : null}
        </div>
      </section>
      <div>
        <section className="wb-section">
          <SectionHeader kicker="RESOLVED PREVIEW" title="解析预览" />
          {packs.length ? (
            <div className="asset-summary-list">
              {packs.map((pack) => (
                <div key={pack.packCode}>
                  <span>
                    <strong>{pack.title}</strong>
                    <code>
                      {pack.packCode} · r{pack.revisionNumber}
                    </code>
                    <small>
                      {pack.packKind === "classification"
                        ? `分类包 · ${pack.role}`
                        : "总体素材包"}{" "}
                      · 当前修订 {pack.revisionStatus}
                      {pack.publishedRevisionNumber
                        ? ` · 已发布 r${pack.publishedRevisionNumber}`
                        : " · 尚未发布"}
                    </small>
                    <small>
                      {pack.entries.map(packEntrySummary).join("；")}
                    </small>
                    <small>
                      {pack.resolvedAssetCodes.join("、") || "没有可用素材"}
                    </small>
                    {pack.exclusiveRoles.length ? (
                      <small>排他角色：{pack.exclusiveRoles.join("、")}</small>
                    ) : null}
                  </span>
                  <span className="asset-pack-actions">
                    <StatusBadge
                      label={
                        pack.revisionStatus === "published" ? "已发布" : "草稿"
                      }
                      tone={
                        pack.revisionStatus === "published"
                          ? "success"
                          : "warning"
                      }
                    />
                    <button
                      type="button"
                      className="wb-button"
                      onClick={() => setSelectedPackCode(pack.packCode)}
                    >
                      {selectedPack?.packCode === pack.packCode
                        ? "正在编辑"
                        : "新修订"}
                    </button>
                    {pack.revisionStatus === "draft" ? (
                      <button
                        type="button"
                        className="wb-button"
                        disabled={publish.isPending}
                        onClick={() => publish.mutate(pack.packCode)}
                      >
                        发布当前修订
                      </button>
                    ) : null}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyBlock
              icon={PackagePlus}
              title="尚无素材包"
              detail={
                groups.length
                  ? "可将一个或多个分组加入素材包。"
                  : "先创建素材分组或填写素材编码。"
              }
            />
          )}
          {publish.error ? (
            <InlineNotice tone="danger" title="素材包发布失败">
              {message(publish.error)}
            </InlineNotice>
          ) : null}
        </section>
        {selectedPack ? (
          <PackRevisionEditor
            key={`${selectedPack.packCode}:${selectedPack.revisionNumber}`}
            pack={selectedPack}
            onSaved={() => setSelectedPackCode(selectedPack.packCode)}
          />
        ) : null}
      </div>
    </div>
  );
}

function GapsTab({
  gaps,
  assets,
}: {
  gaps: AssetGap[];
  assets: LibraryAsset[];
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [role, setRole] = useState("background");
  const [severity, setSeverity] = useState("medium");
  const [gapType, setGapType] = useState("material_missing");
  const [impact, setImpact] = useState("");
  const [selectedAssets, setSelectedAssets] = useState<Record<string, string>>(
    {},
  );
  const [obsoleteReasons, setObsoleteReasons] = useState<
    Record<string, string>
  >({});
  const create = useMutation({
    mutationFn: () =>
      assetLibraryApi.createGap({
        title,
        role,
        severity,
        gap_type: gapType,
        impact_summary: impact || undefined,
      }),
    onSuccess: () => {
      setTitle("");
      setImpact("");
      void queryClient.invalidateQueries({ queryKey: ["assets", "gaps"] });
    },
  });
  const transition = useMutation({
    mutationFn: ({
      gapCode,
      status,
      assetCode,
      evidence,
    }: {
      gapCode: string;
      status: string;
      assetCode?: string;
      evidence?: Record<string, unknown>;
    }) =>
      assetLibraryApi.updateGap(gapCode, {
        status,
        resolution_asset_code: assetCode,
        resolution_evidence: evidence,
        actor: "material_library",
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["assets", "gaps"] }),
  });
  const candidates = (gap: AssetGap) =>
    assets.filter(
      (asset) =>
        asset.materialRoles.includes(gap.role) &&
        asset.executionCapability !== "unavailable" &&
        asset.executionCapability !== "unclassified",
    );
  return (
    <div className="asset-library-layout">
      <section className="wb-section">
        <SectionHeader kicker="ASSET GAP" title="素材缺口" />
        <form
          className="asset-stack-form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (title.trim()) create.mutate();
          }}
        >
          <label className="wb-field">
            <span>缺口描述</span>
            <input
              className="wb-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：用于桌面摆放的白葡萄酒商品图"
            />
          </label>
          <label className="wb-field">
            <span>所需角色</span>
            <select
              className="wb-input"
              value={role}
              onChange={(event) => setRole(event.target.value)}
            >
              {ROLES.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="wb-field">
            <span>缺口类型</span>
            <select
              className="wb-input"
              value={gapType}
              onChange={(event) => setGapType(event.target.value)}
            >
              {[
                ["material_missing", "缺少素材"],
                ["role_coverage", "角色覆盖"],
                ["constraint_conflict", "约束冲突"],
                ["rights_pending", "权利待定"],
                ["quality_improvement", "质量改进"],
              ].map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="wb-field">
            <span>严重度</span>
            <select
              className="wb-input"
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              {["low", "medium", "high", "critical"].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="wb-field wide">
            <span>影响说明</span>
            <textarea
              className="wb-textarea"
              value={impact}
              onChange={(event) => setImpact(event.target.value)}
            />
          </label>
          <button
            className="wb-button wb-button-primary"
            disabled={!title.trim() || create.isPending}
          >
            <TriangleAlert size={14} aria-hidden="true" />
            登记缺口
          </button>
        </form>
        {create.error ? (
          <InlineNotice tone="danger" title="无法登记缺口">
            {message(create.error)}
          </InlineNotice>
        ) : null}
      </section>
      <section className="wb-section">
        <SectionHeader kicker="GAP LIFECYCLE" title="待处理缺口" />
        {gaps.length ? (
          <div className="asset-summary-list">
            {gaps.map((gap) => {
              const usable = candidates(gap);
              const selectedAsset =
                selectedAssets[gap.gapCode] ?? gap.resolutionAssetCode ?? "";
              const obsoleteReason = obsoleteReasons[gap.gapCode] ?? "";
              const savedObsoleteReason =
                typeof gap.resolutionEvidence.obsolete_reason === "string"
                  ? gap.resolutionEvidence.obsolete_reason
                  : "";
              return (
                <div key={gap.gapCode} className="asset-gap-card">
                  <span>
                    <strong>{gap.title}</strong>
                    <code>{gap.gapCode}</code>
                    <small>
                      {gap.role} · {gap.gapType} · {gap.status}
                      {gap.impactSummary ? ` · ${gap.impactSummary}` : ""}
                    </small>
                    {gap.resolutionAssetCode ? (
                      <small>
                        已固定候选：{gap.resolutionAssetCode}
                        {gap.resolutionSnapshot.constraint_profile
                          ? " · 含约束修订快照"
                          : ""}
                      </small>
                    ) : null}
                    {gap.waivedReason ? (
                      <small>历史全局豁免原因：{gap.waivedReason}</small>
                    ) : null}
                    {savedObsoleteReason ? (
                      <small>过时原因：{savedObsoleteReason}</small>
                    ) : null}
                  </span>
                  <div className="asset-gap-actions">
                    <StatusBadge
                      label={gap.severity}
                      tone={
                        gap.severity === "critical"
                          ? "danger"
                          : gap.severity === "high"
                            ? "warning"
                            : "neutral"
                      }
                    />
                    {["open", "candidate_found"].includes(gap.status) ? (
                      <>
                        <select
                          className="wb-input"
                          aria-label={`${gap.gapCode} 候选素材`}
                          value={selectedAsset}
                          onChange={(event) =>
                            setSelectedAssets((current) => ({
                              ...current,
                              [gap.gapCode]: event.target.value,
                            }))
                          }
                        >
                          <option value="">选择角色匹配且可用的素材</option>
                          {usable.map((asset) => (
                            <option
                              key={asset.assetCode}
                              value={asset.assetCode}
                            >
                              {asset.title} · {asset.assetCode}
                            </option>
                          ))}
                        </select>
                        {gap.status === "open" ? (
                          <button
                            type="button"
                            className="wb-button"
                            disabled={!selectedAsset || transition.isPending}
                            onClick={() =>
                              transition.mutate({
                                gapCode: gap.gapCode,
                                status: "candidate_found",
                                assetCode: selectedAsset,
                              })
                            }
                          >
                            确认候选
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="wb-button wb-button-primary"
                            disabled={!selectedAsset || transition.isPending}
                            onClick={() =>
                              transition.mutate({
                                gapCode: gap.gapCode,
                                status: "resolved",
                                assetCode: selectedAsset,
                              })
                            }
                          >
                            固定解决素材
                          </button>
                        )}
                      </>
                    ) : null}
                    {gap.status !== "obsolete" ? (
                      <>
                        <input
                          className="wb-input"
                          aria-label={`${gap.gapCode} 过时原因`}
                          value={obsoleteReason}
                          onChange={(event) =>
                            setObsoleteReasons((current) => ({
                              ...current,
                              [gap.gapCode]: event.target.value,
                            }))
                          }
                          placeholder="不再适用的原因"
                        />
                        <button
                          type="button"
                          className="wb-button"
                          disabled={
                            !obsoleteReason.trim() || transition.isPending
                          }
                          onClick={() =>
                            transition.mutate({
                              gapCode: gap.gapCode,
                              status: "obsolete",
                              evidence: {
                                obsolete_reason: obsoleteReason.trim(),
                              },
                            })
                          }
                        >
                          标记过时
                        </button>
                      </>
                    ) : null}
                    <small>{gap.events.length} 条处理记录</small>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyBlock icon={TriangleAlert} title="没有开放缺口" />
        )}
        {transition.error ? (
          <InlineNotice tone="danger" title="缺口状态未更新">
            {message(transition.error)}
          </InlineNotice>
        ) : null}
      </section>
    </div>
  );
}

export function AssetLibraryPage() {
  const [tab, setTab] = useState<Tab>("materials");
  const assets = useQuery({
    queryKey: ["assets", "library"],
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
  const gaps = useQuery({
    queryKey: ["assets", "gaps"],
    queryFn: assetLibraryApi.listGaps,
  });
  const loading =
    assets.isLoading || groups.isLoading || packs.isLoading || gaps.isLoading;
  const problem = assets.error ?? groups.error ?? packs.error ?? gaps.error;
  return (
    <div>
      <div className="wb-tabs" role="tablist" aria-label="素材库视图">
        {[
          ["materials", "素材", Boxes],
          ["groups", "分组", FolderPlus],
          ["packs", "素材包", PackagePlus],
          ["gaps", "缺口", TriangleAlert],
        ].map(([key, label, Icon]) => {
          const Component = Icon as typeof Boxes;
          return (
            <button
              key={key as string}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={tab === key ? "active" : undefined}
              onClick={() => setTab(key as Tab)}
            >
              <Component size={15} aria-hidden="true" />
              {label as string}
            </button>
          );
        })}
      </div>
      {loading ? (
        <LoadingBlock />
      ) : problem ? (
        <InlineNotice tone="danger" title="素材库无法加载">
          {message(problem)}
        </InlineNotice>
      ) : tab === "materials" ? (
        <MaterialTab
          assets={assets.data ?? []}
          groups={groups.data ?? []}
          packs={packs.data ?? []}
          gaps={gaps.data ?? []}
        />
      ) : tab === "groups" ? (
        <GroupsTab groups={groups.data ?? []} assets={assets.data ?? []} />
      ) : tab === "packs" ? (
        <PacksTab groups={groups.data ?? []} packs={packs.data ?? []} />
      ) : (
        <GapsTab gaps={gaps.data ?? []} assets={assets.data ?? []} />
      )}
    </div>
  );
}
