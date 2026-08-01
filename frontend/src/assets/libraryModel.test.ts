import { describe, expect, it } from "vitest";
import type { ConstraintRule, LibraryAsset } from "./api";
import {
  assetMatchesQuery,
  geometryFromRules,
  rulesFromGeometry,
  setRelativeRuleHardness,
  setTablePlacement,
} from "./libraryModel";

const ASSET: LibraryAsset = {
  assetCode: "AG-VID-20260729-000016",
  displayCode: "MT-VID-0016",
  localFileCode: "VID-LOCAL-0016",
  title: "品酒大师商品视频",
  originalFilename: "wine-master.mp4",
  assetType: "VID",
  mediaKind: "video",
  materialRoles: ["supporting_video"],
  executionCapability: "local_only",
  status: "created",
  rightsStatus: "approved",
  classificationReviewStatus: "confirmed",
  classificationEvidence: {},
};

describe("asset library model", () => {
  it.each([
    "AG-VID-20260729-000016",
    "MT-VID-0016",
    "VID-LOCAL-0016",
    "品酒大师",
    "wine-master.mp4",
  ])("matches search text against names and every operator-facing identifier: %s", (query) => {
    expect(assetMatchesQuery(ASSET, query)).toBe(true);
  });

  it("round-trips managed hardness and leaves unmanaged constraint rules intact", () => {
    const rules: ConstraintRule[] = [
      { kind: "allowed_region", hard: false, parameters: { x: 0, y: 0, width: 1, height: 1, source: "analysis" } },
      { kind: "preserve_aspect_ratio", hard: false, parameters: { source: "operator" } },
      { kind: "above_role", hard: true, parameters: { role: "background", note: "keep" } },
      { kind: "below_role", hard: false, parameters: { role: "digital_human" } },
      { kind: "below_role", hard: false, parameters: { role: "decoration_foreground" } },
      { kind: "size_range", hard: false, parameters: { min_width: 0.2, max_width: 0.8 } },
      { kind: "avoid_overlap", hard: true, parameters: { target_role: "promotion_text" } },
    ];

    expect(rulesFromGeometry(geometryFromRules(rules))).toEqual(rules);
  });

  it("changes only the chosen relative rule between must and prefer", () => {
    const rules: ConstraintRule[] = [
      { kind: "allowed_region", hard: true, parameters: { x: 0, y: 0, width: 1, height: 1 } },
      { kind: "above_role", hard: true, parameters: { role: "background" } },
      { kind: "below_role", hard: false, parameters: { role: "digital_human" } },
      { kind: "scale_range", hard: false, parameters: { min: 0.5, max: 1 } },
    ];
    const changed = setRelativeRuleHardness(
      geometryFromRules(rules),
      "below",
      "digital_human",
      true,
    );
    const serialized = rulesFromGeometry(changed);

    expect(serialized.find((rule) => rule.kind === "below_role")?.hard).toBe(true);
    expect(serialized.find((rule) => rule.kind === "above_role")?.hard).toBe(true);
    expect(serialized.find((rule) => rule.kind === "scale_range")).toEqual(rules[3]);
  });

  it("keeps one background-above rule for table placement and preserves its hardness", () => {
    const rules: ConstraintRule[] = [
      { kind: "allowed_region", hard: true, parameters: { rect: [0, 0, 1, 1] } },
      { kind: "require_named_region", hard: true, parameters: { region: "table_surface" } },
      { kind: "above_role", hard: false, parameters: { role: "background" } },
      { kind: "above_role", hard: true, parameters: { role: "background" } },
    ];
    const serialized = rulesFromGeometry(geometryFromRules(rules));
    const backgroundRules = serialized.filter(
      (rule) => rule.kind === "above_role" && rule.parameters.role === "background",
    );

    expect(backgroundRules).toEqual([
      { kind: "above_role", hard: true, parameters: { role: "background" } },
    ]);
    expect(serialized.find((rule) => rule.kind === "allowed_region")?.parameters).toEqual({ rect: [0, 0, 1, 1] });
  });

  it("removes only a background relation injected by table placement", () => {
    const tableOnly: ConstraintRule[] = [
      { kind: "allowed_region", hard: true, parameters: { x: 0, y: 0, width: 1, height: 1 } },
      { kind: "require_named_region", hard: true, parameters: { region: "table_surface" } },
    ];
    const injected = geometryFromRules(tableOnly);
    expect(injected.tableInjectedBackground).toBe(true);
    expect(setTablePlacement(injected, false).aboveRoles).toEqual([]);

    const explicit = geometryFromRules([
      ...tableOnly,
      { kind: "above_role", hard: false, parameters: { role: "background" } },
    ]);
    expect(explicit.tableInjectedBackground).toBe(false);
    expect(setTablePlacement(explicit, false).aboveRoles).toEqual([
      { role: "background", hard: false },
    ]);
  });

  it.each([
    ["pin_layer_top", "top"],
    ["pin_layer_bottom", "bottom"],
  ] as const)("normalizes legacy soft %s to a valid hard pin", (kind, layer) => {
    const rules: ConstraintRule[] = [
      { kind: "allowed_region", hard: true, parameters: { x: 0, y: 0, width: 1, height: 1 } },
      { kind, hard: false, parameters: { source: "template" } },
    ];
    const geometry = geometryFromRules(rules);

    expect(geometry.layer).toBe(layer);
    expect(rulesFromGeometry(geometry)).toEqual([
      rules[0],
      { kind, hard: true, parameters: { source: "template" } },
    ]);
  });

  it("round-trips the rule that prevents a video from becoming the highest layer", () => {
    const rules: ConstraintRule[] = [
      { kind: "allowed_region", hard: true, parameters: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 } },
      { kind: "preserve_aspect_ratio", hard: true, parameters: {} },
      { kind: "forbid_layer_top", hard: true, parameters: {} },
    ];

    const geometry = geometryFromRules(rules);

    expect(geometry.forbidTop).toBe(true);
    expect(rulesFromGeometry(geometry)).toEqual(rules);
  });
});
