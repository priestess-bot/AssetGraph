import type { ConstraintRule, LibraryAsset, MaterialRole } from "./api";

export const MATERIAL_ROLES: MaterialRole[] = [
  "background",
  "set_surface",
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

export interface RelativeRoleRule {
  role: MaterialRole;
  hard: boolean;
}

export interface Geometry {
  x: number;
  y: number;
  width: number;
  height: number;
  preserveAspect: boolean;
  layer: "normal" | "top" | "bottom";
  forbidTop: boolean;
  aboveRoles: RelativeRoleRule[];
  belowRoles: RelativeRoleRule[];
  onTable: boolean;
  tableInjectedBackground: boolean;
  allowedRegionHard: boolean;
  preserveAspectHard: boolean;
  tableHard: boolean;
  sourceRules: ConstraintRule[];
}

export const DEFAULT_GEOMETRY: Geometry = {
  x: 0.1,
  y: 0.1,
  width: 0.8,
  height: 0.8,
  preserveAspect: true,
  layer: "normal",
  forbidTop: false,
  aboveRoles: [],
  belowRoles: [],
  onTable: false,
  tableInjectedBackground: false,
  allowedRegionHard: true,
  preserveAspectHard: true,
  tableHard: true,
  sourceRules: [],
};

type ManagedRuleKey =
  | "allowed-region"
  | "preserve-aspect"
  | "layer"
  | "forbid-top"
  | "table"
  | `above:${MaterialRole}`
  | `below:${MaterialRole}`;

function roleFromRule(rule: ConstraintRule): MaterialRole | undefined {
  const role = rule.parameters.role ?? rule.parameters.target_role;
  return typeof role === "string" && MATERIAL_ROLES.includes(role as MaterialRole)
    ? (role as MaterialRole)
    : undefined;
}

function managedRuleKey(rule: ConstraintRule): ManagedRuleKey | undefined {
  if (rule.kind === "allowed_region") return "allowed-region";
  if (rule.kind === "preserve_aspect_ratio") return "preserve-aspect";
  if (rule.kind === "pin_layer_top" || rule.kind === "pin_layer_bottom") return "layer";
  if (rule.kind === "forbid_layer_top") return "forbid-top";
  if (rule.kind === "require_named_region" && rule.parameters.region === "table_surface") return "table";
  const role = roleFromRule(rule);
  if (role && rule.kind === "above_role") return `above:${role}`;
  if (role && rule.kind === "below_role") return `below:${role}`;
  return undefined;
}

function uniqueRelativeRules(rules: ConstraintRule[], kind: "above_role" | "below_role"): RelativeRoleRule[] {
  const result: RelativeRoleRule[] = [];
  for (const rule of rules) {
    if (rule.kind !== kind) continue;
    const role = roleFromRule(rule);
    if (role && !result.some((item) => item.role === role)) result.push({ role, hard: rule.hard });
  }
  return result;
}

function regionValues(rule: ConstraintRule | undefined): Pick<Geometry, "x" | "y" | "width" | "height"> {
  const parameters = rule?.parameters ?? {};
  const rect = Array.isArray(parameters.rect) ? parameters.rect : [];
  return {
    x: typeof parameters.x === "number" ? parameters.x : typeof rect[0] === "number" ? rect[0] : DEFAULT_GEOMETRY.x,
    y: typeof parameters.y === "number" ? parameters.y : typeof rect[1] === "number" ? rect[1] : DEFAULT_GEOMETRY.y,
    width: typeof parameters.width === "number" ? parameters.width : typeof rect[2] === "number" ? rect[2] : DEFAULT_GEOMETRY.width,
    height: typeof parameters.height === "number" ? parameters.height : typeof rect[3] === "number" ? rect[3] : DEFAULT_GEOMETRY.height,
  };
}

export function geometryFromRules(rules: ConstraintRule[]): Geometry {
  const sourceRules = rules.map((rule) => ({ ...rule, parameters: { ...rule.parameters } }));
  const regionRule = sourceRules.find((rule) => rule.kind === "allowed_region");
  const preserveRule = sourceRules.find((rule) => rule.kind === "preserve_aspect_ratio");
  const topRule = sourceRules.find((rule) => rule.kind === "pin_layer_top");
  const bottomRule = sourceRules.find((rule) => rule.kind === "pin_layer_bottom");
  const forbidTopRule = sourceRules.find((rule) => rule.kind === "forbid_layer_top");
  const tableRule = sourceRules.find(
    (rule) => rule.kind === "require_named_region" && rule.parameters.region === "table_surface",
  );
  const aboveRoles = uniqueRelativeRules(sourceRules, "above_role");
  const tableInjectedBackground = Boolean(tableRule) && !aboveRoles.some((item) => item.role === "background");
  if (tableInjectedBackground) {
    aboveRoles.push({ role: "background", hard: true });
  }

  return {
    ...regionValues(regionRule),
    preserveAspect: Boolean(preserveRule),
    layer: topRule ? "top" : bottomRule ? "bottom" : "normal",
    forbidTop: Boolean(forbidTopRule),
    aboveRoles,
    belowRoles: uniqueRelativeRules(sourceRules, "below_role"),
    onTable: Boolean(tableRule),
    tableInjectedBackground,
    allowedRegionHard: regionRule?.hard ?? true,
    preserveAspectHard: preserveRule?.hard ?? true,
    tableHard: tableRule?.hard ?? true,
    sourceRules,
  };
}

function roleParameters(original: ConstraintRule | undefined, role: MaterialRole): Record<string, unknown> {
  const parameters = { ...(original?.parameters ?? {}) };
  if ("target_role" in parameters && !("role" in parameters)) parameters.target_role = role;
  else parameters.role = role;
  return parameters;
}

function allowedRegionParameters(original: ConstraintRule | undefined, value: Geometry): Record<string, unknown> {
  const parameters = { ...(original?.parameters ?? {}) };
  if (Array.isArray(parameters.rect) && !("x" in parameters || "y" in parameters || "width" in parameters || "height" in parameters)) {
    parameters.rect = [value.x, value.y, value.width, value.height];
  } else {
    Object.assign(parameters, { x: value.x, y: value.y, width: value.width, height: value.height });
  }
  return parameters;
}

function desiredRules(value: Geometry): Map<ManagedRuleKey, ConstraintRule> {
  const desired = new Map<ManagedRuleKey, ConstraintRule>();
  desired.set("allowed-region", {
    kind: "allowed_region",
    hard: value.allowedRegionHard,
    parameters: { x: value.x, y: value.y, width: value.width, height: value.height },
  });
  if (value.preserveAspect) {
    desired.set("preserve-aspect", {
      kind: "preserve_aspect_ratio",
      hard: value.preserveAspectHard,
      parameters: {},
    });
  }
  if (value.layer !== "normal") {
    desired.set("layer", {
      kind: value.layer === "top" ? "pin_layer_top" : "pin_layer_bottom",
      hard: true,
      parameters: {},
    });
  }
  if (value.forbidTop && value.layer !== "top") {
    desired.set("forbid-top", {
      kind: "forbid_layer_top",
      hard: true,
      parameters: {},
    });
  }
  for (const item of value.aboveRoles) {
    desired.set(`above:${item.role}`, {
      kind: "above_role",
      hard: value.onTable && item.role === "background" ? true : item.hard,
      parameters: { role: item.role },
    });
  }
  if (value.onTable && !desired.has("above:background")) {
    desired.set("above:background", {
      kind: "above_role",
      hard: true,
      parameters: { role: "background" },
    });
  }
  for (const item of value.belowRoles) {
    desired.set(`below:${item.role}`, {
      kind: "below_role",
      hard: item.hard,
      parameters: { role: item.role },
    });
  }
  if (value.onTable) {
    desired.set("table", {
      kind: "require_named_region",
      hard: value.tableHard,
      parameters: { region: "table_surface" },
    });
  }
  return desired;
}

function mergeManagedRule(original: ConstraintRule | undefined, next: ConstraintRule, key: ManagedRuleKey, value: Geometry): ConstraintRule {
  let parameters = { ...(original?.parameters ?? {}), ...next.parameters };
  if (key === "allowed-region") parameters = allowedRegionParameters(original, value);
  if (key.startsWith("above:") || key.startsWith("below:")) {
    parameters = roleParameters(original, (key.split(":")[1] ?? "background") as MaterialRole);
  }
  return { kind: next.kind, hard: next.hard, parameters };
}

export function rulesFromGeometry(value: Geometry): ConstraintRule[] {
  const desired = desiredRules(value);
  const emitted = new Set<ManagedRuleKey>();
  const result: ConstraintRule[] = [];

  for (const sourceRule of value.sourceRules) {
    const key = managedRuleKey(sourceRule);
    if (!key) {
      result.push(sourceRule);
      continue;
    }
    if (emitted.has(key)) continue;
    emitted.add(key);
    const next = desired.get(key);
    if (next) result.push(mergeManagedRule(sourceRule, next, key, value));
  }

  for (const [key, next] of desired) {
    if (!emitted.has(key)) result.push(mergeManagedRule(undefined, next, key, value));
  }
  return result;
}

export function setRelativeRuleHardness(
  value: Geometry,
  direction: "above" | "below",
  role: MaterialRole,
  hard: boolean,
): Geometry {
  const key = direction === "above" ? "aboveRoles" : "belowRoles";
  return {
    ...value,
    [key]: value[key].map((item) => (item.role === role ? { ...item, hard } : item)),
  };
}

export function setTablePlacement(value: Geometry, enabled: boolean): Geometry {
  if (!enabled) {
    return {
      ...value,
      onTable: false,
      tableInjectedBackground: false,
      aboveRoles: value.tableInjectedBackground
        ? value.aboveRoles.filter((item) => item.role !== "background")
        : value.aboveRoles,
    };
  }
  const hasBackground = value.aboveRoles.some((item) => item.role === "background");
  return {
    ...value,
    onTable: true,
    tableInjectedBackground: !hasBackground,
    layer: value.layer === "bottom" ? "normal" : value.layer,
    belowRoles: value.belowRoles.filter((item) => item.role !== "background"),
    aboveRoles: hasBackground
      ? value.aboveRoles
      : [...value.aboveRoles, { role: "background", hard: true }],
  };
}

export function assetMatchesQuery(asset: LibraryAsset, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return [asset.title, asset.originalFilename, asset.assetCode, asset.displayCode, asset.localFileCode]
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .toLowerCase()
    .includes(normalizedQuery);
}
