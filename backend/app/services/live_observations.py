from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Protocol

from app.schemas.live_observations import (
    AnalysisRunCreate,
    AnalysisRunCompletion,
    AnalysisRetryRequest,
    CaptureChannelCreate,
    CaptureChunkFinalize,
    CaptureSessionCreate,
    CaptureSessionFinish,
    ClipJobCreate,
    ClipJobCompletion,
    RawEventBatchRegistration,
    RetentionClaimRequest,
    RoomTemplateCreate,
    RoomTemplatePublicationRequest,
    RoomTemplateRevisionCreate,
    SchedulerClaimRequest,
    SchedulerHeartbeatRequest,
    SchedulerReleaseRequest,
    TimelineSpanCreate,
    WatchTargetCreate,
    WatchTargetUpdate,
    WorkClaimRequest,
    WorkFailure,
    WorkHeartbeatRequest,
)


class LiveObservationConflictError(RuntimeError):
    """An observation cannot be changed from its current authoritative state."""


class LiveObservationNotFoundError(RuntimeError):
    """The requested live-research object does not exist."""


class LiveObservationRepositoryProtocol(Protocol):
    def overview(self) -> dict[str, int]: ...


def canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def default_chunk_analysis_specs() -> list[dict[str, Any]]:
    return [
        {
            "analysis_type": "frame_sampling",
            "strategy_revision": "live.frame-sampling.v2",
            "parameters": {"interval_seconds": 5, "max_frames": 720},
        },
        {
            "analysis_type": "asr",
            "strategy_revision": "live.asr.zh.v2",
            "parameters": {"language": "zh"},
        },
        {
            "analysis_type": "ocr",
            "strategy_revision": "live.ocr.v2",
            "parameters": {"sample_times_seconds": [0, 5, 15, 30]},
        },
        {
            "analysis_type": "layout_inference",
            "strategy_revision": "live.layout-inference.v2",
            "parameters": {"sample_times_seconds": [0, 5, 15, 30]},
        },
    ]


def default_aggregation_spec() -> dict[str, str]:
    return {
        "strategy_revision": "live.template-aggregation.v2",
    }


def validate_storage_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ValueError("path must stay within the configured live-research root")
    if any(not part for part in path.parts):
        raise ValueError("path contains an empty component")
    return str(path)


def validate_timeline_append(
    existing: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    tolerance_seconds: float = 0.5,
) -> None:
    expected_index = len(existing)
    if int(candidate["span_index"]) != expected_index:
        raise LiveObservationConflictError(
            f"timeline span_index must be {expected_index}; received {candidate['span_index']}"
        )
    global_start = float(candidate["global_start_seconds"])
    global_end = float(candidate["global_end_seconds"])
    chunk_start = float(candidate["chunk_start_seconds"])
    chunk_end = float(candidate["chunk_end_seconds"])
    slope = float(candidate.get("mapping_slope", 1.0))
    mapped_duration = (chunk_end - chunk_start) * slope
    if abs((global_end - global_start) - mapped_duration) > tolerance_seconds:
        raise LiveObservationConflictError("timeline mapping duration differs from its chunk duration")
    if not existing:
        if global_start > tolerance_seconds:
            raise LiveObservationConflictError("the first timeline span must start at zero")
        return
    previous_end = float(existing[-1]["global_end_seconds"])
    if global_start + tolerance_seconds < previous_end:
        raise LiveObservationConflictError("normalized timeline spans cannot overlap")
    discontinuity = str(candidate.get("discontinuity_before") or "none")
    has_gap = global_start - previous_end > tolerance_seconds
    if has_gap and discontinuity not in {"gap", "reconnect", "unknown"}:
        raise LiveObservationConflictError("a normalized timeline gap must be declared explicitly")


