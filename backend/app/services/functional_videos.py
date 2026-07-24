from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainValidationError
from app.repositories.content_production import ContentProductionRepository
from app.repositories.releases import ReleaseRepository
from app.repositories.video_productions import VideoProductionRepository
from app.services.functional_content import FunctionalContentService
from app.services.releases import ReleaseService


class FunctionalVideoService:
    """Creates a rendered-video variant whose queued worker job consumes ContentProject text."""

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
        self._release_signing_key = release_signing_key
        self._release_signing_key_id = release_signing_key_id

    def create_plan(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        detail = self._source_detail(payload)
        if detail is None:
            raise KeyError(payload.get("project_code") or payload.get("live_room_plan_code"))
        if not detail["generated"] or not detail["story_brief"] or not detail["script"] or not detail["shot_list"]:
            raise DomainValidationError("VIDEO_CONTENT_CHAIN_REQUIRED", "Generate the ContentProject before creating a video plan")
        duration = int(payload["target_duration_seconds"])
        story, script, shots, timeline = self._compile_content(detail, duration)
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
            material_snapshot_ref={"source": "baseline_verified_video_assets.v1", "asset_codes": [shot["asset_code"] for shot in shots["shots"]]},
            constraint_snapshot_ref={"source": "functional-content-timeline.v1"},
            actor_id=actor_id, producer_strategy_revision="functional-video.v1",
        )
        variant = self.production.confirm_production_variant_revision(variant["variant_code"], revision_number=int(variant["revision_number"]), actor_id=actor_id)
        job = self.videos.create({"topic": detail["generation_goal"], "target_duration_seconds": duration})
        seeded = self.videos.seed_content_project_job(job["job_code"], story_brief=story, script=script, shot_list=shots)
        if seeded is None:
            raise RuntimeError("created video job cannot be seeded")
        self.production.bind_video_production_job(job_code=job["job_code"], variant_code=variant["variant_code"], variant_revision=int(variant["revision_number"]), actor_id=actor_id)
        render_profile = {
            "schema_version": "functional-render-profile.v1", "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "subtitle": "ass", "audio": "local_tts", "visual_asset_mode": "baseline_verified_video_assets", "target_duration_seconds": duration,
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
        self.connection.commit()
        return self._enrich(row)

    def _source_detail(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        live_room_plan_code = payload.get("live_room_plan_code")
        if live_room_plan_code:
            return self._live_room_source_detail(str(live_room_plan_code))
        return self.content.get_detail(str(payload["project_code"]))

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
                       shots.shot_list_revision_code, shots.revision_number AS shot_list_revision_number
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
        if not blocks:
            raise DomainValidationError(
                "VIDEO_LIVE_ROOM_SOURCE_SCRIPT_EMPTY",
                "The live-room source has no fixed script blocks to compile into a video",
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
                "asset_codes": [str(shot.get("asset_code")) for shot in job.get("shot_list", {}).get("shots") or []],
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
        return self._with_release(plan)

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
                        {"show_product_sticker": "product_sticker" in (clip.get("overlay_roles") or [])}
                        if clip.get("overlay_roles") is not None
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
        return result

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
        unlinked_audio = [
            deepcopy(clip)
            for clip in current_clips
            if not str(clip.get("clip_code") or "").startswith("VOICE-")
        ]
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
            source_range = clip.get("source_range") or {}
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
        result["shots"] = ordered_shots
        result["duration_seconds"] = timeline["global_end_ms"] / 1000
        result["timeline_revision"] = timeline.get("timeline_revision")
        return result

    @staticmethod
    def _compile_content(detail: dict[str, Any], duration: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        source_blocks = detail["script"]["blocks"]
        text = [str(block["content"]) for block in source_blocks]
        chunks = FunctionalVideoService._chunks(text, 6)
        durations = [round(duration / 6, 3) for _ in range(6)]
        durations[-1] = round(duration - sum(durations[:-1]), 3)
        clip_specs = (("MT-VID-0027", 0.0, 6.0, "contain"), ("MT-VID-0016", 0.0, 12.0, "cover"), ("MT-VID-0027", 30.0, 42.0, "contain"), ("MT-VID-0016", 12.0, 25.0, "cover"), ("MT-VID-0024", 0.0, 6.0, "cover"), ("MT-VID-0016", 25.0, 38.0, "cover"))
        cursor = 0.0
        compiled: list[dict[str, Any]] = []
        for index, (chunk, item_duration, clip) in enumerate(zip(chunks, durations, clip_specs, strict=True)):
            asset_code, source_start, source_end, fit = clip
            end = round(cursor + item_duration, 3)
            compiled.append({"shot_index": index, "shot_code": f"SHOT-{index + 1:02d}", "start_seconds": cursor, "end_seconds": end, "duration_seconds": item_duration, "goal": "content_project", "narration": chunk, "tts_text": chunk.replace("PRO", "P R O"), "screen_text": chunk[:28], "asset_code": asset_code, "source_start_seconds": source_start, "source_end_seconds": source_end, "source_available_seconds": source_end - source_start, "fit": fit, "playback_rate": 1.0, "visual_role": "baseline_visual", "transition": "fade_out" if index == 5 else "cut", "overlay_roles": ["brand_logo"] if index in {0, 5} else []})
            cursor = end
        story = {"source": "content_project_revision", "project_code": detail["project_code"], "objective": detail["generation_goal"], "content": detail["story_brief"]["content"], "format": {"orientation": "vertical", "width": 1080, "height": 1920, "target_duration_seconds": duration, "shot_count": 6}}
        script = {"source": "content_project_revision", "title": detail["title"], "spoken_script": "".join(chunks), "sections": [{"section_index": index, "section_type": "content_project", "narration": chunk, "tts_text": chunk.replace("PRO", "P R O"), "screen_text": chunk[:28]} for index, chunk in enumerate(chunks)], "section_count": len(chunks)}
        shots = {"source": "content_project_revision", "canvas": {"width": 1080, "height": 1920, "fps": 30}, "duration_seconds": duration, "shot_count": len(compiled), "shots": compiled}
        timeline = {"schema_version": "otio-compatible-production-timeline.v1", "global_start_ms": 0, "global_end_ms": duration * 1000, "tracks": [{"track_kind": "video", "clips": [{"clip_code": shot["shot_code"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "source_range": {"asset_code": shot["asset_code"], "start_seconds": shot["source_start_seconds"], "end_seconds": shot["source_end_seconds"], "available_start_seconds": shot["source_start_seconds"], "available_end_seconds": shot["source_end_seconds"]}, "fit": shot["fit"], "crop_x": 0.5, "crop_y": 0.5, "playback_rate": shot["playback_rate"], "overlay_roles": shot["overlay_roles"], "transition": shot["transition"]} for shot in compiled]}, {"track_kind": "audio", "clips": [{"clip_code": f"VOICE-{shot['shot_code']}", "linked_shot_code": shot["shot_code"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "gain_db": 0.0} for shot in compiled]}, {"track_kind": "subtitle", "clips": [{"clip_code": f"SUBTITLE-{shot['shot_code']}", "linked_shot_code": shot["shot_code"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "subtitle_text": shot["narration"], "headline_text": shot["screen_text"], "caption_position": "bottom"} for shot in compiled]}]}
        return story, script, shots, timeline

    @staticmethod
    def _chunks(blocks: list[str], count: int) -> list[str]:
        source = "".join(blocks).strip() or "请根据内容项目完成本次讲述。"
        size = max(1, (len(source) + count - 1) // count)
        chunks = [source[index:index + size] for index in range(0, len(source), size)]
        return (chunks + ["继续围绕当前主题说明关键信息。"] * count)[:count]

    @staticmethod
    def _next_code(cursor: Any) -> str:
        date = datetime.now(UTC).date()
        cursor.execute("""INSERT INTO domain_sequences (sequence_date, object_type, current_value) VALUES (%s, 'functional_video_plan', 1) ON CONFLICT (sequence_date, object_type) DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now() RETURNING current_value""", (date,))
        return f"VIDPLAN-{date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"

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
