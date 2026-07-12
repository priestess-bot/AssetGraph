from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "assetgraph"
    minio_secret_key: str = "assetgraph-secret"
    minio_bucket: str = "assetgraph"
    minio_secure: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
