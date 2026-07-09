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
    asset_retrieval_documents_path: str = "docs/asset-numbering/asset_retrieval_documents_20260709.jsonl"
    asset_retrieval_embeddings_path: str = "docs/asset-numbering/asset_retrieval_embeddings_20260709.jsonl"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "assetgraph"
    minio_secret_key: str = "assetgraph-secret"
    minio_bucket: str = "assetgraph"
    minio_secure: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