def build_template_projection(
    template: dict[str, Any],
    revision: dict[str, Any],
) -> dict[str, Any]:
    components = [dict(item) for item in revision.get("components") or [] if isinstance(item, dict)]
    scenes = [dict(item) for item in revision.get("scenes") or [] if isinstance(item, dict)]
    provenance = dict(revision.get("provenance") or {})
    audio_policy = dict(revision.get("audio_policy") or {})
    # Live research observes a flattened external broadcast. Client-supplied
    # provenance and asset bindings cannot prove that its source layout is
    # reconstructable, so it remains a reference until a server-verified
    # reconstruction contract exists.
    blocking: list[str] = ["external_flat_video_reference_only"]

    if not components:
        blocking.append("template_has_no_components")
    if not scenes:
        blocking.append("template_has_no_scenes")
    if float(revision.get("confidence") or 0) < 0.8:
        blocking.append("template_confidence_below_0_8")

    session_codes = provenance.get("source_session_codes")
    independent_sessions = {
        str(code).strip() for code in session_codes or [] if isinstance(code, str) and str(code).strip()
    }
    if len(independent_sessions) < 3:
        blocking.append("fewer_than_three_independent_source_sessions")

    component_ids: set[str] = set()
    for component in components:
        component_id = str(component.get("component_id") or "")
        if not component_id or component_id in component_ids:
            blocking.append("component_identity_is_missing_or_duplicate")
        component_ids.add(component_id)
        if component.get("observability") == "unknown":
            blocking.append(f"component_{component_id or 'unknown'}_is_not_observable")
        if component.get("source_binding_status") != "verified" or not component.get("asset_code"):
            blocking.append(f"component_{component_id or 'unknown'}_source_is_not_verified")
        role = str(component.get("role") or "")
        if role not in {"speech", "bgm", "audio"} and not isinstance(component.get("geometry"), dict):
            blocking.append(f"component_{component_id or 'unknown'}_has_no_geometry")
        if component.get("audio_classification") == "unknown" and component.get("muted") is not True:
            blocking.append(f"component_{component_id or 'unknown'}_unknown_audio_is_not_muted")

    if audio_policy.get("max_active_speech") != 1:
        blocking.append("audio_policy_does_not_limit_speech_to_one")
    if audio_policy.get("max_active_bgm") != 1:
        blocking.append("audio_policy_does_not_limit_bgm_to_one")
    if audio_policy.get("unknown_audio_default_muted") is not True:
        blocking.append("audio_policy_does_not_mute_unknown_audio")
    if audio_policy.get("allow_overlapping_bgm_crossfade") is not False:
        blocking.append("audio_policy_allows_overlapping_bgm")
    blocking.extend(_audio_overlap_reasons(components))

    blocking = sorted(set(blocking))
    ready = False
    projection = {
        "template_code": template["template_code"],
        "template_name": template["name"],
        "revision_number": int(revision["revision_number"]),
        "projection_contract": "maitu-layout-projection.v1",
        "layout_fidelity": "approximate",
        "buildability": "reference_only",
        "projection_ready": ready,
        "manual_review_required": True,
        "blocking_reasons": blocking,
        "canvas": dict(revision.get("canvas") or {}),
        "scenes": scenes,
        "components": components,
        "audio_policy": audio_policy,
        "provenance": provenance,
    }
    projection["projection_fingerprint"] = canonical_fingerprint(projection)
    return projection


_SOURCE_FACT_MARKERS = (
    "价格", "到手", "库存", "限时", "优惠", "满减", "赠品", "sku", "原价", "折",
)


