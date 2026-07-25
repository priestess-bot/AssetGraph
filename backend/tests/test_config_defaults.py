from pathlib import Path

from app.core.config import Settings


def test_qwen3_timeout_default_allows_cold_model_loads() -> None:
    assert Settings.model_fields["qwen3_timeout_seconds"].default >= 600.0


def test_video_production_defaults_use_data_volume_and_safe_lease_intervals() -> None:
    assert Settings.model_fields["asset_materials_root"].default == Path(__file__).resolve().parents[2] / "素材"
    assert Settings.model_fields["video_production_root"].default == Path(
        "/DATA/Downloads/AssetGraph/video-productions"
    )
    assert Settings.model_fields["video_production_worker_lease_seconds"].default == 300
    assert Settings.model_fields["video_production_worker_heartbeat_seconds"].default == 30
    assert Settings.model_fields["maitu_mirror_root"].default == Path(
        "/DATA/Downloads/AssetGraph/maitu-mirror"
    )
    assert Settings.model_fields["material_analysis_root"].default == Path(
        "/DATA/Downloads/AssetGraph/material-analysis"
    )
    assert Settings.model_fields["live_research_root"].default == Path(
        "/DATA/Downloads/AssetGraph/live-research"
    )
