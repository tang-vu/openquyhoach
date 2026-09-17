"""Runtime configuration. Everything is overridable via OQH_* env vars."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OQH_", env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    log_format: str = "console"  # console | json

    database_url: str = "postgresql+psycopg://oqh:oqh@localhost:5432/openquyhoach"

    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_artifacts: str = "oqh-artifacts"
    s3_bucket_published: str = "oqh-published"
    s3_secure: bool = False

    queue_backend: str = "inline"  # inline | redis
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000"
    api_max_bbox_deg2: float = 4.0
    admin_token: str = "dev-admin-token"

    fetch_user_agent: str = "OpenQuyHoach/0.1 (+https://github.com/openquyhoach/openquyhoach)"
    fetch_max_bytes: int = 500 * 1024 * 1024
    fetch_timeout_seconds: float = 60.0
    fetch_allow_private_ips: bool = False

    ai_enabled: bool = False

    sources_dir: str = "sources"

    @field_validator("queue_backend")
    @classmethod
    def _queue(cls, v: str) -> str:
        if v not in {"inline", "redis"}:
            raise ValueError("queue_backend must be inline|redis")
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