def build_content_strategy_projection(
    template: dict[str, Any], revision: dict[str, Any]
) -> dict[str, Any]:
    """Publish only abstract, reviewed strategy from a flattened external recording.

    The resulting projection is deliberately useful to content planning while
    remaining unusable as a Maitu layout or a source-product fact store.
    """
    strategy = dict(revision.get("content_strategy") or {})
    provenance = dict(revision.get("provenance") or {})
    source_session_codes = [str(code) for code in revision.get("source_session_codes") or [] if str(code)]
    program_outline = [item for item in strategy.get("program_outline") or [] if isinstance(item, dict)]
    reviewed_examples = [item for item in strategy.get("reviewed_examples") or [] if isinstance(item, dict)]
    removed_categories = {str(item) for item in strategy.get("removed_source_fact_categories") or []}
    blocking: list[str] = []

    if template.get("template_kind") != "content_strategy":
        blocking.append("CONTENT_STRATEGY_TEMPLATE_KIND_MISMATCH")
    if revision.get("contract_version") != "content-strategy.v2":
        blocking.append("CONTENT_STRATEGY_CONTRACT_MISMATCH")
    if not source_session_codes:
        blocking.append("CONTENT_STRATEGY_SOURCE_SESSION_REQUIRED")
    if not str(template.get("source_target_code") or "").strip():
        blocking.append("CONTENT_STRATEGY_SOURCE_TARGET_REQUIRED")
    if not str(strategy.get("target_category") or "").strip():
        blocking.append("CONTENT_STRATEGY_TARGET_CATEGORY_REQUIRED")
    if not program_outline:
        blocking.append("CONTENT_STRATEGY_PROGRAM_OUTLINE_REQUIRED")
    missing_categories = {
        "price", "promotion", "inventory", "product_identity", "source_brand", "host_identity"
    } - removed_categories
    if missing_categories:
        blocking.append("CONTENT_STRATEGY_SOURCE_FACT_REMOVAL_INCOMPLETE")

    module_keys = {str(item.get("module_key") or "") for item in program_outline}
    if "" in module_keys or len(module_keys) != len(program_outline):
        blocking.append("CONTENT_STRATEGY_MODULE_KEYS_INVALID")
    example_sources = {str(item.get("source_session_code") or "") for item in reviewed_examples}
    if not example_sources.issubset(set(source_session_codes)):
        blocking.append("CONTENT_STRATEGY_EXAMPLE_SOURCE_OUT_OF_SCOPE")
    if any(str(item.get("module_key") or "") not in module_keys for item in reviewed_examples):
        blocking.append("CONTENT_STRATEGY_EXAMPLE_MODULE_INVALID")
    for example in reviewed_examples:
        text = str(example.get("example_text") or "").lower()
        if any(marker in text for marker in _SOURCE_FACT_MARKERS) or "￥" in text or "¥" in text:
            blocking.append("CONTENT_STRATEGY_SOURCE_FACT_REMAINS")
            break

    requested_readiness = str(revision.get("content_readiness") or "review_required")
    if requested_readiness != "ready":
        blocking.append("CONTENT_STRATEGY_CONTENT_NOT_READY")
    blocking = sorted(set(blocking))
    content_readiness = "ready" if not blocking else "blocked"
    projection = {
        "template_code": template["template_code"],
        "template_name": template["name"],
        "revision_number": int(revision["revision_number"]),
        "projection_contract": "content-strategy.v2",
        "content_readiness": content_readiness,
        "layout_fidelity": revision.get("layout_fidelity", "none"),
        "buildability": "reference_only",
        "projection_ready": content_readiness == "ready",
        "manual_review_required": False,
        "blocking_reasons": blocking,
        "reference_capabilities": [
            "program_outline", "module_recipes", "interaction_policy", "material_cues", "reviewed_examples",
        ],
        "executable_capabilities": [],
        "blocked_operations": ["insert_template_component", "set_exact_geometry", "bind_external_material"],
        "content_strategy": strategy,
        "layout_reference": dict(revision.get("layout_reference") or {}),
        "source_session_codes": source_session_codes,
        "provenance": {
            **provenance,
            "source_target_code": template.get("source_target_code"),
            "source_session_codes": source_session_codes,
            "content_fact_boundary": "source facts are excluded from content-strategy.v2",
        },
        # Compatibility placeholders: legacy presentation clients still expect
        # the layout payload shape, but content consumers must use strategy.
        "canvas": {},
        "scenes": [],
        "components": [],
        "audio_policy": {},
    }
    projection["projection_fingerprint"] = canonical_fingerprint(projection)
    return projection


