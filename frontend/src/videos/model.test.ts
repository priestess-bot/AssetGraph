import { describe, expect, it } from "vitest";
import type { LibraryAsset } from "../assets/api";
import { isLocallyRenderableAsset } from "./model";

const VIDEO: LibraryAsset = {
  assetCode: "AG-VID-20260801-000026",
  localRelativePath: "video/product.mp4",
  title: "Product video",
  originalFilename: "product.mp4",
  assetType: "VID",
  mediaKind: "video",
  materialRoles: ["supporting_video"],
  executionCapability: "local_only",
  status: "stored",
  rightsStatus: "approved",
  classificationReviewStatus: "confirmed",
  classificationEvidence: {},
};

describe("local render asset eligibility", () => {
  it("accepts both local-only and downloaded Maitu-bound files", () => {
    expect(isLocallyRenderableAsset(VIDEO, "video")).toBe(true);
    expect(isLocallyRenderableAsset({ ...VIDEO, executionCapability: "maitu_bound" }, "video")).toBe(true);
  });

  it("rejects remote-only, unapproved, and mismatched media", () => {
    expect(isLocallyRenderableAsset({ ...VIDEO, executionCapability: "maitu_bound", localRelativePath: undefined }, "video")).toBe(false);
    expect(isLocallyRenderableAsset({ ...VIDEO, rightsStatus: "pending" }, "video")).toBe(false);
    expect(isLocallyRenderableAsset({ ...VIDEO, executionCapability: "reference_only" }, "video")).toBe(false);
    expect(isLocallyRenderableAsset(VIDEO, "audio")).toBe(false);
  });
});
