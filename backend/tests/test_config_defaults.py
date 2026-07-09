from app.core.config import Settings


def test_qwen3_timeout_default_allows_cold_model_loads() -> None:
    assert Settings.model_fields["qwen3_timeout_seconds"].default >= 600.0
