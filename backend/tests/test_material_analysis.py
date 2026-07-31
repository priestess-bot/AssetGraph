from __future__ import annotations

import json
import os
import stat
import threading
from types import SimpleNamespace
from pathlib import Path

import pytest

import app.services.material_analysis as material_analysis_module
from app.domain.contracts import DataClassification
from app.schemas.material_analysis import MaterialSemanticObservation
from app.services.material_analysis import (
    MaterialAnalysisError,
    MaterialAnalysisJobProcessor,
    MaterialAnalysisLeaseHeartbeat,
    MaterialAnalysisLeaseLostError,
    MaterialVisionAnalyzer,
    RepresentativeFrameExtractor,
    merge_material_profile,
    parse_gemini_manual_submission,
    sha256_file,
)
from app.services.providers import (
    ModelCapability,
    ProviderBinding,
    ProviderInvocationOutput,
    ProviderRouter,
)


FINGERPRINT = "a" * 64


def observation(**overrides: object) -> MaterialSemanticObservation:
    payload: dict[str, object] = {
        "asset_code": "AG-VID-1",
        "asset_fingerprint": FINGERPRINT,
        "summary": "product video",
        "semantic_roles": ["product_visual"],
        "product_identities": ["PRO"],
        "people": [],
        "visible_text": ["PRO"],
        "palette": ["red"],
        "style_tags": ["commercial"],
        "audio_class": "unknown",
        "original_audio_recommended": False,
        "reusable_as_whole": True,
        "scenes": [],
        "warnings": [],
    }
    payload.update(overrides)
    return MaterialSemanticObservation.model_validate(payload)


def test_sha256_file_streams_a_stable_identity(tmp_path: Path) -> None:
    source = tmp_path / "large.mov"
    source.write_bytes(b"abc" * 1000)
    assert sha256_file(source) == sha256_file(source)


def test_representative_timestamps_are_bounded_and_scene_aware(tmp_path: Path) -> None:
    extractor = RepresentativeFrameExtractor(tmp_path, min_frames=6, max_frames=10)
    timestamps = extractor._select_timestamps(60.0, [1.0, 5.0, 10.0, 30.0, 50.0])

    assert 6 <= len(timestamps) <= 10
    assert timestamps[0][0] == 0.0
    assert timestamps[-1][0] < 60.0
    assert any(reason == "scene_change" for _, reason in timestamps)
    assert timestamps == sorted(timestamps)


def test_representative_frames_are_private_and_immutable(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-video")
    extractor = RepresentativeFrameExtractor(tmp_path / "analysis", min_frames=2, max_frames=2)
    extractor._scene_times = lambda _path: []  # type: ignore[method-assign]
    extractor._ffmpeg_version = lambda: "ffmpeg-test"  # type: ignore[method-assign]
    extractor._extract_one = (  # type: ignore[method-assign]
        lambda _source, timestamp, output, **_kwargs: output.write_bytes(f"frame-{timestamp}".encode())
    )
    technical = {
        "duration_seconds": 1.0,
        "video": {"has_alpha": False},
    }

    manifest = extractor.extract(
        asset_code="AG-VID-1",
        source_path=source,
        source_fingerprint=FINGERPRINT,
        technical=technical,
    )

    if os.name != "nt":
        assert stat.S_IMODE(extractor.root.stat().st_mode) == 0o700
    for frame in manifest.frames:
        path = extractor.root / frame.relative_path
        if os.name != "nt":
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

    extractor._extract_one = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must reuse immutable frames"))
    )
    repeated = extractor.extract(
        asset_code="AG-VID-1",
        source_path=source,
        source_fingerprint=FINGERPRINT,
        technical=technical,
    )
    assert repeated.frames == manifest.frames


def test_automatic_profile_is_immediately_provisional() -> None:
    profile = merge_material_profile(technical={"duration_seconds": 10}, automatic=observation())
    assert profile.status == "provisional"
    assert profile.semantic.audio_class == "unknown"


