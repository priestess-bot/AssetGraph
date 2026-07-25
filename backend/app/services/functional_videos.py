from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainValidationError
from app.repositories.content_production import ContentProductionRepository
from app.repositories.material_library import (
    MaterialLibraryRepository,
    MaterialLibraryValidationError,
)
from app.repositories.releases import ReleaseRepository
from app.repositories.video_productions import VideoProductionRepository
from app.services.functional_content import FunctionalContentService
from app.services.releases import ReleaseService


class FunctionalVideoService:
    """Creates a rendered-video variant whose queued worker job consumes ContentProject text."""

    EDITORIAL_TIME_RATE = 1_000

    def __init__(
        self,
        connection: Connection,
        *,
        release_signing_key: bytes | None = None,
        release_signing_key_id: str | None = None,
    ):
        self.connection = connection
        self.content = FunctionalContentService(connection)
        self.production = ContentProductionRepository(connection)
        self.videos = VideoProductionRepository(connection)
        self.materials = MaterialLibraryRepository(connection)
        self._release_signing_key = release_signing_key
        self._release_signing_key_id = release_signing_key_id

    def create_plan(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        detail = self._source_detail(payload)
        if detail is None:
            raise KeyError(payload.get("project_code") or payload.get("live_room_plan_code"))
        if not detail["generated"] or not detail["story_brief"] or not detail["script"] or not detail["shot_list"]:
            raise DomainValidationError("VIDEO_CONTENT_CHAIN_REQUIRED", "Generate the ContentProject before creating a video plan")
        duration = int(payload["target_duration_seconds"])
        visual_assets, visual_selection = self._resolve_visual_assets(
            payload.get("visual_asset_codes") or [],
            group_codes=payload.get("visual_group_codes") or [],
            material_pack_codes=payload.get("visual_material_pack_codes") or [],
        )
        background_music = self._resolve_background_music_asset(
            payload.get("background_music_asset_code"),
            gain_db=payload.get("background_music_gain_db", -18.0),
        )
        sound_effect = self._resolve_sound_effect_asset(
            payload.get("sound_effect_asset_code"),
            gain_db=payload.get("sound_effect_gain_db", -9.0),
        )
        product_sticker = self._resolve_product_sticker_asset(
            payload.get("product_sticker_asset_code"),
        )
        brand_logo = self._resolve_brand_logo_asset(
            payload.get("brand_logo_asset_code"),
        )
        story, script, shots, timeline = self._compile_content(
            detail,
            duration,
            source_shot_codes=self._source_shot_codes(detail),
            source_shot_script_blocks=self._source_shot_script_blocks(detail),
            visual_assets=visual_assets,
            background_music=background_music,
            sound_effect=sound_effect,
            product_sticker=product_sticker,
            brand_logo=brand_logo,
        )
        variant = self.production.create_production_variant(
            project_code=detail["project_code"], project_revision=int(detail["revision_number"]),
            story_brief_code=detail["story_brief"]["story_brief_code"], story_brief_revision=int(detail["story_brief"]["revision_number"]),
            script_revision_code=detail["script"]["script_revision_code"], shot_list_revision_code=detail["shot_list"]["shot_list_revision_code"],
            carrier_kind="rendered_video",
            branch_target={
                "delivery": "local_render",
                "title": payload.get("title") or detail["title"],
                "source_live_room_plan_code": detail.get("source_live_room_plan_code"),
            },
            configuration={
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "target_duration_seconds": duration,
                "source_live_room_plan_code": detail.get("source_live_room_plan_code"),
            },
            material_snapshot_ref={
                "source": "asset_library_local_video_assets.v1" if visual_assets else "baseline_verified_video_assets.v1",
                "asset_codes": self._selected_material_codes(shots),
                "assets": visual_assets,
                "visual_selection": visual_selection,
                "brand_logo": brand_logo,
                "product_sticker": product_sticker,
                "background_music": background_music,
                "sound_effect": sound_effect,
            },
            constraint_snapshot_ref=self._video_constraint_snapshot(
                visual_assets=visual_assets,
                product_sticker=product_sticker,
                brand_logo=brand_logo,
            ),
            actor_id=actor_id, producer_strategy_revision="functional-video.v1",
        )
        variant = self.production.confirm_production_variant_revision(variant["variant_code"], revision_number=int(variant["revision_number"]), actor_id=actor_id)
        job = self.videos.create({"topic": detail["generation_goal"], "target_duration_seconds": duration})
        # Keep the Worker input tied to the exact editable timeline revision that created it.
        shots["production_timeline"] = deepcopy(timeline)
        seeded = self.videos.seed_content_project_job(job["job_code"], story_brief=story, script=script, shot_list=shots)
        if seeded is None:
            raise RuntimeError("created video job cannot be seeded")
        self.production.bind_video_production_job(job_code=job["job_code"], variant_code=variant["variant_code"], variant_revision=int(variant["revision_number"]), actor_id=actor_id)
        render_profile = {
            "schema_version": "functional-render-profile.v1", "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "subtitle": "ass", "audio": "local_tts",
            "visual_asset_mode": "asset_library_local_video_assets" if visual_assets else "baseline_verified_video_assets",
            "visual_asset_codes": [asset["asset_code"] for asset in visual_assets],
            "visual_assets": [
                {
                    "asset_code": asset["asset_code"],
                    "checksum_sha256": asset["checksum_sha256"],
                }
                for asset in visual_assets
            ],
            "visual_selection": visual_selection,
            "brand_logo": (
                {
                    "asset_code": brand_logo["asset_code"],
                    "checksum_sha256": brand_logo["checksum_sha256"],
                }
                if brand_logo
                else None
            ),
            "product_sticker": (
                {
                    "asset_code": product_sticker["asset_code"],
                    "checksum_sha256": product_sticker["checksum_sha256"],
                }
                if product_sticker
                else None
            ),
            "background_music": (
                {
                    "asset_code": background_music["asset_code"],
                    "checksum_sha256": background_music["checksum_sha256"],
                    "gain_db": background_music["gain_db"],
                }
                if background_music
                else None
            ),
            "sound_effect": (
                {
                    "asset_code": sound_effect["asset_code"],
                    "checksum_sha256": sound_effect["checksum_sha256"],
                    "gain_db": sound_effect["gain_db"],
                }
                if sound_effect
                else None
            ),
            "target_duration_seconds": duration,
            "source_live_room_plan_code": detail.get("source_live_room_plan_code"),
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code = self._next_code(cursor)
            cursor.execute(
                """INSERT INTO functional_video_plans (plan_code, project_code, variant_code, video_job_code, title, production_timeline, render_profile)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (code, detail["project_code"], variant["variant_code"], job["job_code"], payload.get("title") or detail["title"], Jsonb(timeline), Jsonb(render_profile)),
            )
            row = cursor.fetchone()
            cursor.execute(
                """INSERT INTO functional_video_timeline_revisions
                   (plan_id, revision_number, production_timeline, actor_id)
                   VALUES (%s, %s, %s, %s)""",
                (row["id"], int(row["timeline_revision"]), Jsonb(timeline), actor_id),
            )
            self._persist_timeline_segments(
                cursor,
                plan_id=row["id"],
                plan_code=code,
                timeline_revision=int(row["timeline_revision"]),
                variant_code=variant["variant_code"],
                timeline=timeline,
                actor_id=actor_id,
            )
            decision_code = self._record_material_selection_decision(
                cursor,
                plan_code=code,
                project_code=detail["project_code"],
                project_revision=int(detail["revision_number"]),
                variant=variant,
                timeline_revision=int(row["timeline_revision"]),
                material_snapshot_ref=variant["material_snapshot_ref"],
                constraint_snapshot_ref=variant["constraint_snapshot_ref"],
                actor_id=actor_id,
            )
            cursor.execute(
                """UPDATE functional_video_plans
                   SET material_selection_decision_code = %s
                   WHERE id = %s
                   RETURNING *""",
                (decision_code, row["id"]),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._enrich(row)

    def _source_detail(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        live_room_plan_code = payload.get("live_room_plan_code")
        if live_room_plan_code:
            return self._live_room_source_detail(str(live_room_plan_code))
        return self.content.get_detail(str(payload["project_code"]))

    def _resolve_visual_assets(
        self,
        asset_codes: list[Any],
        *,
        group_codes: list[Any],
        material_pack_codes: list[Any],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Resolve material-library selection once and retain only immutable snapshots.

        Asset groups are intentionally mutable authoring aids. Their active member list
        is therefore expanded here and retained on the plan; published packs additionally
        retain their immutable revision fingerprint.
        """
        direct_codes = self._unique_selection_codes(
            asset_codes,
            duplicate_code="VIDEO_VISUAL_ASSET_DUPLICATE",
            label="Visual asset codes",
        )
        selected_group_codes = self._unique_selection_codes(
            group_codes,
            duplicate_code="VIDEO_VISUAL_GROUP_DUPLICATE",
            label="Visual group codes",
        )
        selected_pack_codes = self._unique_selection_codes(
            material_pack_codes,
            duplicate_code="VIDEO_VISUAL_MATERIAL_PACK_DUPLICATE",
            label="Visual material pack codes",
        )
        group_refs: list[dict[str, Any]] = []
        group_asset_codes: list[str] = []
        for group_code in selected_group_codes:
            group = self.materials.get_group(group_code)
            if group is None:
                raise DomainValidationError(
                    "VIDEO_VISUAL_GROUP_NOT_FOUND",
                    "Every selected visual material group must exist",
                    details={"group_code": group_code},
                )
            expanded_codes = list(group.get("asset_codes") or [])
            if not expanded_codes:
                raise DomainValidationError(
                    "VIDEO_VISUAL_GROUP_EMPTY",
                    "A selected visual material group must contain at least one active asset",
                    details={"group_code": group_code},
                )
            group_refs.append(
                {
                    "group_code": group_code,
                    "title": group["title"],
                    "asset_codes": expanded_codes,
                }
            )
            group_asset_codes.extend(expanded_codes)
        try:
            material_pack_refs, pack_asset_codes = self.materials.resolve_published_packs(selected_pack_codes)
        except MaterialLibraryValidationError as exc:
            raise DomainValidationError(
                "VIDEO_VISUAL_MATERIAL_PACK_INVALID",
                str(exc),
            ) from exc

        selected_codes = list(dict.fromkeys([*direct_codes, *group_asset_codes, *pack_asset_codes]))
        if len(selected_codes) > 6:
            raise DomainValidationError(
                "VIDEO_VISUAL_ASSET_LIMIT_EXCEEDED",
                "Expanded visual material selection may contain at most six unique local videos",
                details={"asset_count": len(selected_codes), "limit": 6},
            )
        assets = self._resolve_local_video_assets(selected_codes)
        selection_sources: dict[str, list[dict[str, str]]] = {}

        def add_source(asset_code: str, kind: str, code: str) -> None:
            source = {"kind": kind, "code": code}
            sources = selection_sources.setdefault(asset_code, [])
            if source not in sources:
                sources.append(source)

        for asset_code in direct_codes:
            add_source(asset_code, "loose_asset", asset_code)
        for group in group_refs:
            for asset_code in group["asset_codes"]:
                add_source(asset_code, "asset_group", str(group["group_code"]))
        for pack in material_pack_refs:
            for asset_code in pack["resolved_asset_codes"]:
                add_source(asset_code, "material_pack", str(pack["pack_code"]))
        return assets, {
            "direct_asset_codes": direct_codes,
            "group_refs": group_refs,
            "material_pack_refs": material_pack_refs,
            "asset_codes": selected_codes,
            "selection_sources": selection_sources,
        }

    @staticmethod
    def _unique_selection_codes(
        values: list[Any],
        *,
        duplicate_code: str,
        label: str,
    ) -> list[str]:
        selected_codes = [str(value).strip() for value in values if str(value).strip()]
        if len(selected_codes) != len(set(selected_codes)):
            raise DomainValidationError(duplicate_code, f"{label} must be unique")
        return selected_codes

    def _resolve_local_video_assets(self, selected_codes: list[str]) -> list[dict[str, Any]]:
        if not selected_codes:
            return []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset.asset_code, asset.asset_type, asset.media_kind,
                       asset.execution_capability, asset.local_relative_path,
                       asset.checksum_sha256, profile.profile_code AS constraint_profile_code,
                       revision.revision_number AS constraint_profile_revision,
                       revision.constraints AS constraint_profile_constraints,
                       revision.fingerprint_sha256 AS constraint_profile_fingerprint
                FROM assets AS asset
                LEFT JOIN asset_constraint_profiles AS profile ON profile.asset_id = asset.id
                LEFT JOIN asset_constraint_profile_revisions AS revision
                  ON revision.profile_id = profile.id
                 AND revision.revision_number = profile.current_revision
                WHERE asset.asset_code = ANY(%s) AND asset.deleted_at IS NULL
                """,
                (selected_codes,),
            )
            rows = cursor.fetchall()
        assets_by_code = {str(row["asset_code"]): row for row in rows}
        missing = [code for code in selected_codes if code not in assets_by_code]
        if missing:
            raise DomainValidationError(
                "VIDEO_VISUAL_ASSET_NOT_FOUND",
                "Every selected visual asset must exist in the material library",
                details={"asset_codes": missing},
            )
        resolved: list[dict[str, Any]] = []
        for code in selected_codes:
            row = assets_by_code[code]
            local_relative_path = str(row.get("local_relative_path") or "").strip()
            checksum = str(row.get("checksum_sha256") or "").strip()
            checksum_is_valid = len(checksum) == 64 and all(character in "0123456789abcdef" for character in checksum)
            path_is_safe = not Path(local_relative_path).is_absolute() and ".." not in Path(local_relative_path).parts
            if (
                str(row.get("asset_type") or "") != "VID"
                or str(row.get("media_kind") or "") != "video"
                or str(row.get("execution_capability") or "") != "local_only"
                or not local_relative_path
                or not checksum_is_valid
                or not path_is_safe
            ):
                raise DomainValidationError(
                    "VIDEO_VISUAL_ASSET_NOT_RENDERABLE",
                    "A visual asset must be a checksummed local video with a relative material path",
                    details={"asset_code": code},
                )
            resolved.append(
                {
                    "asset_code": code,
                    "relative_path": local_relative_path,
                    "checksum_sha256": checksum,
                    "constraint_profile": self._constraint_profile_from_row(row),
                }
            )
        return resolved

    def _resolve_background_music_asset(
        self,
        asset_code: Any,
        *,
        gain_db: Any,
    ) -> dict[str, Any] | None:
        code = str(asset_code or "").strip()
        if not code:
            return None
        try:
            normalized_gain = float(gain_db)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(
                "VIDEO_BACKGROUND_MUSIC_GAIN_INVALID",
                "Background music gain must be numeric",
            ) from exc
        if not -36 <= normalized_gain <= -6:
            raise DomainValidationError(
                "VIDEO_BACKGROUND_MUSIC_GAIN_INVALID",
                "Background music gain must remain between -36 dB and -6 dB",
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, asset_type, media_kind, material_roles,
                       execution_capability, local_relative_path, checksum_sha256
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (code,),
            )
            row = cursor.fetchone()
        if row is None:
            raise DomainValidationError(
                "VIDEO_BACKGROUND_MUSIC_NOT_FOUND",
                "The selected background music asset does not exist in the material library",
                details={"asset_code": code},
            )
        relative_path = str(row.get("local_relative_path") or "").strip()
        checksum = str(row.get("checksum_sha256") or "").strip()
        checksum_is_valid = len(checksum) == 64 and all(
            character in "0123456789abcdef" for character in checksum
        )
        path_is_safe = (
            bool(relative_path)
            and not Path(relative_path).is_absolute()
            and ".." not in Path(relative_path).parts
        )
        if (
            str(row.get("media_kind") or "") != "audio"
            or "background_music" not in list(row.get("material_roles") or [])
            or str(row.get("execution_capability") or "") != "local_only"
            or not checksum_is_valid
            or not path_is_safe
        ):
            raise DomainValidationError(
                "VIDEO_BACKGROUND_MUSIC_NOT_RENDERABLE",
                "Background music must be a checksummed local audio asset classified for background music",
                details={"asset_code": code},
            )
        return {
            "asset_code": code,
            "relative_path": relative_path,
            "checksum_sha256": checksum,
            "gain_db": normalized_gain,
        }

    def _resolve_sound_effect_asset(
        self,
        asset_code: Any,
        *,
        gain_db: Any,
    ) -> dict[str, Any] | None:
        code = str(asset_code or "").strip()
        if not code:
            return None
        try:
            normalized_gain = float(gain_db)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(
                "VIDEO_SOUND_EFFECT_GAIN_INVALID",
                "Sound effect gain must be numeric",
            ) from exc
        if not -24 <= normalized_gain <= 6:
            raise DomainValidationError(
                "VIDEO_SOUND_EFFECT_GAIN_INVALID",
                "Sound effect gain must remain between -24 dB and 6 dB",
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, media_kind, material_roles,
                       execution_capability, local_relative_path, checksum_sha256
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (code,),
            )
            row = cursor.fetchone()
        if row is None:
            raise DomainValidationError(
                "VIDEO_SOUND_EFFECT_NOT_FOUND",
                "The selected sound effect asset does not exist in the material library",
                details={"asset_code": code},
            )
        relative_path = str(row.get("local_relative_path") or "").strip()
        checksum = str(row.get("checksum_sha256") or "").strip()
        checksum_is_valid = len(checksum) == 64 and all(
            character in "0123456789abcdef" for character in checksum
        )
        path_is_safe = (
            bool(relative_path)
            and not Path(relative_path).is_absolute()
            and ".." not in Path(relative_path).parts
        )
        if (
            str(row.get("media_kind") or "") != "audio"
            or "sound_effect" not in list(row.get("material_roles") or [])
            or str(row.get("execution_capability") or "") != "local_only"
            or not checksum_is_valid
            or not path_is_safe
        ):
            raise DomainValidationError(
                "VIDEO_SOUND_EFFECT_NOT_RENDERABLE",
                "Sound effect must be a checksummed local audio asset classified for sound effects",
                details={"asset_code": code},
            )
        return {
            "asset_code": code,
            "relative_path": relative_path,
            "checksum_sha256": checksum,
            "gain_db": normalized_gain,
        }

    def _resolve_product_sticker_asset(self, asset_code: Any) -> dict[str, str] | None:
        code = str(asset_code or "").strip()
        if not code:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset.asset_code, asset.media_kind, asset.material_roles,
                       asset.execution_capability, asset.local_relative_path,
                       asset.checksum_sha256, profile.profile_code AS constraint_profile_code,
                       revision.revision_number AS constraint_profile_revision,
                       revision.constraints AS constraint_profile_constraints,
                       revision.fingerprint_sha256 AS constraint_profile_fingerprint
                FROM assets AS asset
                LEFT JOIN asset_constraint_profiles AS profile ON profile.asset_id = asset.id
                LEFT JOIN asset_constraint_profile_revisions AS revision
                  ON revision.profile_id = profile.id
                 AND revision.revision_number = profile.current_revision
                WHERE asset.asset_code = %s AND asset.deleted_at IS NULL
                """,
                (code,),
            )
            row = cursor.fetchone()
        if row is None:
            raise DomainValidationError(
                "VIDEO_PRODUCT_STICKER_NOT_FOUND",
                "The selected product sticker does not exist in the material library",
                details={"asset_code": code},
            )
        relative_path = str(row.get("local_relative_path") or "").strip()
        checksum = str(row.get("checksum_sha256") or "").strip()
        checksum_is_valid = len(checksum) == 64 and all(
            character in "0123456789abcdef" for character in checksum
        )
        path_is_safe = (
            bool(relative_path)
            and not Path(relative_path).is_absolute()
            and ".." not in Path(relative_path).parts
        )
        if (
            str(row.get("media_kind") or "") != "image"
            or "product_display" not in list(row.get("material_roles") or [])
            or str(row.get("execution_capability") or "") != "local_only"
            or not checksum_is_valid
            or not path_is_safe
        ):
            raise DomainValidationError(
                "VIDEO_PRODUCT_STICKER_NOT_RENDERABLE",
                "Product sticker must be a checksummed local image classified for product display",
                details={"asset_code": code},
            )
        return {
            "asset_code": code,
            "relative_path": relative_path,
            "checksum_sha256": checksum,
            "constraint_profile": self._constraint_profile_from_row(row),
        }

    def _resolve_brand_logo_asset(self, asset_code: Any) -> dict[str, Any] | None:
        code = str(asset_code or "").strip()
        if not code:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset.asset_code, asset.media_kind, asset.material_roles,
                       asset.execution_capability, asset.local_relative_path,
                       asset.checksum_sha256, profile.profile_code AS constraint_profile_code,
                       revision.revision_number AS constraint_profile_revision,
                       revision.constraints AS constraint_profile_constraints,
                       revision.fingerprint_sha256 AS constraint_profile_fingerprint
                FROM assets AS asset
                LEFT JOIN asset_constraint_profiles AS profile ON profile.asset_id = asset.id
                LEFT JOIN asset_constraint_profile_revisions AS revision
                  ON revision.profile_id = profile.id
                 AND revision.revision_number = profile.current_revision
                WHERE asset.asset_code = %s AND asset.deleted_at IS NULL
                """,
                (code,),
            )
            row = cursor.fetchone()
        if row is None:
            raise DomainValidationError(
                "VIDEO_BRAND_LOGO_NOT_FOUND",
                "The selected brand logo does not exist in the material library",
                details={"asset_code": code},
            )
        relative_path = str(row.get("local_relative_path") or "").strip()
        checksum = str(row.get("checksum_sha256") or "").strip()
        checksum_is_valid = len(checksum) == 64 and all(
            character in "0123456789abcdef" for character in checksum
        )
        path_is_safe = (
            bool(relative_path)
            and not Path(relative_path).is_absolute()
            and ".." not in Path(relative_path).parts
        )
        if (
            str(row.get("media_kind") or "") != "image"
            or "brand_title" not in list(row.get("material_roles") or [])
            or str(row.get("execution_capability") or "") != "local_only"
            or not checksum_is_valid
            or not path_is_safe
        ):
            raise DomainValidationError(
                "VIDEO_BRAND_LOGO_NOT_RENDERABLE",
                "Brand logo must be a checksummed local image classified for brand title",
                details={"asset_code": code},
            )
        return {
            "asset_code": code,
            "relative_path": relative_path,
            "checksum_sha256": checksum,
            "constraint_profile": self._constraint_profile_from_row(row),
        }

    def _live_room_source_detail(self, live_room_plan_code: str) -> dict[str, Any] | None:
        """Load the exact confirmed content chain frozen by an existing live-room Variant."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT live.plan_code AS source_live_room_plan_code,
                       project.project_code, project.title,
                       project_revision.revision_number AS project_revision_number,
                       project_revision.generation_goal,
                       story.story_brief_code, story.revision_number AS story_revision_number,
                       story.content AS story_content,
                       script.id AS script_revision_id, script.script_revision_code,
                       script.revision_number AS script_revision_number, script.title AS script_title,
                       shots.id AS shot_list_revision_id, shots.shot_list_revision_code,
                       shots.revision_number AS shot_list_revision_number
                FROM functional_live_room_plans AS live
                JOIN production_variant_revisions AS variant
                  ON variant.variant_code = live.variant_code AND variant.status = 'confirmed'
                JOIN content_project_revisions AS project_revision
                  ON project_revision.id = variant.source_project_revision_id AND project_revision.status = 'confirmed'
                JOIN content_projects AS project ON project.id = project_revision.project_id
                JOIN story_brief_revisions AS story
                  ON story.id = variant.source_story_brief_revision_id AND story.status = 'confirmed'
                JOIN content_script_revisions AS script
                  ON script.id = variant.source_script_revision_id AND script.status = 'confirmed'
                JOIN shot_list_revisions AS shots
                  ON shots.id = variant.source_shot_list_revision_id AND shots.status = 'confirmed'
                WHERE live.plan_code = %s
                """,
                (live_room_plan_code,),
            )
            source = cursor.fetchone()
            if source is None:
                return None
            cursor.execute(
                """
                SELECT block_code, module_type, content, estimated_duration_ms,
                       fact_citations, template_sources, interaction_intent, cta_intent
                FROM content_script_blocks
                WHERE script_revision_id = %s
                ORDER BY sort_order
                """,
                (source["script_revision_id"],),
            )
            blocks = cursor.fetchall()
            cursor.execute(
                """SELECT shot_code FROM shots
                   WHERE shot_list_revision_id = %s
                   ORDER BY sort_order, shot_code""",
                (source["shot_list_revision_id"],),
            )
            source_shots = cursor.fetchall()
        if not blocks:
            raise DomainValidationError(
                "VIDEO_LIVE_ROOM_SOURCE_SCRIPT_EMPTY",
                "The live-room source has no fixed script blocks to compile into a video",
            )
        if not source_shots:
            raise DomainValidationError(
                "VIDEO_LIVE_ROOM_SOURCE_SHOTS_EMPTY",
                "The live-room source has no fixed Shots to project into a video timeline",
            )
        return {
            "project_code": source["project_code"],
            "title": source["title"],
            "revision_number": int(source["project_revision_number"]),
            "generation_goal": source["generation_goal"],
            "generated": True,
            "source_live_room_plan_code": source["source_live_room_plan_code"],
            "story_brief": {
                "story_brief_code": source["story_brief_code"],
                "revision_number": int(source["story_revision_number"]),
                "content": source["story_content"],
            },
            "script": {
                "script_revision_code": source["script_revision_code"],
                "revision_number": int(source["script_revision_number"]),
                "title": source["script_title"],
                "blocks": blocks,
            },
            "shot_list": {
                "shot_list_revision_code": source["shot_list_revision_code"],
                "revision_number": int(source["shot_list_revision_number"]),
                "shots": source_shots,
            },
        }

    def list_plans(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_video_plans ORDER BY updated_at DESC, plan_code")
            rows = cursor.fetchall()
        return [self._enrich(row) for row in rows]

    def get_plan(self, plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_video_plans WHERE plan_code = %s", (plan_code,))
            row = cursor.fetchone()
        return self._enrich(row) if row else None

    def list_timeline_revisions(self, plan_code: str) -> list[dict[str, Any]] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT id FROM functional_video_plans WHERE plan_code = %s",
                (plan_code,),
            )
            plan = cursor.fetchone()
            if plan is None:
                return None
            cursor.execute(
                """SELECT revision_number, production_timeline, actor_id, created_at
                   FROM functional_video_timeline_revisions
                   WHERE plan_id = %s
                   ORDER BY revision_number DESC""",
                (plan["id"],),
            )
            return [dict(row) for row in cursor.fetchall()]

    def restore_timeline_revision(
        self,
        plan_code: str,
        source_revision: int,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any] | None:
        """Restore a historical editable timeline by creating, never mutating, a new revision."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT r.production_timeline
                   FROM functional_video_timeline_revisions r
                   JOIN functional_video_plans p ON p.id = r.plan_id
                   WHERE p.plan_code = %s AND r.revision_number = %s""",
                (plan_code, source_revision),
            )
            source = cursor.fetchone()
        if source is None:
            if self.get_plan(plan_code) is None:
                return None
            raise DomainValidationError(
                "VIDEO_TIMELINE_REVISION_NOT_FOUND",
                "The requested timeline revision does not belong to this video plan",
                details={"source_revision": source_revision},
            )
        source_timeline = dict(source["production_timeline"] or {})
        video_clips = self._timeline_video_updates(source_timeline)
        subtitle_clips = self._timeline_subtitle_updates(source_timeline)
        audio_clips = self._timeline_audio_updates(source_timeline)
        return self.update_timeline(
            plan_code,
            {
                "expected_revision": expected_revision,
                "poster_time_ms": source_timeline.get("poster_time_ms"),
                "subtitle_style": source_timeline.get("subtitle_style"),
                "video_clips": video_clips,
                "subtitle_clips": subtitle_clips,
                "audio_clips": audio_clips,
            },
            actor_id=actor_id,
        )

    def branch_plan(self, plan_code: str, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any] | None:
        """Create a queued editable branch from the exact fixed source of an existing plan."""
        source = self._branch_source(plan_code)
        if source is None:
            return None
        timeline = deepcopy(dict(source["production_timeline"] or {}))
        shot_list = self._timeline_shot_list(dict(source["job_shot_list"] or {}), timeline)
        duration = round(float(timeline.get("global_end_ms") or 0) / 1000)
        if not 30 <= duration <= 120:
            raise DomainValidationError("VIDEO_BRANCH_DURATION_INVALID", "The source timeline has an unsupported duration")
        title = str(payload.get("title") or f"{source['title']} - 分支")
        variant = self.production.create_production_variant(
            project_code=str(source["source_project_code"]),
            project_revision=int(source["source_project_revision"]),
            story_brief_code=str(source["story_brief_code"]),
            story_brief_revision=int(source["story_brief_revision"]),
            script_revision_code=str(source["script_revision_code"]),
            shot_list_revision_code=str(source["shot_list_revision_code"]),
            carrier_kind="rendered_video",
            branch_target={
                **dict(source["variant_branch_target"] or {}),
                "delivery": "local_render",
                "title": title,
                "branched_from_plan_code": plan_code,
            },
            configuration={
                **dict(source["variant_configuration"] or {}),
                "target_duration_seconds": duration,
                "branched_from_plan_code": plan_code,
            },
            material_snapshot_ref=deepcopy(dict(source["material_snapshot_ref"] or {})),
            constraint_snapshot_ref=deepcopy(dict(source["constraint_snapshot_ref"] or {})),
            actor_id=actor_id,
            producer_strategy_revision="functional-video.branch.v1",
        )
        variant = self.production.confirm_production_variant_revision(
            variant["variant_code"], revision_number=int(variant["revision_number"]), actor_id=actor_id
        )
        job = self.videos.create({"topic": source["job_topic"], "target_duration_seconds": duration})
        seeded = self.videos.seed_content_project_job(
            job["job_code"],
            story_brief=deepcopy(dict(source["job_story_brief"] or {})),
            script=deepcopy(dict(source["job_script"] or {})),
            shot_list=shot_list,
        )
        if seeded is None:
            raise RuntimeError("branched video job cannot be seeded")
        self.production.bind_video_production_job(
            job_code=job["job_code"],
            variant_code=variant["variant_code"],
            variant_revision=int(variant["revision_number"]),
            actor_id=actor_id,
        )
        profile = deepcopy(dict(source["render_profile"] or {}))
        profile["target_duration_seconds"] = duration
        profile["branched_from_plan_code"] = plan_code
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                code = self._next_code(cursor)
                cursor.execute(
                    """INSERT INTO functional_video_plans
                       (plan_code, project_code, variant_code, video_job_code, title, production_timeline, render_profile)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                    (code, source["project_code"], variant["variant_code"], job["job_code"], title, Jsonb(timeline), Jsonb(profile)),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """INSERT INTO functional_video_timeline_revisions
                       (plan_id, revision_number, production_timeline, actor_id)
                       VALUES (%s, %s, %s, %s)""",
                    (row["id"], int(row["timeline_revision"]), Jsonb(timeline), actor_id),
                )
                self._persist_timeline_segments(
                    cursor,
                    plan_id=row["id"],
                    plan_code=code,
                    timeline_revision=int(row["timeline_revision"]),
                    variant_code=variant["variant_code"],
                    timeline=timeline,
                    actor_id=actor_id,
                )
                decision_code = self._record_material_selection_decision(
                    cursor,
                    plan_code=code,
                    project_code=str(source["project_code"]),
                    project_revision=int(source["source_project_revision"]),
                    variant=variant,
                    timeline_revision=int(row["timeline_revision"]),
                    material_snapshot_ref=variant["material_snapshot_ref"],
                    constraint_snapshot_ref=variant["constraint_snapshot_ref"],
                    actor_id=actor_id,
                    branched_from_plan_code=plan_code,
                )
                cursor.execute(
                    """UPDATE functional_video_plans
                       SET material_selection_decision_code = %s
                       WHERE id = %s
                       RETURNING *""",
                    (decision_code, row["id"]),
                )
                row = cursor.fetchone()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self._enrich(row)

    def create_release_candidate(self, plan_code: str, *, actor_id: str) -> dict[str, Any]:
        """Freeze a QC-passed rendered-video plan for review, never delivery."""
        source = self._branch_source(plan_code)
        if source is None:
            if self.get_plan(plan_code) is None:
                raise KeyError(plan_code)
            raise DomainValidationError("VIDEO_RELEASE_SOURCE_INVALID", "The fixed content source for this video plan is unavailable")
        if source.get("release_code"):
            existing = self.get_plan(plan_code)
            if existing is None:
                raise KeyError(plan_code)
            return existing
        job = self.videos.get_by_code(str(source["video_job_code"]))
        if job is None:
            raise DomainValidationError("VIDEO_RELEASE_JOB_MISSING", "The associated rendered-video job no longer exists")
        quality_report = dict(job.get("quality_report") or {})
        if job["status"] != "succeeded" or quality_report.get("passed") is not True:
            raise DomainValidationError(
                "VIDEO_RELEASE_QC_REQUIRED",
                "Only a successfully rendered video with a passing quality report can create a release candidate",
                details={"job_status": job["status"], "quality_passed": quality_report.get("passed")},
            )
        video_artifact = next(
            (artifact for artifact in job.get("artifacts") or [] if artifact.get("artifact_key") == "video"),
            None,
        )
        if not video_artifact or not video_artifact.get("checksum_sha256"):
            raise DomainValidationError("VIDEO_RELEASE_ARTIFACT_MISSING", "The QC-passed video artifact is required for release")
        subject_refs = self._release_subject_refs(source)
        snapshot_artifact = self._get_or_create_release_snapshot(source, job, subject_refs)
        release = self._release_service().create_candidate(
            subject_type="production_variant",
            subject_code=str(source["variant_code"]),
            subject_revision=int(source["variant_revision"]),
            carrier_kind="rendered_video",
            subject_refs=subject_refs,
            artifact_refs=[
                {
                    "artifact_code": snapshot_artifact["artifact_code"],
                    "checksum_sha256": snapshot_artifact["checksum_sha256"],
                    "role": "rendered_video_release_snapshot",
                }
            ],
            rights_snapshot={
                "status": "pending_evidence",
                "asset_codes": self._selected_material_codes(dict(job.get("shot_list") or {})),
                "reason": "Rendered source asset rights and delivery authorization have not been collected.",
            },
            quality_snapshot={
                "schema_version": "functional-video-release-quality.v1",
                "gates": [
                    {"code": "GATE_VIDEO_QC", "status": "pass", "blocking": True},
                    {"code": "GATE_RELEASE_RIGHTS_EVIDENCE_PENDING", "status": "pending", "blocking": True},
                    {"code": "GATE_RELEASE_AUTHORIZATION_PENDING", "status": "pending", "blocking": True},
                ],
                "quality_report": quality_report,
            },
            lineage_snapshot={
                "complete": True,
                "schema_version": "functional-video-lineage.v1",
                "coverage": {
                    "content_chain": "fixed",
                    "production_timeline": "fixed",
                    "render_artifact": "fixed",
                    "rights_and_delivery": "pending",
                },
            },
            carrier_facet={
                "video_job": {"code": job["job_code"], "attempt": job["attempt"]},
                "production_timeline_ref": {
                    "revision": int(source["timeline_revision"]),
                    "fingerprint": canonical_fingerprint(source["production_timeline"]),
                },
                "render_profile": source["render_profile"],
                "video_artifact": {
                    "relative_path": video_artifact.get("relative_path"),
                    "checksum_sha256": video_artifact["checksum_sha256"],
                },
                "delivery": {"status": "not_authorized"},
            },
            created_by=actor_id,
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """UPDATE functional_video_plans
                   SET release_code = %s, release_snapshot_artifact_code = %s,
                       release_manifest_fingerprint = %s, updated_at = now()
                   WHERE id = %s AND release_code IS NULL
                   RETURNING *""",
                (
                    release["release_code"],
                    snapshot_artifact["artifact_code"],
                    release["manifest"]["manifest_fingerprint"],
                    source["id"],
                ),
            )
            updated = cursor.fetchone()
            if updated is None:
                cursor.execute("SELECT * FROM functional_video_plans WHERE id = %s", (source["id"],))
                updated = cursor.fetchone()
        self.connection.commit()
        return self._enrich(updated)

    def retry(self, plan_code: str) -> dict[str, Any] | None:
        plan = self.get_plan(plan_code)
        if plan is None:
            return None
        self.videos.retry(plan["video_job_code"])
        return self.get_plan(plan_code)

    def _branch_source(self, plan_code: str) -> dict[str, Any] | None:
        """Load only confirmed, immutable source revisions for a branch copy."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT plan.*, job.topic AS job_topic, job.story_brief AS job_story_brief,
                          job.script AS job_script, job.shot_list AS job_shot_list,
                          project.project_code AS source_project_code,
                          project.revision_number AS source_project_revision,
                          story.story_brief_code, story.revision_number AS story_brief_revision,
                          script.script_revision_code, script.revision_number AS script_revision,
                          shots.shot_list_revision_code, shots.revision_number AS shot_list_revision,
                          program.program_revision_code, program.revision_number AS program_revision,
                          variant.revision_number AS variant_revision,
                          variant.configuration AS variant_configuration,
                          variant.branch_target AS variant_branch_target,
                          variant.material_snapshot_ref, variant.constraint_snapshot_ref
                   FROM functional_video_plans AS plan
                   JOIN video_production_jobs AS job ON job.job_code = plan.video_job_code
                   JOIN production_variant_revisions AS variant
                     ON variant.variant_code = plan.variant_code AND variant.status = 'confirmed'
                   JOIN content_project_revisions AS project ON project.id = variant.source_project_revision_id
                   JOIN story_brief_revisions AS story ON story.id = variant.source_story_brief_revision_id
                   JOIN content_script_revisions AS script ON script.id = variant.source_script_revision_id
                   JOIN shot_list_revisions AS shots ON shots.id = variant.source_shot_list_revision_id
                   JOIN content_program_revisions AS program ON program.id = shots.source_program_revision_id
                   WHERE plan.plan_code = %s
                   ORDER BY variant.revision_number DESC
                   LIMIT 1""",
                (plan_code,),
            )
            source = cursor.fetchone()
        if source is None:
            return None
        for revision_key in ("source_project_revision", "story_brief_revision"):
            if int(source[revision_key]) < 1:
                raise DomainValidationError("VIDEO_BRANCH_SOURCE_INVALID", "The source content revisions are invalid")
        return source

    @staticmethod
    def _release_subject_refs(source: dict[str, Any]) -> dict[str, Any]:
        return {
            "content_project_revision": {"code": source["source_project_code"], "revision": int(source["source_project_revision"])},
            "production_variant_revision": {"code": source["variant_code"], "revision": int(source["variant_revision"])},
            "story_brief_revision": {"code": source["story_brief_code"], "revision": int(source["story_brief_revision"])},
            "script_revision": {"code": source["script_revision_code"], "revision": int(source["script_revision"])},
            "program_revision": {"code": source["program_revision_code"], "revision": int(source["program_revision"])},
            "shot_list_revision": {"code": source["shot_list_revision_code"], "revision": int(source["shot_list_revision"])},
        }

    def _get_or_create_release_snapshot(
        self,
        source: dict[str, Any],
        job: dict[str, Any],
        subject_refs: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT artifact.artifact_code, artifact.checksum_sha256, artifact.byte_size
                   FROM functional_video_plan_release_snapshots AS snapshot
                   JOIN artifact_refs AS artifact ON artifact.id = snapshot.artifact_id
                   WHERE snapshot.plan_id = %s""",
                (source["id"],),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return existing
            snapshot = {
                "schema_version": "functional-video-release-snapshot.v1",
                "plan": {
                    "plan_code": source["plan_code"],
                    "title": source["title"],
                    "timeline_revision": source["timeline_revision"],
                },
                "subject_refs": subject_refs,
                "production_timeline": source["production_timeline"],
                "render_profile": source["render_profile"],
                "video_job": {
                    "job_code": job["job_code"],
                    "attempt": job["attempt"],
                    "quality_report": job["quality_report"],
                    "artifacts": [
                        {
                            "artifact_key": artifact.get("artifact_key"),
                            "stage_name": artifact.get("stage_name"),
                            "relative_path": artifact.get("relative_path"),
                            "checksum_sha256": artifact.get("checksum_sha256"),
                            "file_size": artifact.get("file_size"),
                        }
                        for artifact in job.get("artifacts") or []
                    ],
                },
            }
            snapshot_bytes = canonical_json_bytes(snapshot)
            fingerprint = canonical_fingerprint(snapshot)
            cursor.execute(
                """SELECT * FROM artifact_refs
                   WHERE checksum_sha256 = %s AND byte_size = %s AND media_type = 'application/json'
                     AND content_addressed = true""",
                (fingerprint, len(snapshot_bytes)),
            )
            artifact = cursor.fetchone()
            if artifact is None:
                artifact_code = self._next_release_snapshot_artifact_code(cursor)
                cursor.execute(
                    """INSERT INTO artifact_refs (
                         artifact_code, artifact_kind, media_type, schema_version,
                         storage_uri, checksum_sha256, byte_size, producer_type,
                         producer_code, producer_revision, sensitivity,
                         retention_policy_code, metadata
                       ) VALUES (%s, 'rendered_video_release_snapshot', 'application/json',
                                 'functional-video-release-snapshot.v1', %s, %s, %s,
                                 'functional_video_plan', %s, %s, 'internal',
                                 'release-candidate', %s) RETURNING *""",
                    (
                        artifact_code,
                        f"assetgraph://functional-video-release-snapshots/{fingerprint}",
                        fingerprint,
                        len(snapshot_bytes),
                        source["plan_code"],
                        int(source["timeline_revision"]),
                        Jsonb({"plan_code": source["plan_code"], "snapshot_fingerprint": fingerprint, "storage_backend": "postgresql"}),
                    ),
                )
                artifact = cursor.fetchone()
            cursor.execute(
                """INSERT INTO functional_video_plan_release_snapshots
                   (plan_id, artifact_id, artifact_code, snapshot_fingerprint_sha256, snapshot)
                   VALUES (%s, %s, %s, %s, %s)""",
                (source["id"], artifact["id"], artifact["artifact_code"], fingerprint, Jsonb(snapshot)),
            )
        self.connection.commit()
        return {
            "artifact_code": artifact["artifact_code"],
            "checksum_sha256": artifact["checksum_sha256"],
            "byte_size": artifact["byte_size"],
        }

    def _release_service(self) -> ReleaseService:
        if self._release_signing_key is not None:
            key = self._release_signing_key
            key_id = self._release_signing_key_id or "functional-video-test-key"
        elif settings.manifest_signing_key is not None and settings.manifest_signing_key.get_secret_value().strip():
            key = settings.manifest_signing_key.get_secret_value().encode("utf-8")
            key_id = settings.manifest_signing_key_id
        elif settings.app_env == "local":
            key = b"assetgraph-local-functional-video-release-key-v1"
            key_id = "local-functional-video-release-key-v1"
        else:
            raise DomainValidationError("RELEASE_SIGNING_KEY_MISSING", "A release signing key is required outside the local environment")
        return ReleaseService(ReleaseRepository(self.connection), signing_key=key, signing_key_id=key_id)

    def _with_release(self, plan: dict[str, Any]) -> dict[str, Any]:
        release_code = plan.get("release_code")
        if not release_code:
            plan["release"] = None
            return plan
        release = ReleaseRepository(self.connection).get_release(str(release_code))
        if release is None:
            plan["release"] = None
            return plan
        manifest = release["manifest"]
        plan["release"] = {
            "release_code": release["release_code"],
            "status": release["status"],
            "manifest_code": manifest["manifest_code"],
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "snapshot_artifact_code": plan.get("release_snapshot_artifact_code") or "",
        }
        return plan

    @staticmethod
    def _source_shot_codes(detail: dict[str, Any]) -> list[str]:
        shot_list = detail.get("shot_list") or {}
        codes = [
            str(shot.get("shot_code") or "").strip()
            for shot in shot_list.get("shots") or []
            if isinstance(shot, dict)
        ]
        codes = list(dict.fromkeys(code for code in codes if code))
        if not codes:
            raise DomainValidationError(
                "VIDEO_SOURCE_SHOT_LIST_EMPTY",
                "A generated ContentProject must expose fixed Shots before video planning",
            )
        return codes

    @staticmethod
    def _source_shot_script_blocks(detail: dict[str, Any]) -> dict[str, list[str]]:
        shot_list = detail.get("shot_list") or {}
        result: dict[str, list[str]] = {}
        for shot in shot_list.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            shot_code = str(shot.get("shot_code") or "").strip()
            if not shot_code:
                continue
            result[shot_code] = list(
                dict.fromkeys(
                    str(code).strip()
                    for code in shot.get("script_block_codes") or []
                    if str(code).strip()
                )
            )
        return result

    @staticmethod
    def _timeline_segment_code(
        plan_code: str, timeline_revision: int, clip_code: str
    ) -> str:
        return f"VTLSEG-{plan_code}-r{timeline_revision}-{clip_code}"

    def _persist_timeline_segments(
        self,
        cursor: Any,
        *,
        plan_id: Any,
        plan_code: str,
        timeline_revision: int,
        variant_code: str,
        timeline: dict[str, Any],
        actor_id: str,
    ) -> None:
        """Freeze one TimelineSegment and ShotProjectionLink for every video clip."""
        cursor.execute(
            """SELECT source_shot_list_revision_id
               FROM production_variant_revisions
               WHERE variant_code = %s AND status = 'confirmed'
               ORDER BY revision_number DESC
               LIMIT 1""",
            (variant_code,),
        )
        variant = cursor.fetchone()
        if variant is None:
            raise DomainValidationError(
                "VIDEO_TIMELINE_VARIANT_INVALID",
                "Timeline segments require a confirmed rendered-video ProductionVariant",
                details={"variant_code": variant_code},
            )
        cursor.execute(
            """SELECT id, shot_code FROM shots
               WHERE shot_list_revision_id = %s""",
            (variant["source_shot_list_revision_id"],),
        )
        source_shots = {
            str(row["shot_code"]): row["id"] for row in cursor.fetchall()
        }
        source_script_blocks: dict[Any, list[str]] = {}
        if source_shots:
            cursor.execute(
                """SELECT source.shot_id, block.block_code
                   FROM shot_script_block_sources AS source
                   JOIN content_script_blocks AS block ON block.id = source.script_block_id
                   WHERE source.shot_id = ANY(%s)
                   ORDER BY source.shot_id, source.source_order""",
                (list(source_shots.values()),),
            )
            for row in cursor.fetchall():
                source_script_blocks.setdefault(row["shot_id"], []).append(
                    str(row["block_code"])
                )
        video_track = next(
            (
                track
                for track in timeline.get("tracks") or []
                if isinstance(track, dict) and track.get("track_kind") == "video"
            ),
            None,
        )
        if not isinstance(video_track, dict):
            raise DomainValidationError(
                "VIDEO_TIMELINE_VIDEO_TRACK_MISSING",
                "Timeline segments require a video track",
            )
        for clip in video_track.get("clips") or []:
            if not isinstance(clip, dict):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_CLIP_INVALID",
                    "Timeline video clips must be objects",
                )
            clip_code = str(clip.get("clip_code") or "").strip()
            source_shot_code = str(clip.get("source_shot_code") or "").strip()
            timing = clip.get("timeline_range") or {}
            if not clip_code or not source_shot_code or not isinstance(timing, dict):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SHOT_PROJECTION_INVALID",
                    "Every TimelineSegment needs a clip code, source Shot and timeline range",
                    details={"clip_code": clip_code or None},
                )
            source_shot_id = source_shots.get(source_shot_code)
            if source_shot_id is None:
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SOURCE_SHOT_INVALID",
                    "TimelineSegment source Shot is outside the fixed ShotList",
                    details={"clip_code": clip_code, "source_shot_code": source_shot_code},
                )
            source_script_block_codes = source_script_blocks.get(source_shot_id, [])
            try:
                start_ms = int(timing["start_ms"])
                duration_ms = int(timing["duration_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SHOT_PROJECTION_INVALID",
                    "TimelineSegment range must contain integer start and duration",
                    details={"clip_code": clip_code},
                ) from exc
            if start_ms < 0 or duration_ms <= 0:
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SHOT_PROJECTION_INVALID",
                    "TimelineSegment duration must be positive",
                    details={"clip_code": clip_code},
                )
            segment_code = self._timeline_segment_code(
                plan_code, timeline_revision, clip_code
            )
            source_range = dict(clip.get("source_range") or {})
            source_asset_file = self._timeline_segment_asset_file_snapshot(
                cursor, source_range
            )
            transform = {
                key: deepcopy(clip[key])
                for key in (
                    "fit",
                    "crop_x",
                    "crop_y",
                    "playback_rate",
                    "overlay_roles",
                    "overlay_z_order",
                    "product_sticker_layout",
                    "product_sticker_layout_suggestion",
                    "audio_roles",
                )
                if key in clip
            }
            artifact_refs = (
                [
                    {
                        "relation_role": "source_video",
                        "asset_code": source_range.get("asset_code"),
                        "checksum_sha256": source_range.get("asset_checksum_sha256"),
                        "relative_path": source_range.get("asset_relative_path"),
                        "source_start_seconds": source_range.get("start_seconds"),
                        "source_end_seconds": source_range.get("end_seconds"),
                        "asset_file": source_asset_file,
                    }
                ]
                if source_range.get("asset_code")
                else []
            )
            payload = {
                "schema_version": "functional-video-timeline-segment.v1",
                "segment_code": segment_code,
                "plan_code": plan_code,
                "timeline_revision": timeline_revision,
                "clip_code": clip_code,
                "source_shot_code": source_shot_code,
                "source_script_block_codes": source_script_block_codes,
                "timeline_range": {
                    "start_ms": start_ms,
                    "end_ms": start_ms + duration_ms,
                },
                "source_range": source_range,
                "transform": transform,
                "transition": str(clip.get("transition") or "cut"),
                "artifact_refs": artifact_refs,
            }
            fingerprint = canonical_fingerprint(payload)
            cursor.execute(
                """INSERT INTO functional_video_timeline_segments (
                       plan_id, timeline_revision, segment_code, clip_code,
                       source_shot_id, source_shot_code, timeline_start_ms,
                       source_script_block_codes, timeline_end_ms, source_range, transform, transition,
                       artifact_refs, fingerprint_sha256, created_by
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    plan_id,
                    timeline_revision,
                    segment_code,
                    clip_code,
                    source_shot_id,
                    source_shot_code,
                    start_ms,
                    Jsonb(source_script_block_codes),
                    start_ms + duration_ms,
                    Jsonb(source_range),
                    Jsonb(transform),
                    payload["transition"],
                    Jsonb(artifact_refs),
                    fingerprint,
                    actor_id,
                ),
            )
            timeline_segment = cursor.fetchone()
            if source_asset_file is not None:
                cursor.execute(
                    """INSERT INTO functional_video_timeline_segment_asset_files (
                           timeline_segment_id, asset_file_id, relation_role,
                           asset_code, file_role, bucket_name, object_key,
                           source_relative_path, mime_type, file_size, checksum_sha256
                       ) VALUES (%s, %s, 'source_video', %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        timeline_segment["id"],
                        source_asset_file["asset_file_id"],
                        source_asset_file["asset_code"],
                        source_asset_file["file_role"],
                        source_asset_file["bucket_name"],
                        source_asset_file["object_key"],
                        source_asset_file["source_relative_path"],
                        source_asset_file["mime_type"],
                        source_asset_file["file_size"],
                        source_asset_file["checksum_sha256"],
                    ),
                )
            cursor.execute(
                """INSERT INTO shot_projection_links (
                       shot_id, target_type, target_code, target_revision,
                       relation_type, applicable_start_ms, applicable_end_ms, evidence
                   ) VALUES (%s, 'timeline_segment', %s, %s, 'projects_to', %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    source_shot_id,
                    segment_code,
                    timeline_revision,
                    start_ms,
                    start_ms + duration_ms,
                    Jsonb(
                        {
                            "compiler": "functional-video.v1",
                            "plan_code": plan_code,
                            "clip_code": clip_code,
                            "timeline_revision": timeline_revision,
                            "fingerprint_sha256": fingerprint,
                        }
                    ),
                ),
            )

    @staticmethod
    def _timeline_segment_asset_file_snapshot(
        cursor: Any, source_range: dict[str, Any]
    ) -> dict[str, Any] | None:
        asset_code = str(source_range.get("asset_code") or "").strip()
        checksum = str(source_range.get("asset_checksum_sha256") or "").strip()
        if not asset_code or not VideoProductionRepository._valid_checksum(checksum):
            return None
        cursor.execute(
            """SELECT id, asset_code, file_role, bucket_name, object_key,
                      source_relative_path, mime_type, file_size, checksum_sha256
               FROM asset_files
               WHERE asset_code = %s AND checksum_sha256 = %s
               ORDER BY CASE file_role WHEN 'original' THEN 0 ELSE 1 END, created_at DESC
               LIMIT 1""",
            (asset_code, checksum),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "asset_file_id": str(row["id"]),
            "asset_code": str(row["asset_code"]),
            "file_role": str(row["file_role"]),
            "bucket_name": str(row["bucket_name"]),
            "object_key": str(row["object_key"]),
            "source_relative_path": row.get("source_relative_path"),
            "mime_type": row.get("mime_type"),
            "file_size": row.get("file_size"),
            "checksum_sha256": str(row["checksum_sha256"]),
        }

    def _timeline_segments(
        self, plan_id: Any, timeline_revision: int
    ) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT id, segment_code, clip_code, source_shot_code,
                          timeline_start_ms, timeline_end_ms, source_script_block_codes, source_range,
                          transform, transition, artifact_refs,
                          fingerprint_sha256, created_at
                   FROM functional_video_timeline_segments
                   WHERE plan_id = %s AND timeline_revision = %s
                   ORDER BY timeline_start_ms, clip_code""",
                (plan_id, timeline_revision),
            )
            segments = [dict(row) for row in cursor.fetchall()]
            if not segments:
                return []
            cursor.execute(
                """SELECT link.timeline_segment_id, link.job_attempt,
                          link.artifact_role, link.artifact_key, link.relative_path,
                          link.checksum_sha256, link.evidence, link.created_at
                   FROM functional_video_timeline_segment_execution_artifacts AS link
                   WHERE link.timeline_segment_id = ANY(%s)
                   ORDER BY link.created_at, link.artifact_role""",
                ([segment["id"] for segment in segments],),
            )
            links_by_segment: dict[Any, list[dict[str, Any]]] = {}
            for link in cursor.fetchall():
                values = dict(link)
                links_by_segment.setdefault(values.pop("timeline_segment_id"), []).append(values)
            cursor.execute(
                """SELECT source.timeline_segment_id, source.asset_file_id,
                          source.relation_role, source.asset_code, source.file_role,
                          source.bucket_name, source.object_key, source.source_relative_path,
                          source.mime_type, source.file_size, source.checksum_sha256,
                          source.created_at
                   FROM functional_video_timeline_segment_asset_files AS source
                   WHERE source.timeline_segment_id = ANY(%s)
                   ORDER BY source.created_at, source.relation_role""",
                ([segment["id"] for segment in segments],),
            )
            asset_files_by_segment: dict[Any, list[dict[str, Any]]] = {}
            for source in cursor.fetchall():
                values = dict(source)
                values["asset_file_id"] = str(values["asset_file_id"])
                asset_files_by_segment.setdefault(
                    values.pop("timeline_segment_id"), []
                ).append(values)
            for segment in segments:
                segment_id = segment.pop("id")
                segment["execution_artifact_refs"] = links_by_segment.get(segment_id, [])
                segment["source_asset_file_refs"] = asset_files_by_segment.get(segment_id, [])
            return segments

    def update_timeline(self, plan_code: str, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any] | None:
        """Apply a constrained edit and update the queued worker input atomically."""
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT * FROM functional_video_plans WHERE plan_code = %s FOR UPDATE", (plan_code,))
                plan = cursor.fetchone()
                if plan is None:
                    self.connection.rollback()
                    return None
                expected_revision = int(payload["expected_revision"])
                actual_revision = int(plan["timeline_revision"])
                if expected_revision != actual_revision:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_REVISION_CONFLICT",
                        "Timeline changed since it was loaded",
                        details={"expected_revision": expected_revision, "actual_revision": actual_revision},
                    )
                cursor.execute("SELECT * FROM video_production_jobs WHERE job_code = %s FOR UPDATE", (plan["video_job_code"],))
                job = cursor.fetchone()
                if job is None:
                    raise DomainValidationError("VIDEO_TIMELINE_JOB_MISSING", "The associated render job no longer exists")
                if job["status"] != "queued" or job["claimed_by"] is not None:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_EDIT_NOT_ALLOWED",
                        "Only an unclaimed queued render plan can be edited; create a new branch after rendering begins",
                        details={"job_status": job["status"]},
                    )
                timeline = self._apply_timeline_update(
                    dict(plan["production_timeline"] or {}),
                    payload["video_clips"],
                    payload.get("subtitle_clips") or [],
                    payload.get("audio_clips") or [],
                    payload.get("poster_time_ms"),
                    payload.get("subtitle_style"),
                )
                shot_list = self._timeline_shot_list(dict(job["shot_list"] or {}), timeline)
                total_seconds = timeline["global_end_ms"] / 1000
                profile = deepcopy(dict(plan["render_profile"] or {}))
                profile["target_duration_seconds"] = total_seconds
                next_revision = actual_revision + 1
                cursor.execute(
                    """UPDATE functional_video_plans
                       SET production_timeline = %s, render_profile = %s, timeline_revision = %s, updated_at = now()
                       WHERE id = %s""",
                    (Jsonb(timeline), Jsonb(profile), next_revision, plan["id"]),
                )
                cursor.execute(
                    """INSERT INTO functional_video_timeline_revisions
                       (plan_id, revision_number, production_timeline, actor_id)
                       VALUES (%s, %s, %s, %s)""",
                    (plan["id"], next_revision, Jsonb(timeline), actor_id),
                )
                self._persist_timeline_segments(
                    cursor,
                    plan_id=plan["id"],
                    plan_code=plan["plan_code"],
                    timeline_revision=next_revision,
                    variant_code=plan["variant_code"],
                    timeline=timeline,
                    actor_id=actor_id,
                )
                cursor.execute(
                    """UPDATE video_production_jobs
                       SET shot_list = %s, target_duration_seconds = %s, updated_at = now()
                       WHERE id = %s""",
                    (Jsonb(shot_list), round(total_seconds), job["id"]),
                )
                cursor.execute(
                    """UPDATE video_production_stages
                       SET output_payload = %s, updated_at = now()
                       WHERE job_id = %s AND stage_name = 'shot_planning'""",
                    (Jsonb(shot_list), job["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_plan(plan_code)

    def _enrich(self, row: dict[str, Any]) -> dict[str, Any]:
        plan = dict(row)
        job = self.videos.get_by_code(plan["video_job_code"])
        if job is None:
            raise RuntimeError("functional video plan refers to a missing job")
        plan.update(
            {
                "job_status": job["status"],
                "current_stage": job.get("current_stage"),
                "progress_percent": job["progress_percent"],
                "error_message": job.get("error_message"),
                "final_asset_id": job.get("final_asset_id"),
                "quality_report": dict(job.get("quality_report") or {}),
                "workflow_stages": [
                    {
                        "stage_name": stage.get("stage_name"),
                        "stage_order": stage.get("stage_order"),
                        "status": stage.get("status"),
                        "attempt": stage.get("attempt"),
                        "error_code": stage.get("error_code"),
                        "error_message": stage.get("error_message"),
                    }
                    for stage in job.get("stages") or []
                ],
            }
        )
        plan["artifacts"] = [
            {
                **artifact,
                "download_url": f"/api/video-productions/{job['job_code']}/artifacts/{artifact['artifact_key']}",
            }
            for artifact in job.get("artifacts") or []
        ]
        plan["timeline_segments"] = self._timeline_segments(
            plan["id"], int(plan["timeline_revision"])
        )
        return self._with_release(plan)

    def _record_material_selection_decision(
        self,
        cursor: Any,
        *,
        plan_code: str,
        project_code: str,
        project_revision: int,
        variant: dict[str, Any],
        timeline_revision: int,
        material_snapshot_ref: dict[str, Any],
        constraint_snapshot_ref: dict[str, Any],
        actor_id: str,
        branched_from_plan_code: str | None = None,
    ) -> str:
        """Persist one explicit, frozen selection as a reusable DecisionLog record."""

        material_snapshot = deepcopy(dict(material_snapshot_ref or {}))
        constraint_snapshot = deepcopy(dict(constraint_snapshot_ref or {}))
        decision_code = self._next_sequence_code(
            cursor,
            prefix="DEC",
            object_type="functional_decision_log",
        )
        asset_refs: list[dict[str, Any]] = []
        for asset in material_snapshot.get("assets") or []:
            if isinstance(asset, dict) and str(asset.get("asset_code") or "").strip():
                asset_refs.append(
                    {
                        "object_type": "asset",
                        "asset_code": str(asset["asset_code"]),
                        "fingerprint_sha256": str(asset.get("checksum_sha256") or ""),
                        "relation_type": "selected_visual_source",
                    }
                )
        for role in ("brand_logo", "product_sticker", "background_music", "sound_effect"):
            asset = material_snapshot.get(role)
            if isinstance(asset, dict) and str(asset.get("asset_code") or "").strip():
                asset_refs.append(
                    {
                        "object_type": "asset",
                        "asset_code": str(asset["asset_code"]),
                        "fingerprint_sha256": str(asset.get("checksum_sha256") or ""),
                        "relation_type": role,
                    }
                )
        source_refs = [
            {
                "object_type": "content_project",
                "project_code": project_code,
                "revision": project_revision,
                "relation_type": "selection_content_source",
            },
            {
                "object_type": "production_variant",
                "variant_code": str(variant["variant_code"]),
                "revision": int(variant["revision_number"]),
                "fingerprint_sha256": str(variant.get("fingerprint_sha256") or ""),
                "relation_type": "selection_output_variant",
            },
            *asset_refs,
        ]
        decision_payload = {
            "schema_version": "functional-video-material-selection-decision.v1",
            "plan_code": plan_code,
            "timeline_revision": timeline_revision,
            "actor_id": actor_id,
            "branched_from_plan_code": branched_from_plan_code,
            "material_snapshot_ref": material_snapshot,
            "constraint_snapshot_ref": constraint_snapshot,
            "selection_kind": "explicit_local_material_selection",
        }
        fingerprint = canonical_fingerprint(
            {
                "decision_code": decision_code,
                "project_code": project_code,
                "decision_type": "rendered_video_material_selection",
                "decision_payload": decision_payload,
                "source_revision_refs": source_refs,
            }
        )
        cursor.execute(
            """INSERT INTO functional_decision_logs
               (decision_code, project_code, observation, recommendation, decision_type,
                decision_payload, source_revision_refs, fingerprint_sha256)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                decision_code,
                project_code,
                f"Material selection frozen for rendered-video plan {plan_code}.",
                "Use only this frozen selection for the current plan; evaluate later branches independently.",
                "rendered_video_material_selection",
                Jsonb(decision_payload),
                Jsonb(source_refs),
                fingerprint,
            ),
        )
        return decision_code

    @staticmethod
    def _timeline_video_updates(timeline: dict[str, Any]) -> list[dict[str, Any]]:
        video = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "video"), None)
        if not isinstance(video, dict):
            raise DomainValidationError("VIDEO_TIMELINE_VIDEO_TRACK_MISSING", "Timeline has no editable video track")
        updates: list[dict[str, Any]] = []
        for clip in video.get("clips") or []:
            timeline_range = clip.get("timeline_range") or {}
            source_range = clip.get("source_range")
            source_update = (
                {
                    "source_asset_code": source_range.get("asset_code"),
                    "source_start_seconds": source_range["start_seconds"],
                    "source_end_seconds": source_range["end_seconds"],
                }
                if isinstance(source_range, dict)
                and "start_seconds" in source_range
                and "end_seconds" in source_range
                else {}
            )
            updates.append(
                {
                    "clip_code": str(clip.get("clip_code") or ""),
                    "duration_ms": int(timeline_range.get("duration_ms") or 0),
                    "transition": str(clip.get("transition") or "cut"),
                    **source_update,
                    **({"fit": str(clip["fit"])} if clip.get("fit") is not None else {}),
                    **(
                        {"crop_x": float(clip["crop_x"]), "crop_y": float(clip["crop_y"])}
                        if clip.get("crop_x") is not None and clip.get("crop_y") is not None
                        else {}
                    ),
                    **({"playback_rate": float(clip["playback_rate"])} if clip.get("playback_rate") is not None else {}),
                    **(
                        {"show_brand_logo": "brand_logo" in (clip.get("overlay_roles") or [])}
                        if clip.get("overlay_roles") is not None
                        else {}
                    ),
                    **(
                        {"show_product_sticker": "product_sticker" in (clip.get("overlay_roles") or [])}
                        if clip.get("overlay_roles") is not None
                        else {}
                    ),
                    **(
                        {
                            "product_sticker_x": float(clip["product_sticker_layout"]["x"]),
                            "product_sticker_y": float(clip["product_sticker_layout"]["y"]),
                            "product_sticker_width_ratio": float(
                                clip["product_sticker_layout"]["width_ratio"]
                            ),
                        }
                        if isinstance(clip.get("product_sticker_layout"), dict)
                        and all(
                            key in clip["product_sticker_layout"]
                            for key in ("x", "y", "width_ratio")
                        )
                        else {}
                    ),
                    **(
                        {"play_sound_effect": "sound_effect" in (clip.get("audio_roles") or [])}
                        if clip.get("audio_roles") is not None
                        else {}
                    ),
                }
            )
        return updates

    @staticmethod
    def _timeline_subtitle_updates(timeline: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a complete subtitle-edit payload when this timeline owns a subtitle track."""
        subtitle = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "subtitle"), None)
        if subtitle is None:
            return []
        if not isinstance(subtitle, dict):
            raise DomainValidationError("VIDEO_TIMELINE_SUBTITLE_TRACK_INVALID", "Timeline subtitle track is invalid")
        updates: list[dict[str, Any]] = []
        for clip in subtitle.get("clips") or []:
            updates.append(
                {
                    "clip_code": str(clip.get("clip_code") or ""),
                    "subtitle_text": str(clip.get("subtitle_text") or ""),
                    "headline_text": str(clip.get("headline_text") or ""),
                    "caption_position": str(clip.get("caption_position") or "bottom"),
                }
            )
        return updates

    @staticmethod
    def _timeline_audio_updates(timeline: dict[str, Any]) -> list[dict[str, Any]]:
        """Return complete editable voice gain state for a timeline restore."""
        audio = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "audio"), None)
        if audio is None:
            return []
        if not isinstance(audio, dict):
            raise DomainValidationError("VIDEO_TIMELINE_AUDIO_TRACK_INVALID", "Timeline audio track is invalid")
        return [
            {
                "clip_code": str(clip.get("clip_code") or ""),
                "gain_db": float(clip.get("gain_db") or 0),
            }
            for clip in audio.get("clips") or []
            if str(clip.get("clip_code") or "").startswith("VOICE-")
        ]

    @staticmethod
    def _apply_timeline_update(
        timeline: dict[str, Any],
        updates: list[dict[str, Any]],
        subtitle_updates: list[dict[str, Any]] | None = None,
        audio_updates: list[dict[str, Any]] | None = None,
        poster_time_ms: int | None = None,
        subtitle_style: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = deepcopy(timeline)
        tracks = result.get("tracks") or []
        video = next((track for track in tracks if track.get("track_kind") == "video"), None)
        if not isinstance(video, dict):
            raise DomainValidationError("VIDEO_TIMELINE_VIDEO_TRACK_MISSING", "Timeline has no editable video track")
        clips = list(video.get("clips") or [])
        current_codes = [str(clip.get("clip_code") or "") for clip in clips]
        update_codes = [str(update.get("clip_code") or "") for update in updates]
        if set(current_codes) != set(update_codes) or len(current_codes) != len(update_codes):
            raise DomainValidationError(
                "VIDEO_TIMELINE_CLIP_SET_MISMATCH",
                "Timeline edits must retain the complete current video clip set",
                details={"expected_clip_codes": current_codes},
            )
        current_by_code = {str(clip["clip_code"]): clip for clip in clips}
        cursor = 0
        ordered_clips: list[dict[str, Any]] = []
        for update in updates:
            clip = deepcopy(current_by_code[str(update["clip_code"])])
            duration = int(update["duration_ms"])
            transition = str(update.get("transition") or "cut")
            if duration < 250 or duration > 120_000 or transition not in {"cut", "fade", "fade_out"}:
                raise DomainValidationError("VIDEO_TIMELINE_INVALID_CLIP", "Timeline clip duration or transition is invalid")
            fit = update.get("fit")
            if fit is not None:
                if fit not in {"cover", "contain"}:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_FIT_INVALID",
                        "Timeline visual fit must be cover or contain",
                        details={"clip_code": clip["clip_code"]},
                    )
                clip["fit"] = fit
            crop_x = update.get("crop_x")
            crop_y = update.get("crop_y")
            if (crop_x is None) != (crop_y is None):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_CROP_POSITION_INCOMPLETE",
                    "Timeline crop position requires both x and y",
                    details={"clip_code": clip["clip_code"]},
                )
            if crop_x is not None and crop_y is not None:
                crop_x = float(crop_x)
                crop_y = float(crop_y)
                if not 0 <= crop_x <= 1 or not 0 <= crop_y <= 1:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_CROP_POSITION_INVALID",
                        "Timeline crop position must be normalized between zero and one",
                        details={"clip_code": clip["clip_code"]},
                    )
                if (clip.get("fit") or "cover") != "cover":
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_CROP_POSITION_UNSUPPORTED",
                        "Timeline crop position is available only for cover fit",
                        details={"clip_code": clip["clip_code"]},
                    )
                clip["crop_x"] = crop_x
                clip["crop_y"] = crop_y
            elif (clip.get("fit") or "cover") == "contain":
                # Contain preserves the full foreground; stale crop focus has no valid meaning.
                clip.pop("crop_x", None)
                clip.pop("crop_y", None)
            playback_rate = update.get("playback_rate")
            if playback_rate is not None:
                playback_rate = float(playback_rate)
                if not 0.5 <= playback_rate <= 2:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PLAYBACK_RATE_INVALID",
                        "Timeline playback rate must be between 0.5 and 2",
                        details={"clip_code": clip["clip_code"]},
                    )
                clip["playback_rate"] = playback_rate
            show_brand_logo = update.get("show_brand_logo")
            if show_brand_logo is not None:
                if type(show_brand_logo) is not bool:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_BRAND_LOGO_INVALID",
                        "Brand logo selection must be a boolean",
                        details={"clip_code": clip["clip_code"]},
                    )
                roles = [
                    str(role)
                    for role in clip.get("overlay_roles") or []
                    if str(role) != "brand_logo"
                ]
                if show_brand_logo:
                    roles.insert(0, "brand_logo")
                clip["overlay_roles"] = roles
            show_product_sticker = update.get("show_product_sticker")
            if show_product_sticker is not None:
                if type(show_product_sticker) is not bool:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PRODUCT_STICKER_INVALID",
                        "Product sticker selection must be a boolean",
                        details={"clip_code": clip["clip_code"]},
                    )
                roles = [str(role) for role in clip.get("overlay_roles") or [] if str(role) != "product_sticker"]
                if show_product_sticker:
                    roles.append("product_sticker")
                clip["overlay_roles"] = roles
            sticker_layout_values = (
                update.get("product_sticker_x"),
                update.get("product_sticker_y"),
                update.get("product_sticker_width_ratio"),
            )
            if any(value is not None for value in sticker_layout_values):
                if not all(value is not None for value in sticker_layout_values):
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PRODUCT_STICKER_LAYOUT_INCOMPLETE",
                        "Product sticker x, y and width ratio must be supplied together",
                        details={"clip_code": clip["clip_code"]},
                    )
                if "product_sticker" not in (clip.get("overlay_roles") or []):
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PRODUCT_STICKER_LAYOUT_UNAVAILABLE",
                        "Enable the product sticker before changing its layout",
                        details={"clip_code": clip["clip_code"]},
                    )
                sticker_x, sticker_y, sticker_width_ratio = (
                    float(value) for value in sticker_layout_values
                )
                if not 0 <= sticker_x <= 1 or not 0 <= sticker_y <= 1 or not 0.1 <= sticker_width_ratio <= 1:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PRODUCT_STICKER_LAYOUT_INVALID",
                        "Product sticker layout must remain within the canvas",
                        details={"clip_code": clip["clip_code"]},
                    )
                clip["product_sticker_layout"] = {
                    "x": sticker_x,
                    "y": sticker_y,
                    "width_ratio": sticker_width_ratio,
                }
            elif "product_sticker" not in (clip.get("overlay_roles") or []):
                clip.pop("product_sticker_layout", None)
            play_sound_effect = update.get("play_sound_effect")
            if play_sound_effect is not None:
                if type(play_sound_effect) is not bool:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SOUND_EFFECT_INVALID",
                        "Sound effect selection must be a boolean",
                        details={"clip_code": clip["clip_code"]},
                    )
                audio_roles = [
                    str(role)
                    for role in clip.get("audio_roles") or []
                    if str(role) != "sound_effect"
                ]
                if play_sound_effect:
                    audio_roles.append("sound_effect")
                clip["audio_roles"] = audio_roles
            source_asset_code = str(update.get("source_asset_code") or "").strip()
            if source_asset_code:
                source = dict(clip.get("source_range") or {})
                if not source:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SOURCE_RANGE_UNAVAILABLE",
                        "This clip has no editable source range",
                        details={"clip_code": clip["clip_code"]},
                    )
                if source_asset_code != str(source.get("asset_code") or ""):
                    source.update(
                        {
                            "asset_code": source_asset_code,
                            "start_seconds": 0.0,
                            "end_seconds": 6.0,
                            "available_start_seconds": 0.0,
                            "available_end_seconds": 6.0,
                        }
                    )
                else:
                    source["asset_code"] = source_asset_code
                clip["source_range"] = source
            source_start = update.get("source_start_seconds")
            source_end = update.get("source_end_seconds")
            if (source_start is None) != (source_end is None):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SOURCE_RANGE_INCOMPLETE",
                    "Source range edits require both a start and end",
                )
            if source_start is not None and source_end is not None:
                source = dict(clip.get("source_range") or {})
                if not source:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SOURCE_RANGE_UNAVAILABLE",
                        "This clip has no editable source range",
                        details={"clip_code": clip["clip_code"]},
                    )
                available_start = float(source.get("available_start_seconds", source.get("start_seconds", 0)))
                available_end = float(source.get("available_end_seconds", source.get("end_seconds", 0)))
                requested_start = float(source_start)
                requested_end = float(source_end)
                if (
                    requested_end <= requested_start
                    or requested_start < available_start
                    or requested_end > available_end
                ):
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SOURCE_RANGE_INVALID",
                        "Source range must stay inside the fixed available range",
                        details={
                            "clip_code": clip["clip_code"],
                            "available_start_seconds": available_start,
                            "available_end_seconds": available_end,
                        },
                    )
                source.update(
                    {
                        "start_seconds": requested_start,
                        "end_seconds": requested_end,
                        "available_start_seconds": available_start,
                        "available_end_seconds": available_end,
                    }
                )
                clip["source_range"] = source
            clip["timeline_range"] = {"start_ms": cursor, "duration_ms": duration}
            clip["transition"] = transition
            cursor += duration
            ordered_clips.append(clip)
        if not 30_000 <= cursor <= 120_000:
            raise DomainValidationError(
                "VIDEO_TIMELINE_DURATION_OUT_OF_RANGE",
                "Edited timeline duration must remain between 30 and 120 seconds",
                details={"duration_ms": cursor},
            )
        result["global_start_ms"] = 0
        result["global_end_ms"] = cursor
        maximum_poster_time_ms = max(0, cursor - 1)
        selected_poster_time_ms = result.get("poster_time_ms") if poster_time_ms is None else poster_time_ms
        if selected_poster_time_ms is None:
            selected_poster_time_ms = min(2_000, maximum_poster_time_ms)
        try:
            selected_poster_time_ms = int(selected_poster_time_ms)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(
                "VIDEO_TIMELINE_POSTER_TIME_INVALID",
                "Poster time must be an integer millisecond offset",
            ) from exc
        if not 0 <= selected_poster_time_ms <= maximum_poster_time_ms:
            raise DomainValidationError(
                "VIDEO_TIMELINE_POSTER_TIME_INVALID",
                "Poster time must remain inside the rendered timeline",
                details={"maximum_poster_time_ms": maximum_poster_time_ms},
            )
        result["poster_time_ms"] = selected_poster_time_ms
        if subtitle_style is not None:
            preset = str(subtitle_style.get("preset") or "").strip()
            safe_bottom_px = subtitle_style.get("safe_bottom_px")
            if preset not in {"compact", "standard", "large"}:
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SUBTITLE_STYLE_INVALID",
                    "Subtitle preset must be compact, standard or large",
                )
            if (
                not isinstance(safe_bottom_px, int)
                or isinstance(safe_bottom_px, bool)
                or not 80 <= safe_bottom_px <= 360
            ):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SUBTITLE_STYLE_INVALID",
                    "Subtitle bottom safe margin must be an integer between 80 and 360",
                )
            result["subtitle_style"] = {
                "preset": preset,
                "safe_bottom_px": safe_bottom_px,
            }
        video["clips"] = ordered_clips
        FunctionalVideoService._apply_subtitle_updates(
            tracks,
            ordered_video_clips=ordered_clips,
            subtitle_updates=subtitle_updates or [],
        )
        FunctionalVideoService._apply_audio_updates(
            tracks,
            ordered_video_clips=ordered_clips,
            audio_updates=audio_updates or [],
        )
        return FunctionalVideoService._with_rational_time_projection(result)

    @classmethod
    def _with_rational_time_projection(cls, timeline: dict[str, Any]) -> dict[str, Any]:
        """Add a lossless OTIO-compatible editorial-time projection to millisecond inputs.

        The worker still consumes millisecond offsets today.  The rational fields
        make the time rate and ranges explicit for revisions and downstream
        adapters without silently changing that stable worker contract.
        """
        result = deepcopy(timeline)
        try:
            global_start_ms = int(result.get("global_start_ms", 0))
            global_end_ms = int(result["global_end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainValidationError(
                "VIDEO_TIMELINE_TIME_RANGE_INVALID",
                "Timeline requires integer global millisecond bounds",
            ) from exc
        if global_start_ms < 0 or global_end_ms <= global_start_ms:
            raise DomainValidationError(
                "VIDEO_TIMELINE_TIME_RANGE_INVALID",
                "Timeline global range must be positive",
            )
        result["schema_version"] = "otio-compatible-production-timeline.v2"
        result["otio_schema"] = "OTIO_SCHEMA:Timeline.1"
        result["editorial_time_rate"] = cls.EDITORIAL_TIME_RATE
        result["global_time_range"] = cls._rational_time_range(
            global_start_ms, global_end_ms - global_start_ms
        )
        for track in result.get("tracks") or []:
            if not isinstance(track, dict):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_TRACK_INVALID",
                    "Timeline tracks must be objects",
                )
            clips = track.get("clips") or []
            track_start_ms: int | None = None
            track_end_ms: int | None = None
            for clip in clips:
                if not isinstance(clip, dict):
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_CLIP_INVALID",
                        "Timeline clips must be objects",
                    )
                time_range = clip.get("timeline_range") or {}
                try:
                    start_ms = int(time_range["start_ms"])
                    duration_ms = int(time_range["duration_ms"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_TIME_RANGE_INVALID",
                        "Timeline clips require integer millisecond offsets",
                        details={"clip_code": clip.get("clip_code")},
                    ) from exc
                if start_ms < 0 or duration_ms <= 0:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_TIME_RANGE_INVALID",
                        "Timeline clip range must be positive",
                        details={"clip_code": clip.get("clip_code")},
                    )
                clip["timeline_time_range"] = cls._rational_time_range(
                    start_ms, duration_ms
                )
                track_start_ms = start_ms if track_start_ms is None else min(track_start_ms, start_ms)
                track_end_ms = max(track_end_ms or 0, start_ms + duration_ms)
                source_range = clip.get("source_range")
                if isinstance(source_range, dict):
                    try:
                        source_start_ms = round(float(source_range["start_seconds"]) * cls.EDITORIAL_TIME_RATE)
                        source_end_ms = round(float(source_range["end_seconds"]) * cls.EDITORIAL_TIME_RATE)
                    except (KeyError, TypeError, ValueError):
                        source_start_ms = source_end_ms = 0
                    if source_start_ms >= 0 and source_end_ms > source_start_ms:
                        source_range["source_time_range"] = cls._rational_time_range(
                            source_start_ms, source_end_ms - source_start_ms
                        )
                transition = str(clip.get("transition") or "cut")
                if transition in {"fade", "fade_out"}:
                    transition_duration_ms = min(300, duration_ms // 2)
                else:
                    transition_duration_ms = 0
                clip["transition_time_range"] = {
                    "transition_type": transition,
                    "duration": cls._rational_time(transition_duration_ms),
                }
            if track_start_ms is not None and track_end_ms is not None:
                track["track_time_range"] = cls._rational_time_range(
                    track_start_ms, track_end_ms - track_start_ms
                )
        return result

    @classmethod
    def _rational_time_range(cls, start_ms: int, duration_ms: int) -> dict[str, dict[str, int]]:
        return {
            "start_time": cls._rational_time(start_ms),
            "duration": cls._rational_time(duration_ms),
        }

    @classmethod
    def _rational_time(cls, value: int) -> dict[str, int]:
        return {"value": int(value), "rate": cls.EDITORIAL_TIME_RATE}

    @staticmethod
    def _apply_audio_updates(
        tracks: list[dict[str, Any]],
        *,
        ordered_video_clips: list[dict[str, Any]],
        audio_updates: list[dict[str, Any]],
    ) -> None:
        audio_track = next((track for track in tracks if track.get("track_kind") == "audio"), None)
        if audio_track is None:
            if audio_updates:
                raise DomainValidationError("VIDEO_TIMELINE_AUDIO_TRACK_MISSING", "Timeline has no editable audio track")
            return
        if not isinstance(audio_track, dict):
            raise DomainValidationError("VIDEO_TIMELINE_AUDIO_TRACK_INVALID", "Timeline audio track is invalid")
        current_clips = list(audio_track.get("clips") or [])
        video_codes = [str(clip["clip_code"]) for clip in ordered_video_clips]
        expected_voice_codes = [f"VOICE-{code}" for code in video_codes]
        current_voice_by_code = {
            str(clip.get("clip_code") or ""): clip
            for clip in current_clips
            if str(clip.get("clip_code") or "").startswith("VOICE-")
        }
        if set(current_voice_by_code) != set(expected_voice_codes):
            raise DomainValidationError(
                "VIDEO_TIMELINE_AUDIO_MAPPING_INVALID",
                "Voice clips must remain one-to-one with the fixed video shot set",
                details={"expected_clip_codes": expected_voice_codes},
            )
        updates_by_code = {str(update.get("clip_code") or ""): update for update in audio_updates}
        if audio_updates and (set(updates_by_code) != set(expected_voice_codes) or len(audio_updates) != len(expected_voice_codes)):
            raise DomainValidationError(
                "VIDEO_TIMELINE_AUDIO_CLIP_SET_MISMATCH",
                "Audio edits must retain the complete current voice clip set",
                details={"expected_clip_codes": expected_voice_codes},
            )
        ordered_audio: list[dict[str, Any]] = []
        for video_clip in ordered_video_clips:
            voice_code = f"VOICE-{video_clip['clip_code']}"
            audio_clip = deepcopy(current_voice_by_code[voice_code])
            update = updates_by_code.get(voice_code)
            if update is not None:
                gain_db = float(update.get("gain_db", 0))
                if not -24 <= gain_db <= 12:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_AUDIO_GAIN_INVALID",
                        "Voice gain must remain between -24 dB and 12 dB",
                        details={"clip_code": voice_code},
                    )
                audio_clip["gain_db"] = gain_db
            else:
                audio_clip["gain_db"] = float(audio_clip.get("gain_db") or 0)
            audio_clip["linked_shot_code"] = str(video_clip["clip_code"])
            audio_clip["timeline_range"] = dict(video_clip["timeline_range"])
            ordered_audio.append(audio_clip)
        unlinked_audio = []
        timeline_duration_ms = sum(
            int(clip["timeline_range"]["duration_ms"])
            for clip in ordered_video_clips
        )
        for current in current_clips:
            if str(current.get("clip_code") or "").startswith("VOICE-"):
                continue
            clip = deepcopy(current)
            if str(clip.get("clip_code") or "") == "BGM-01":
                clip["timeline_range"] = {"start_ms": 0, "duration_ms": timeline_duration_ms}
            unlinked_audio.append(clip)
        audio_track["clips"] = [*ordered_audio, *unlinked_audio]

    @staticmethod
    def _apply_subtitle_updates(
        tracks: list[dict[str, Any]],
        *,
        ordered_video_clips: list[dict[str, Any]],
        subtitle_updates: list[dict[str, Any]],
    ) -> None:
        subtitle_track = next((track for track in tracks if track.get("track_kind") == "subtitle"), None)
        if subtitle_track is None:
            if subtitle_updates:
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SUBTITLE_TRACK_MISSING",
                    "Timeline has no editable subtitle track",
                )
            return
        if not isinstance(subtitle_track, dict):
            raise DomainValidationError("VIDEO_TIMELINE_SUBTITLE_TRACK_INVALID", "Timeline subtitle track is invalid")
        current_clips = list(subtitle_track.get("clips") or [])
        current_by_code = {str(clip.get("clip_code") or ""): clip for clip in current_clips}
        video_codes = [str(clip["clip_code"]) for clip in ordered_video_clips]
        expected_codes = [f"SUBTITLE-{code}" for code in video_codes]
        if set(current_by_code) != set(expected_codes) or len(current_clips) != len(expected_codes):
            raise DomainValidationError(
                "VIDEO_TIMELINE_SUBTITLE_MAPPING_INVALID",
                "Subtitle clips must remain one-to-one with the fixed video shot set",
                details={"expected_clip_codes": expected_codes},
            )
        if subtitle_updates:
            update_by_code = {str(update.get("clip_code") or ""): update for update in subtitle_updates}
            if set(update_by_code) != set(expected_codes) or len(update_by_code) != len(subtitle_updates):
                raise DomainValidationError(
                    "VIDEO_TIMELINE_SUBTITLE_SET_MISMATCH",
                    "Subtitle edits must retain the complete current subtitle clip set",
                    details={"expected_clip_codes": expected_codes},
                )
        else:
            update_by_code = {}
        ordered_subtitles: list[dict[str, Any]] = []
        for video_clip in ordered_video_clips:
            video_code = str(video_clip["clip_code"])
            subtitle_code = f"SUBTITLE-{video_code}"
            subtitle = deepcopy(current_by_code[subtitle_code])
            update = update_by_code.get(subtitle_code)
            if update is not None:
                subtitle_text = str(update.get("subtitle_text") or "").strip()
                headline_text = str(update.get("headline_text") or "").strip()
                caption_position = str(update.get("caption_position") or "bottom")
                if not subtitle_text or len(subtitle_text) > 500 or len(headline_text) > 160:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SUBTITLE_TEXT_INVALID",
                        "Subtitle text must be non-empty and stay within the supported length",
                        details={"clip_code": subtitle_code},
                    )
                subtitle["subtitle_text"] = subtitle_text
                subtitle["headline_text"] = headline_text
                if caption_position not in {"bottom", "center"}:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SUBTITLE_POSITION_INVALID",
                        "Subtitle caption position must be bottom or center",
                        details={"clip_code": subtitle_code},
                    )
                subtitle["caption_position"] = caption_position
            else:
                subtitle["caption_position"] = (
                    str(subtitle.get("caption_position"))
                    if subtitle.get("caption_position") in {"bottom", "center"}
                    else "bottom"
                )
            subtitle["linked_shot_code"] = video_code
            subtitle["timeline_range"] = dict(video_clip["timeline_range"])
            ordered_subtitles.append(subtitle)
        subtitle_track["clips"] = ordered_subtitles

    @staticmethod
    def _timeline_shot_list(shot_list: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(shot_list)
        video_track = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "video"), None)
        if not isinstance(video_track, dict):
            raise DomainValidationError("VIDEO_TIMELINE_VIDEO_TRACK_MISSING", "Timeline has no editable video track")
        clips = {str(clip["clip_code"]): clip for clip in video_track.get("clips") or []}
        subtitle_track = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "subtitle"), None)
        subtitle_clips = subtitle_track.get("clips") or [] if isinstance(subtitle_track, dict) else []
        subtitle_by_shot = {
            str(clip.get("linked_shot_code") or str(clip.get("clip_code") or "").removeprefix("SUBTITLE-")): clip
            for clip in subtitle_clips
            if isinstance(clip, dict)
        }
        audio_track = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "audio"), None)
        audio_by_shot = {
            str(clip.get("linked_shot_code") or str(clip.get("clip_code") or "").removeprefix("VOICE-")): clip
            for clip in (audio_track.get("clips") or [] if isinstance(audio_track, dict) else [])
            if isinstance(clip, dict) and str(clip.get("clip_code") or "").startswith("VOICE-")
        }
        shots = list(result.get("shots") or [])
        if {str(shot.get("shot_code") or "") for shot in shots} != set(clips):
            raise DomainValidationError("VIDEO_TIMELINE_SHOT_MAPPING_INVALID", "Timeline clips no longer match the fixed ShotList")
        shots_by_code = {str(shot["shot_code"]): shot for shot in shots}
        ordered_shots: list[dict[str, Any]] = []
        for clip_code in [str(clip["clip_code"]) for clip in video_track.get("clips") or []]:
            shot = deepcopy(shots_by_code[clip_code])
            clip = clips[clip_code]
            timing = clip["timeline_range"]
            start = int(timing["start_ms"]) / 1000
            duration = int(timing["duration_ms"]) / 1000
            shot["start_seconds"] = start
            shot["end_seconds"] = start + duration
            shot["duration_seconds"] = duration
            shot["transition"] = clip.get("transition") or "cut"
            if clip.get("fit") in {"cover", "contain"}:
                shot["fit"] = clip["fit"]
            if clip.get("crop_x") is not None and clip.get("crop_y") is not None:
                shot["crop_x"] = float(clip["crop_x"])
                shot["crop_y"] = float(clip["crop_y"])
            if clip.get("playback_rate") is not None:
                shot["playback_rate"] = float(clip["playback_rate"])
            if isinstance(clip.get("overlay_roles"), list):
                shot["overlay_roles"] = [
                    str(role)
                    for role in clip["overlay_roles"]
                    if str(role) in {"brand_logo", "product_sticker"}
                ]
            overlay_z_order = clip.get("overlay_z_order")
            if isinstance(overlay_z_order, dict):
                normalized_z_order: dict[str, int] = {}
                for role in ("brand_logo", "product_sticker"):
                    value = overlay_z_order.get(role)
                    if isinstance(value, int) and not isinstance(value, bool):
                        normalized_z_order[role] = value
                if normalized_z_order:
                    shot["overlay_z_order"] = normalized_z_order
            product_sticker_layout = clip.get("product_sticker_layout")
            if isinstance(product_sticker_layout, dict):
                try:
                    sticker_x = float(product_sticker_layout["x"])
                    sticker_y = float(product_sticker_layout["y"])
                    sticker_width_ratio = float(product_sticker_layout["width_ratio"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PRODUCT_STICKER_LAYOUT_INVALID",
                        "Product sticker layout is invalid",
                        details={"clip_code": clip_code},
                    ) from exc
                if (
                    "product_sticker" not in shot.get("overlay_roles", [])
                    or not 0 <= sticker_x <= 1
                    or not 0 <= sticker_y <= 1
                    or not 0.1 <= sticker_width_ratio <= 1
                ):
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_PRODUCT_STICKER_LAYOUT_INVALID",
                        "Product sticker layout must belong to an enabled sticker",
                        details={"clip_code": clip_code},
                    )
                shot["product_sticker_layout"] = {
                    "x": sticker_x,
                    "y": sticker_y,
                    "width_ratio": sticker_width_ratio,
                }
            product_sticker_suggestion = clip.get("product_sticker_layout_suggestion")
            if isinstance(product_sticker_suggestion, dict):
                shot["product_sticker_layout_suggestion"] = deepcopy(
                    product_sticker_suggestion
                )
            if isinstance(clip.get("audio_roles"), list):
                shot["audio_roles"] = [
                    str(role)
                    for role in clip["audio_roles"]
                    if str(role) == "sound_effect"
                ]
            source_range = clip.get("source_range") or {}
            source_asset_code = str(source_range.get("asset_code") or "").strip()
            current_asset_code = str(shot.get("asset_code") or "").strip()
            if source_asset_code and current_asset_code and source_asset_code != current_asset_code:
                source_pool = {
                    str(asset.get("asset_code") or ""): asset
                    for asset in result.get("visual_source_pool") or []
                    if isinstance(asset, dict)
                }
                selected_asset = source_pool.get(source_asset_code)
                if not isinstance(selected_asset, dict):
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SOURCE_ASSET_NOT_FROZEN",
                        "Timeline visual source must come from this plan's frozen material pool",
                        details={"clip_code": clip_code, "asset_code": source_asset_code},
                    )
                relative_path = str(selected_asset.get("relative_path") or "").strip()
                checksum = str(selected_asset.get("checksum_sha256") or "").strip()
                if not relative_path or not checksum:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_SOURCE_ASSET_INVALID",
                        "Frozen timeline visual source is incomplete",
                        details={"clip_code": clip_code, "asset_code": source_asset_code},
                    )
                shot["asset_code"] = source_asset_code
                shot["asset_relative_path"] = relative_path
                shot["asset_expected_checksum"] = checksum
                shot["visual_role"] = "selected_library_video"
            if "start_seconds" in source_range and "end_seconds" in source_range:
                shot["source_start_seconds"] = float(source_range["start_seconds"])
                shot["source_end_seconds"] = float(source_range["end_seconds"])
                shot["source_available_seconds"] = float(source_range["end_seconds"]) - float(source_range["start_seconds"])
            subtitle = subtitle_by_shot.get(clip_code)
            if subtitle is not None:
                shot["subtitle_text"] = str(subtitle.get("subtitle_text") or shot.get("narration") or "")
                shot["screen_text"] = str(subtitle.get("headline_text") or "")
                shot["caption_position"] = (
                    str(subtitle.get("caption_position"))
                    if subtitle.get("caption_position") in {"bottom", "center"}
                    else "bottom"
                )
            audio = audio_by_shot.get(clip_code)
            if audio is not None:
                shot["voice_gain_db"] = float(audio.get("gain_db") or 0)
            ordered_shots.append(shot)
        if any("sound_effect" in (shot.get("audio_roles") or []) for shot in ordered_shots) and not isinstance(
            result.get("sound_effect"), dict
        ):
            raise DomainValidationError(
                "VIDEO_TIMELINE_SOUND_EFFECT_NOT_SELECTED",
                "Timeline sound effects require a frozen local sound-effect source",
            )
        result["shots"] = ordered_shots
        result["duration_seconds"] = timeline["global_end_ms"] / 1000
        if isinstance(timeline.get("subtitle_style"), dict):
            result["subtitle_style"] = deepcopy(timeline["subtitle_style"])
        result["poster_time_seconds"] = float(
            min(
                max(0, int(timeline.get("poster_time_ms") or 0)),
                max(0, int(timeline["global_end_ms"]) - 1),
            )
        ) / 1000
        result["timeline_revision"] = timeline.get("timeline_revision")
        result["production_timeline"] = deepcopy(timeline)
        return result

    @staticmethod
    def _compile_content(
        detail: dict[str, Any],
        duration: int,
        *,
        source_shot_codes: list[str] | None = None,
        source_shot_script_blocks: dict[str, list[str]] | None = None,
        visual_assets: list[dict[str, Any]] | None = None,
        background_music: dict[str, Any] | None = None,
        sound_effect: dict[str, Any] | None = None,
        product_sticker: dict[str, Any] | None = None,
        brand_logo: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        source_blocks = detail["script"]["blocks"]
        text = [str(block["content"]) for block in source_blocks]
        chunks = FunctionalVideoService._chunks(text, 6)
        durations = [round(duration / 6, 3) for _ in range(6)]
        durations[-1] = round(duration - sum(durations[:-1]), 3)
        clip_specs = (("MT-VID-0027", 0.0, 6.0, "contain"), ("MT-VID-0016", 0.0, 12.0, "cover"), ("MT-VID-0027", 30.0, 42.0, "contain"), ("MT-VID-0016", 12.0, 25.0, "cover"), ("MT-VID-0024", 0.0, 6.0, "cover"), ("MT-VID-0016", 25.0, 38.0, "cover"))
        cursor = 0.0
        compiled: list[dict[str, Any]] = []
        source_shot_codes = source_shot_codes or [f"SOURCE-SHOT-{index + 1:02d}" for index in range(6)]
        source_shot_script_blocks = source_shot_script_blocks or {}
        for index, (chunk, item_duration, clip) in enumerate(zip(chunks, durations, clip_specs, strict=True)):
            asset_code, source_start, source_end, fit = clip
            selected_asset = visual_assets[index % len(visual_assets)] if visual_assets else None
            if selected_asset is not None:
                asset_code = selected_asset["asset_code"]
                source_start = 0.0
                source_end = 6.0
            end = round(cursor + item_duration, 3)
            source_shot_code = source_shot_codes[min(len(source_shot_codes) - 1, index * len(source_shot_codes) // 6)]
            shot = {"shot_index": index, "shot_code": f"SHOT-{index + 1:02d}", "source_shot_code": source_shot_code, "source_script_block_codes": source_shot_script_blocks.get(source_shot_code, []), "start_seconds": cursor, "end_seconds": end, "duration_seconds": item_duration, "goal": "content_project", "narration": chunk, "tts_text": chunk.replace("PRO", "P R O"), "screen_text": chunk[:28], "asset_code": asset_code, "asset_relative_path": selected_asset["relative_path"] if selected_asset else None, "asset_expected_checksum": selected_asset["checksum_sha256"] if selected_asset else None, "source_start_seconds": source_start, "source_end_seconds": source_end, "source_available_seconds": source_end - source_start, "fit": fit, "playback_rate": 1.0, "visual_role": "selected_library_video" if selected_asset else "baseline_visual", "transition": "fade_out" if index == 5 else "cut", "overlay_roles": ["brand_logo"] if index in {0, 5} else []}
            sticker_suggestion = FunctionalVideoService._product_sticker_layout_suggestion(
                selected_asset,
                product_sticker,
            )
            if sticker_suggestion is not None:
                shot["product_sticker_layout_suggestion"] = sticker_suggestion
            shot["overlay_z_order"] = FunctionalVideoService._overlay_z_order(
                product_sticker=product_sticker,
                brand_logo=brand_logo,
            )
            compiled.append(shot)
            cursor = end
        if sound_effect is not None and compiled:
            compiled[0]["audio_roles"] = ["sound_effect"]
        story = {"source": "content_project_revision", "project_code": detail["project_code"], "objective": detail["generation_goal"], "content": detail["story_brief"]["content"], "format": {"orientation": "vertical", "width": 1080, "height": 1920, "target_duration_seconds": duration, "shot_count": 6}}
        script = {"source": "content_project_revision", "title": detail["title"], "spoken_script": "".join(chunks), "sections": [{"section_index": index, "section_type": "content_project", "narration": chunk, "tts_text": chunk.replace("PRO", "P R O"), "screen_text": chunk[:28]} for index, chunk in enumerate(chunks)], "section_count": len(chunks)}
        poster_time_ms = min(2_000, duration * 1000 - 1)
        subtitle_style = {"preset": "standard", "safe_bottom_px": 160}
        shots = {"source": "content_project_revision", "canvas": {"width": 1080, "height": 1920, "fps": 30}, "duration_seconds": duration, "shot_count": len(compiled), "poster_time_seconds": poster_time_ms / 1000, "subtitle_style": subtitle_style, "shots": compiled}
        if visual_assets:
            shots["visual_source_pool"] = [
                {
                    "asset_code": asset["asset_code"],
                    "relative_path": asset["relative_path"],
                    "checksum_sha256": asset["checksum_sha256"],
                }
                for asset in visual_assets
            ]
        if background_music is not None:
            shots["background_music"] = {
                "asset_code": background_music["asset_code"],
                "asset_relative_path": background_music["relative_path"],
                "asset_expected_checksum": background_music["checksum_sha256"],
                "gain_db": background_music["gain_db"],
            }
        if sound_effect is not None:
            shots["sound_effect"] = {
                "asset_code": sound_effect["asset_code"],
                "asset_relative_path": sound_effect["relative_path"],
                "asset_expected_checksum": sound_effect["checksum_sha256"],
                "gain_db": sound_effect["gain_db"],
            }
        if product_sticker is not None:
            shots["product_sticker"] = {
                "asset_code": product_sticker["asset_code"],
                "asset_relative_path": product_sticker["relative_path"],
                "asset_expected_checksum": product_sticker["checksum_sha256"],
            }
        if brand_logo is not None:
            shots["brand_logo"] = {
                "asset_code": brand_logo["asset_code"],
                "asset_relative_path": brand_logo["relative_path"],
                "asset_expected_checksum": brand_logo["checksum_sha256"],
            }
        audio_clips = [{"clip_code": f"VOICE-{shot['shot_code']}", "linked_shot_code": shot["shot_code"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "gain_db": 0.0} for shot in compiled]
        if background_music is not None:
            audio_clips.append({"clip_code": "BGM-01", "timeline_range": {"start_ms": 0, "duration_ms": duration * 1000}, "asset_code": background_music["asset_code"], "gain_db": background_music["gain_db"]})
        timeline = {"schema_version": "otio-compatible-production-timeline.v1", "global_start_ms": 0, "global_end_ms": duration * 1000, "poster_time_ms": poster_time_ms, "subtitle_style": subtitle_style, "tracks": [{"track_kind": "video", "clips": [{"clip_code": shot["shot_code"], "source_shot_code": shot["source_shot_code"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "source_range": {"asset_code": shot["asset_code"], "asset_checksum_sha256": shot.get("asset_expected_checksum"), "asset_relative_path": shot.get("asset_relative_path"), "start_seconds": shot["source_start_seconds"], "end_seconds": shot["source_end_seconds"], "available_start_seconds": shot["source_start_seconds"], "available_end_seconds": shot["source_end_seconds"]}, "fit": shot["fit"], "crop_x": 0.5, "crop_y": 0.5, "playback_rate": shot["playback_rate"], "overlay_roles": shot["overlay_roles"], "overlay_z_order": shot["overlay_z_order"], "product_sticker_layout_suggestion": shot.get("product_sticker_layout_suggestion"), "audio_roles": shot.get("audio_roles", []), "transition": shot["transition"]} for shot in compiled]}, {"track_kind": "audio", "clips": audio_clips}, {"track_kind": "subtitle", "clips": [{"clip_code": f"SUBTITLE-{shot['shot_code']}", "linked_shot_code": shot["shot_code"], "source_script_block_codes": shot["source_script_block_codes"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "subtitle_text": shot["narration"], "headline_text": shot["screen_text"], "caption_position": "bottom"} for shot in compiled]}]}
        timeline = FunctionalVideoService._with_rational_time_projection(timeline)
        return story, script, shots, timeline

    @staticmethod
    def _constraint_profile_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
        profile_code = str(row.get("constraint_profile_code") or "").strip()
        fingerprint = str(row.get("constraint_profile_fingerprint") or "").strip()
        try:
            revision_number = int(row.get("constraint_profile_revision"))
        except (TypeError, ValueError):
            revision_number = 0
        if not profile_code or revision_number < 1 or len(fingerprint) != 64:
            return None
        return {
            "profile_code": profile_code,
            "revision_number": revision_number,
            "fingerprint_sha256": fingerprint,
            "constraints": [
                deepcopy(rule)
                for rule in row.get("constraint_profile_constraints") or []
                if isinstance(rule, dict)
            ],
        }

    @staticmethod
    def _video_constraint_snapshot(
        *,
        visual_assets: list[dict[str, Any]],
        product_sticker: dict[str, Any] | None,
        brand_logo: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profiles: list[dict[str, Any]] = []
        for asset in [
            *visual_assets,
            *([product_sticker] if product_sticker else []),
            *([brand_logo] if brand_logo else []),
        ]:
            profile = asset.get("constraint_profile")
            if not isinstance(profile, dict):
                continue
            profiles.append(
                {
                    "asset_code": asset["asset_code"],
                    "profile_code": profile["profile_code"],
                    "revision_number": profile["revision_number"],
                    "fingerprint_sha256": profile["fingerprint_sha256"],
                    "constraints": deepcopy(profile["constraints"]),
                }
            )
        return {
            "schema_version": "functional-video-asset-constraints.v1",
            "profiles": profiles,
        }

    @staticmethod
    def _overlay_z_order(
        *,
        product_sticker: dict[str, Any] | None,
        brand_logo: dict[str, Any] | None,
    ) -> dict[str, int]:
        values = {"brand_logo": 100, "product_sticker": 200}
        for role, asset in (
            ("brand_logo", brand_logo),
            ("product_sticker", product_sticker),
        ):
            profile = asset.get("constraint_profile") if isinstance(asset, dict) else None
            if not isinstance(profile, dict):
                continue
            for rule in profile.get("constraints") or []:
                if not isinstance(rule, dict):
                    continue
                if str(rule.get("kind") or "") == "pin_layer_top":
                    values[role] = 1000
                elif str(rule.get("kind") or "") == "pin_layer_bottom":
                    values[role] = -1000
        return values

    @staticmethod
    def _product_sticker_layout_suggestion(
        visual_asset: dict[str, Any] | None,
        product_sticker: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if visual_asset is None or product_sticker is None:
            return None
        visual_profile = visual_asset.get("constraint_profile")
        if not isinstance(visual_profile, dict):
            return None
        product_profile = product_sticker.get("constraint_profile")
        product_rules = (
            product_profile.get("constraints")
            if isinstance(product_profile, dict)
            else []
        )
        for rule in visual_profile.get("constraints") or []:
            if not isinstance(rule, dict) or str(rule.get("kind") or "") != "table_surface":
                continue
            parameters = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
            if str(parameters.get("product_role") or "product_display") != "product_display":
                continue
            try:
                region_x = float(parameters["x"])
                region_y = float(parameters["y"])
                region_width = float(parameters["width"])
                region_height = float(parameters["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                region_x < 0
                or region_y < 0
                or region_width <= 0
                or region_height <= 0
                or region_x + region_width > 1
                or region_y + region_height > 1
            ):
                continue
            width_ratio = min(0.6, region_width)
            for product_rule in product_rules:
                if not isinstance(product_rule, dict) or str(product_rule.get("kind") or "") != "size_range":
                    continue
                size = product_rule.get("parameters") if isinstance(product_rule.get("parameters"), dict) else {}
                try:
                    minimum = float(size.get("min_width", 0.1))
                    maximum = float(size.get("max_width", 1.0))
                except (TypeError, ValueError):
                    continue
                if 0.1 <= minimum <= maximum <= 1:
                    width_ratio = min(max(width_ratio, minimum), maximum)
            width_ratio = min(max(width_ratio, 0.1), 1.0)
            anchor = str(parameters.get("product_anchor") or "bottom_center")
            if anchor == "bottom_left":
                raw_x = region_x
            elif anchor == "bottom_right":
                raw_x = region_x + region_width - width_ratio
            else:
                raw_x = region_x + (region_width - width_ratio) / 2
            raw_x = min(max(raw_x, 0.0), 1.0 - width_ratio)
            if anchor == "center":
                raw_y = region_y + (region_height - width_ratio) / 2
            else:
                raw_y = region_y + region_height - width_ratio
            raw_y = min(max(raw_y, 0.0), 1.0 - width_ratio)
            available = max(0.0001, 1.0 - width_ratio)
            return {
                "x": round(raw_x / available, 4),
                "y": round(raw_y / available, 4),
                "width_ratio": round(width_ratio, 4),
                "source": "table_surface",
                "table_surface_name": str(parameters.get("name") or "table_surface"),
                "constraint_profile": {
                    "profile_code": visual_profile["profile_code"],
                    "revision_number": visual_profile["revision_number"],
                    "fingerprint_sha256": visual_profile["fingerprint_sha256"],
                },
                "approximate": True,
            }
        return None

    @staticmethod
    def _selected_material_codes(shot_list: dict[str, Any]) -> list[str]:
        codes = [
            str(shot.get("asset_code") or "").strip()
            for shot in shot_list.get("shots") or []
            if isinstance(shot, dict)
        ]
        background_music = shot_list.get("background_music")
        if isinstance(background_music, dict):
            codes.append(str(background_music.get("asset_code") or "").strip())
        sound_effect = shot_list.get("sound_effect")
        if isinstance(sound_effect, dict):
            codes.append(str(sound_effect.get("asset_code") or "").strip())
        product_sticker = shot_list.get("product_sticker")
        if isinstance(product_sticker, dict):
            codes.append(str(product_sticker.get("asset_code") or "").strip())
        brand_logo = shot_list.get("brand_logo")
        if isinstance(brand_logo, dict):
            codes.append(str(brand_logo.get("asset_code") or "").strip())
        return list(dict.fromkeys(code for code in codes if code))

    @staticmethod
    def _chunks(blocks: list[str], count: int) -> list[str]:
        source = "".join(blocks).strip() or "请根据内容项目完成本次讲述。"
        size = max(1, (len(source) + count - 1) // count)
        chunks = [source[index:index + size] for index in range(0, len(source), size)]
        return (chunks + ["继续围绕当前主题说明关键信息。"] * count)[:count]

    @staticmethod
    def _next_code(cursor: Any) -> str:
        return FunctionalVideoService._next_sequence_code(
            cursor,
            prefix="VIDPLAN",
            object_type="functional_video_plan",
        )

    @staticmethod
    def _next_sequence_code(cursor: Any, *, prefix: str, object_type: str) -> str:
        date = datetime.now(UTC).date()
        cursor.execute(
            """INSERT INTO domain_sequences (sequence_date, object_type, current_value)
               VALUES (%s, %s, 1)
               ON CONFLICT (sequence_date, object_type)
               DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now()
               RETURNING current_value""",
            (date, object_type),
        )
        return f"{prefix}-{date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"

    @staticmethod
    def _next_release_snapshot_artifact_code(cursor: Any) -> str:
        date = datetime.now(UTC).date()
        cursor.execute(
            """INSERT INTO domain_sequences (sequence_date, object_type, current_value)
               VALUES (%s, 'functional_video_release_snapshot', 1)
               ON CONFLICT (sequence_date, object_type)
               DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now()
               RETURNING current_value""",
            (date,),
        )
        return f"ART-{date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"
