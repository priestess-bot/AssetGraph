import os
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = Path(os.environ.get("ASSETGRAPH_ENV_FILE", REPO_ROOT / ".env")).resolve()


class Settings(BaseSettings):
    app_name: str = "AssetGraph"
    app_env: str = "local"
    api_prefix: str = "/api"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "assetgraph"
    postgres_user: str = "assetgraph"
    postgres_password: str = "assetgraph"

    qwen3_base_url: str = "http://127.0.0.1:8010"
    qwen3_api_key: str = "local-no-auth"
    qwen3_embedding_model: str = "qwen3-embedding-4b-local"
    qwen3_rerank_model: str = "qwen3-reranker-4b-local"
    qwen3_embedding_dimensions: int = 1024
    qwen3_timeout_seconds: float = 600.0

    # Online generation is deliberately separate from the local Qwen
    # retrieval service. Secrets are never copied into durable job payloads.
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "ASSETGRAPH_DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "ASSETGRAPH_DEEPSEEK_BASE_URL"),
    )
    deepseek_pro_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias=AliasChoices("DEEPSEEK_PRO_MODEL", "ASSETGRAPH_DEEPSEEK_PRO_MODEL"),
    )
    deepseek_flash_model: str = Field(
        default="deepseek-v4-flash",
        validation_alias=AliasChoices("DEEPSEEK_FLASH_MODEL", "ASSETGRAPH_DEEPSEEK_FLASH_MODEL"),
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "ASSETGRAPH_OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "ASSETGRAPH_OPENAI_BASE_URL"),
    )
    openai_image_bulk_model: str = Field(
        default="gpt-5.6-terra",
        validation_alias=AliasChoices("OPENAI_IMAGE_BULK_MODEL", "ASSETGRAPH_OPENAI_IMAGE_BULK_MODEL"),
    )
    openai_image_review_model: str = Field(
        default="gpt-5.6-sol",
        validation_alias=AliasChoices("OPENAI_IMAGE_REVIEW_MODEL", "ASSETGRAPH_OPENAI_IMAGE_REVIEW_MODEL"),
    )
    openai_video_frame_model: str = Field(
        default="gpt-5.6-sol",
        validation_alias=AliasChoices("OPENAI_VIDEO_FRAME_MODEL", "ASSETGRAPH_OPENAI_VIDEO_FRAME_MODEL"),
    )
    openai_transcription_model: str = Field(
        default="gpt-4o-transcribe-diarize",
        validation_alias=AliasChoices("OPENAI_TRANSCRIPTION_MODEL", "ASSETGRAPH_OPENAI_TRANSCRIPTION_MODEL"),
    )
    online_model_timeout_seconds: float = Field(
        default=180.0,
        ge=1.0,
        validation_alias=AliasChoices("ONLINE_MODEL_TIMEOUT_SECONDS", "ASSETGRAPH_ONLINE_MODEL_TIMEOUT_SECONDS"),
    )
    online_model_max_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias=AliasChoices("ONLINE_MODEL_MAX_ATTEMPTS", "ASSETGRAPH_ONLINE_MODEL_MAX_ATTEMPTS"),
    )
    maitu_reconciliation_operator_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ASSETGRAPH_MAITU_RECONCILIATION_OPERATOR_TOKEN",
            "MAITU_RECONCILIATION_OPERATOR_TOKEN",
        ),
    )
    maitu_reconciliation_operator_id: str = Field(
        default="configured-maitu-operator",
        validation_alias=AliasChoices(
            "ASSETGRAPH_MAITU_RECONCILIATION_OPERATOR_ID",
            "MAITU_RECONCILIATION_OPERATOR_ID",
        ),
    )
    maitu_script_layout_worker_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN",
            "MAITU_SCRIPT_LAYOUT_WORKER_TOKEN",
        ),
    )
    maitu_readback_attestation_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ASSETGRAPH_MAITU_READBACK_ATTESTATION_KEY",
            "MAITU_READBACK_ATTESTATION_KEY",
        ),
    )
    maitu_authority_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ASSETGRAPH_MAITU_AUTHORITY_TOKEN", "MAITU_AUTHORITY_TOKEN"),
    )
    maitu_authority_base_url: str = Field(
        default="https://api.maituai.com",
        validation_alias=AliasChoices("ASSETGRAPH_MAITU_AUTHORITY_BASE_URL", "MAITU_AUTHORITY_BASE_URL"),
    )
    maitu_authority_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "ASSETGRAPH_MAITU_AUTHORITY_TIMEOUT_SECONDS",
            "MAITU_AUTHORITY_TIMEOUT_SECONDS",
        ),
    )
    asset_retrieval_documents_path: str = "docs/asset-numbering/asset_retrieval_documents_20260709.jsonl"
    asset_retrieval_embeddings_path: str = "docs/asset-numbering/asset_retrieval_embeddings_20260709.jsonl"

    video_production_root: Path = Field(
        default=Path("/DATA/Downloads/AssetGraph/video-productions"),
        validation_alias=AliasChoices("ASSETGRAPH_VIDEO_PRODUCTION_ROOT", "VIDEO_PRODUCTION_ROOT"),
    )
    video_production_worker_lease_seconds: int = Field(
        default=300,
        ge=30,
        validation_alias=AliasChoices(
            "ASSETGRAPH_VIDEO_PRODUCTION_WORKER_LEASE_SECONDS",
            "VIDEO_PRODUCTION_WORKER_LEASE_SECONDS",
        ),
    )
    video_production_worker_heartbeat_seconds: int = Field(
        default=30,
        ge=5,
        validation_alias=AliasChoices(
            "ASSETGRAPH_VIDEO_PRODUCTION_WORKER_HEARTBEAT_SECONDS",
            "VIDEO_PRODUCTION_WORKER_HEARTBEAT_SECONDS",
        ),
    )
    video_production_worker_poll_seconds: float = Field(
        default=1.0,
        ge=0.1,
        validation_alias=AliasChoices(
            "ASSETGRAPH_VIDEO_PRODUCTION_WORKER_POLL_SECONDS",
            "VIDEO_PRODUCTION_WORKER_POLL_SECONDS",
        ),
    )

    maitu_mirror_root: Path = Field(
        default=Path("/DATA/Downloads/AssetGraph/maitu-mirror"),
        validation_alias=AliasChoices("ASSETGRAPH_MAITU_MIRROR_ROOT", "MAITU_MIRROR_ROOT"),
    )
    material_analysis_root: Path = Field(
        default=Path("/DATA/Downloads/AssetGraph/material-analysis"),
        validation_alias=AliasChoices("ASSETGRAPH_MATERIAL_ANALYSIS_ROOT", "MATERIAL_ANALYSIS_ROOT"),
    )
    live_research_root: Path = Field(
        default=Path("/DATA/Downloads/AssetGraph/live-research"),
        validation_alias=AliasChoices("ASSETGRAPH_LIVE_RESEARCH_ROOT", "LIVE_RESEARCH_ROOT"),
    )

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "assetgraph"
    minio_secret_key: str = "assetgraph-secret"
    minio_bucket: str = "assetgraph"
    minio_secure: bool = False

    model_config = SettingsConfigDict(env_file=DEFAULT_ENV_FILE, extra="ignore", populate_by_name=True)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