def test_material_analysis_identity_uses_frame_manifest_not_machine_local_cache_paths() -> None:
    class ImageAdapter:
        adapter_code = "test-image-adapter"
        capabilities = frozenset({ModelCapability.IMAGE_UNDERSTANDING})

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def invoke(self, **kwargs: object) -> ProviderInvocationOutput:
            self.calls.append(kwargs)
            return ProviderInvocationOutput(
                content=observation().model_dump(),
                provider_response_id="provider-response",
                actual_model="test-image-model",
                usage={},
                latency_ms=1,
            )

    class EvidenceSink:
        def __init__(self) -> None:
            self.items: list[dict[str, object]] = []

        def persist_provider_invocation(self, evidence: dict[str, object]) -> str:
            self.items.append(evidence)
            return "ART-EVIDENCE-001"

    adapter = ImageAdapter()
    sink = EvidenceSink()
    router = ProviderRouter(
        [
            ProviderBinding(
                strategy_revision="material-test.v1",
                capability=ModelCapability.IMAGE_UNDERSTANDING,
                adapter=adapter,
                provider_model="test-image-model",
                allowed_classifications=frozenset({DataClassification.CONFIDENTIAL}),
            )
        ],
        sink,
    )
    analyzer = MaterialVisionAnalyzer(router, strategy_revision="material-test.v1")
    manifest = {"frames": [{"frame_code": "FRAME-001", "sha256": "b" * 64}]}

    _, first = analyzer.analyze(
        asset_code="AG-VID-1",
        asset_fingerprint=FINGERPRINT,
        image_paths=[Path("/worker-a/frames/FRAME-001.png")],
        frame_manifest=manifest,
    )
    _, second = analyzer.analyze(
        asset_code="AG-VID-1",
        asset_fingerprint=FINGERPRINT,
        image_paths=[Path("/worker-b/frames/FRAME-001.png")],
        frame_manifest=manifest,
    )

    assert first.input_fingerprint == second.input_fingerprint
    assert adapter.calls[0]["inputs"]["image_paths"] == ["/worker-a/frames/FRAME-001.png"]
    assert adapter.calls[1]["inputs"]["image_paths"] == ["/worker-b/frames/FRAME-001.png"]
    assert "/worker-a/frames/FRAME-001.png" not in str(sink.items[0])


def test_manual_product_identity_conflict_requires_review() -> None:
    profile = merge_material_profile(
        technical={"duration_seconds": 10},
        automatic=observation(product_identities=["PRO"]),
        manual=observation(product_identities=["MASTER"], audio_class="speech"),
    )

    assert profile.status == "review_required"
    assert any(conflict.field == "product_identities" and conflict.severity == "critical" for conflict in profile.conflicts)
    assert profile.semantic.audio_class == "speech"


def test_gemini_submission_requires_exact_task_and_file_fingerprint() -> None:
    raw = json.dumps(
        {
            "analysis_task_code": "MAT-AN-1",
            "asset_code": "AG-VID-1",
            "asset_fingerprint": FINGERPRINT,
            "prompt_schema_version": "gemini-material-analysis-v1",
            "observation": observation().model_dump(),
        }
    )

    parsed = parse_gemini_manual_submission(
        f"```json\n{raw}\n```",
        expected_task_code="MAT-AN-1",
        expected_asset_code="AG-VID-1",
        expected_asset_fingerprint=FINGERPRINT,
    )
    assert parsed.analysis_task_code == "MAT-AN-1"

    with pytest.raises(MaterialAnalysisError, match="fingerprint"):
        parse_gemini_manual_submission(
            raw,
            expected_task_code="MAT-AN-1",
            expected_asset_code="AG-VID-1",
            expected_asset_fingerprint="b" * 64,
        )


def test_material_analysis_heartbeat_renews_and_surfaces_lease_loss() -> None:
    renewed = threading.Event()

    def renew() -> bool:
        renewed.set()
        return False

    with MaterialAnalysisLeaseHeartbeat(renew=renew, interval_seconds=0.01) as heartbeat:
        assert renewed.wait(timeout=1)
        with pytest.raises(MaterialAnalysisLeaseLostError, match="heartbeat failed"):
            heartbeat.raise_if_failed()


def test_job_processor_checks_lease_after_model_before_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(material_analysis_module, "sha256_file", lambda _path: FINGERPRINT)
    monkeypatch.setattr(
        material_analysis_module,
        "probe_media",
        lambda _path: {"duration_seconds": 1.0, "video": {"has_alpha": False}},
    )

    class FakeWorkflow:
        completed = False

        def complete_video_analysis(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            self.completed = True
            return {}

    workflow = FakeWorkflow()
    extractor = SimpleNamespace(
        root=tmp_path,
        extract=lambda **_kwargs: SimpleNamespace(frames=(), as_dict=lambda: {"frames": []}),
    )
    analyzer = SimpleNamespace(
        analyze=lambda **_kwargs: (
            observation(),
            SimpleNamespace(
                provider="openai",
                requested_model="gpt-5.6-sol",
                actual_model="gpt-5.6-sol",
                response_id="response-1",
                input_fingerprint="b" * 64,
                output_fingerprint="c" * 64,
                usage={},
                latency_ms=1,
            ),
        )
    )
    processor = MaterialAnalysisJobProcessor(
        workflow=workflow,
        analyzer=analyzer,
        extractor=extractor,
        asset_materials_root=tmp_path,
        maitu_mirror_root=tmp_path / "mirror",
    )
    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 5:
            raise MaterialAnalysisLeaseLostError("lost after model")

    with pytest.raises(MaterialAnalysisLeaseLostError, match="lost after model"):
        processor.process(
            {
                "analysis_code": "MAT-AN-1",
                "asset_code": "AG-VID-1",
                "asset_fingerprint": FINGERPRINT,
                "source_relative_path": source.name,
                "source_root_kind": "asset_materials",
                "lease_token": "lease-token",
            },
            worker_id="worker-1",
            lease_guard=guard,
        )

    assert guard_calls == 5
    assert workflow.completed is False
