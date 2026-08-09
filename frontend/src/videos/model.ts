import type { LibraryAsset } from "../assets/api";

const LOCAL_RENDER_CAPABILITIES = new Set(["local_only", "maitu_bound"]);

export function isLocallyRenderableAsset(
  asset: LibraryAsset,
  mediaKind: "video" | "audio" | "image",
): boolean {
  return asset.mediaKind === mediaKind
    && asset.rightsStatus === "approved"
    && Boolean(asset.localRelativePath?.trim())
    && LOCAL_RENDER_CAPABILITIES.has(asset.executionCapability);
}