def _audio_overlap_reasons(components: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for bus in ("speech", "bgm"):
        intervals: list[tuple[float, float, str]] = []
        for component in components:
            if component.get("audio_classification") != bus or component.get("muted") is True:
                continue
            start = float(component.get("start_seconds") or 0)
            end_value = component.get("end_seconds")
            end = float(end_value) if end_value is not None else float("inf")
            intervals.append((start, end, str(component.get("component_id") or "unknown")))
        intervals.sort()
        previous: tuple[float, float, str] | None = None
        for interval in intervals:
            if previous is not None and interval[0] < previous[1]:
                reasons.append(f"{bus}_bus_overlap:{previous[2]}:{interval[2]}")
            if previous is None or interval[1] > previous[1]:
                previous = interval
    return reasons


@dataclass(slots=True)
class LiveObservationService:
    repository: Any

    def overview(self) -> dict[str, int]:
        return self.repository.overview()

    def create_watch_target(self, payload: WatchTargetCreate) -> dict[str, Any]:
        return self.repository.create_watch_target(payload.model_dump(mode="json"))

    def list_watch_targets(
        self, *, status: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        return self.repository.list_watch_targets(status=status, limit=limit, offset=offset)

    def get_watch_target(self, target_code: str) -> dict[str, Any]:
        row = self.repository.get_watch_target(target_code)
        if row is None:
            raise LiveObservationNotFoundError("Watch target not found")
        return row

    def update_watch_target(self, target_code: str, payload: WatchTargetUpdate) -> dict[str, Any]:
        row = self.repository.update_watch_target(
            target_code, payload.model_dump(mode="json", exclude_unset=True)
        )
        if row is None:
            raise LiveObservationNotFoundError("Watch target not found")
        return row

    def claim_watch_target(self, payload: SchedulerClaimRequest) -> dict[str, Any] | None:
        return self.repository.claim_watch_target(payload.worker_id, payload.lease_seconds)

    def heartbeat_watch_target(
        self, target_code: str, payload: SchedulerHeartbeatRequest
    ) -> dict[str, Any]:
        row = self.repository.heartbeat_watch_target(
            target_code,
            payload.worker_id,
            payload.claim_token,
            payload.lease_version,
            payload.lease_seconds,
        )
        if row is None:
            raise LiveObservationConflictError("watch-target lease is missing, expired, or fenced")
        return row

    def release_watch_target(
        self, target_code: str, payload: SchedulerReleaseRequest
    ) -> dict[str, Any]:
        row = self.repository.release_watch_target(
            target_code,
            payload.model_dump(mode="json"),
        )
        if row is None:
            raise LiveObservationConflictError("watch-target lease is missing, expired, or fenced")
        return row

    def create_capture_session(self, payload: CaptureSessionCreate) -> dict[str, Any]:
        return self.repository.create_capture_session(payload.model_dump(mode="json"))

    def finish_capture_session(
        self, session_code: str, payload: CaptureSessionFinish
    ) -> dict[str, Any]:
        row = self.repository.finish_capture_session(
            session_code,
            payload.model_dump(mode="json"),
            analysis_specs=default_chunk_analysis_specs(),
            aggregation_spec=default_aggregation_spec(),
        )
        if row is None:
            raise LiveObservationConflictError("capture session is missing or already terminal")
        return row

    def list_capture_sessions(
        self,
        *,
        target_code: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self.repository.list_capture_sessions(
            target_code=target_code, status=status, limit=limit, offset=offset
        )

    def get_capture_session(self, session_code: str) -> dict[str, Any]:
        row = self.repository.get_capture_session(session_code, include_children=True)
        if row is None:
            raise LiveObservationNotFoundError("Capture session not found")
        return row

    def add_channel(
        self, session_code: str, payload: CaptureChannelCreate
    ) -> dict[str, Any]:
        return self.repository.add_capture_channel(session_code, payload.model_dump(mode="json"))

    def finalize_chunk(
        self, session_code: str, payload: CaptureChunkFinalize
    ) -> dict[str, Any]:
        data = payload.model_dump(mode="json")
        data["relative_path"] = validate_storage_relative_path(data["relative_path"])
        return self.repository.finalize_capture_chunk(
            session_code,
            data,
            analysis_specs=default_chunk_analysis_specs(),
        )

    def register_event_batch(
        self, session_code: str, payload: RawEventBatchRegistration
    ) -> dict[str, Any]:
        data = payload.model_dump(mode="json")
        data["relative_path"] = validate_storage_relative_path(data["relative_path"])
        return self.repository.register_raw_event_batch(session_code, data)

    def append_timeline(
        self, session_code: str, payload: TimelineSpanCreate
    ) -> dict[str, Any]:
        existing = self.repository.list_timeline(session_code)
        data = payload.model_dump(mode="json")
        validate_timeline_append(existing, data)
        return self.repository.append_timeline_span(session_code, data)

    def get_timeline(self, session_code: str) -> list[dict[str, Any]]:
        if self.repository.get_capture_session(session_code, include_children=False) is None:
            raise LiveObservationNotFoundError("Capture session not found")
        return self.repository.list_timeline(session_code)

    def get_interaction_summary(
        self, session_code: str, bucket_seconds: int
    ) -> dict[str, Any]:
        if self.repository.get_capture_session(session_code, include_children=False) is None:
            raise LiveObservationNotFoundError("Capture session not found")
        batches = self.repository.list_interaction_batch_summaries(session_code)
        grouped: dict[datetime, dict[str, Any]] = {}
        for batch in batches:
            received_at = batch["first_received_at"]
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=UTC)
            epoch_seconds = int(received_at.timestamp())
            bucket_epoch = epoch_seconds - (epoch_seconds % bucket_seconds)
            bucket_start = datetime.fromtimestamp(bucket_epoch, UTC)
            bucket = grouped.setdefault(
                bucket_start,
                {
                    "bucket_start_at": bucket_start,
                    "bucket_end_at": bucket_start + timedelta(seconds=bucket_seconds),
                    "event_count": 0,
                    "event_types": {},
                },
            )
            bucket["event_count"] += int(batch.get("event_count") or 0)
            for event_type, count in (batch.get("event_types") or {}).items():
                bucket["event_types"][event_type] = (
                    bucket["event_types"].get(event_type, 0) + int(count)
                )
        buckets = [grouped[key] for key in sorted(grouped)]
        return {
            "session_code": session_code,
            "bucket_seconds": bucket_seconds,
            "precision": "batch_metadata",
            "total_event_count": sum(item["event_count"] for item in buckets),
            "buckets": buckets,
        }

    def create_clip_job(self, session_code: str, payload: ClipJobCreate) -> dict[str, Any]:
        timeline = self.get_timeline(session_code)
        if not timeline:
            raise LiveObservationConflictError("capture session has no normalized timeline")
        timeline_end = float(timeline[-1]["global_end_seconds"])
        if payload.requested_end_seconds > timeline_end + 0.001:
            raise LiveObservationConflictError("requested clip ends outside the normalized timeline")
        return self.repository.create_clip_job(session_code, payload.model_dump(mode="json"))

    def list_clip_jobs(
        self, *, session_code: str | None, status: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        return self.repository.list_clip_jobs(
            session_code=session_code, status=status, limit=limit, offset=offset
        )

    def claim_clip_job(self, payload: WorkClaimRequest) -> dict[str, Any] | None:
        return self.repository.claim_clip_job(payload.worker_id, payload.lease_seconds)

    def complete_clip_job(
        self, job_code: str, payload: ClipJobCompletion
    ) -> dict[str, Any]:
        data = payload.model_dump(mode="json")
        data["output_relative_path"] = validate_storage_relative_path(
            data["output_relative_path"]
        )
        row = self.repository.complete_clip_job(
            job_code, data.pop("worker_id"), data.pop("lease_token"), data
        )
        if row is None:
            raise LiveObservationConflictError("clip-job lease is missing, expired, or fenced")
        return row

    def fail_clip_job(self, job_code: str, payload: WorkFailure) -> dict[str, Any]:
        row = self.repository.fail_work(
            table="live_clip_jobs",
            code_column="clip_job_code",
            code=job_code,
            **payload.model_dump(mode="json"),
        )
        if row is None:
            raise LiveObservationConflictError("clip-job lease is missing, expired, or fenced")
        return row

    def create_analysis_run(
        self, session_code: str, payload: AnalysisRunCreate
    ) -> dict[str, Any]:
        return self.repository.create_analysis_run(session_code, payload.model_dump(mode="json"))

    def list_analysis_runs(
        self,
        *,
        session_code: str | None,
        analysis_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return self.repository.list_analysis_runs(
            session_code=session_code,
            analysis_type=analysis_type,
            status=status,
            limit=limit,
            offset=offset,
        )

    def claim_analysis_run(self, payload: WorkClaimRequest) -> dict[str, Any] | None:
        return self.repository.claim_analysis_run(payload.worker_id, payload.lease_seconds)

    def complete_analysis_run(
        self, run_code: str, payload: AnalysisRunCompletion
    ) -> dict[str, Any]:
        data = payload.model_dump(mode="json")
        if data.get("output_relative_path"):
            data["output_relative_path"] = validate_storage_relative_path(
                data["output_relative_path"]
            )
        row = self.repository.complete_analysis_run(
            run_code,
            data.pop("worker_id"),
            data.pop("lease_token"),
            data,
            aggregation_spec=default_aggregation_spec(),
        )
        if row is None:
            raise LiveObservationConflictError("analysis-run lease is missing, expired, or fenced")
        return row

    def fail_analysis_run(self, run_code: str, payload: WorkFailure) -> dict[str, Any]:
        row = self.repository.fail_work(
            table="live_analysis_runs",
            code_column="analysis_run_code",
            code=run_code,
            **payload.model_dump(mode="json"),
        )
        if row is None:
            raise LiveObservationConflictError("analysis-run lease is missing, expired, or fenced")
        return row

    def retry_analysis_run(
        self, run_code: str, payload: AnalysisRetryRequest
    ) -> dict[str, Any]:
        row = self.repository.retry_analysis_run(
            run_code,
            payload.worker_id,
            payload.reason,
        )
        if row is None:
            raise LiveObservationConflictError(
                "analysis run is not failed or has exhausted its bounded attempts"
            )
        return row

    def heartbeat_clip_job(
        self, job_code: str, payload: WorkHeartbeatRequest
    ) -> dict[str, Any]:
        row = self.repository.heartbeat_work(
            table="live_clip_jobs",
            code_column="clip_job_code",
            code=job_code,
            **payload.model_dump(mode="json"),
        )
        if row is None:
            raise LiveObservationConflictError("clip-job lease is missing, expired, or fenced")
        return row

    def heartbeat_analysis_run(
        self, run_code: str, payload: WorkHeartbeatRequest
    ) -> dict[str, Any]:
        row = self.repository.heartbeat_work(
            table="live_analysis_runs",
            code_column="analysis_run_code",
            code=run_code,
            **payload.model_dump(mode="json"),
        )
        if row is None:
            raise LiveObservationConflictError("analysis-run lease is missing, expired, or fenced")
        return row

    def create_room_template(self, payload: RoomTemplateCreate) -> dict[str, Any]:
        return self.repository.create_room_template(payload.model_dump(mode="json"))

    def list_room_templates(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        return self.repository.list_room_templates(limit=limit, offset=offset)

    def get_room_template(self, template_code: str) -> dict[str, Any]:
        row = self.repository.get_room_template(template_code, include_revisions=True)
        if row is None:
            raise LiveObservationNotFoundError("Room template not found")
        return row

    def create_room_template_revision(
        self, template_code: str, payload: RoomTemplateRevisionCreate
    ) -> dict[str, Any]:
        data = payload.model_dump(mode="json")
        data["content_fingerprint"] = canonical_fingerprint(data)
        return self.repository.create_room_template_revision(template_code, data)

    def publish_room_template_revision(
        self,
        template_code: str,
        revision_number: int,
        payload: RoomTemplatePublicationRequest,
    ) -> dict[str, Any]:
        template = self.get_room_template(template_code)
        revision = next(
            (
                item
                for item in template.get("revisions") or []
                if int(item["revision_number"]) == revision_number
            ),
            None,
        )
        if revision is None:
            raise LiveObservationNotFoundError("Room template revision not found")
        if revision.get("status") not in {"draft", "rejected"}:
            raise LiveObservationConflictError("Room template revision cannot be published again")
        projection = (
            build_content_strategy_projection(template, revision)
            if revision.get("contract_version") == "content-strategy.v2"
            else build_template_projection(template, revision)
        )
        if revision.get("contract_version") == "content-strategy.v2" and not projection["projection_ready"]:
            raise LiveObservationConflictError(
                "CONTENT_STRATEGY_PUBLICATION_BLOCKED: "
                + ", ".join(projection["blocking_reasons"])
            )
        return self.repository.publish_room_template_revision(
            template_code,
            revision_number,
            payload.model_dump(mode="json"),
            projection,
        )

    def get_room_template_projection(self, template_code: str) -> dict[str, Any]:
        row = self.repository.get_room_template_projection(template_code)
        if row is None:
            raise LiveObservationNotFoundError("Published room template projection not found")
        return row

    def claim_retention_candidates(
        self, payload: RetentionClaimRequest
    ) -> list[dict[str, Any]]:
        return self.repository.claim_retention_candidates(
            payload.worker_id,
            payload.lease_seconds,
            payload.limit,
        )

    def complete_retention(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = self.repository.complete_retention(payload)
        if row is None:
            raise LiveObservationConflictError("retention candidate is missing or no longer deletable")
        return row
