from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Invest Service"
    environment: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./invest.db"
    market_provider: Literal["tushare", "eastmoney"] = "tushare"
    market_provider_order: Literal["free_first", "configured_first"] = "free_first"
    tushare_token: str | None = None
    iwencai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "INVEST_IWENCAI_API_KEY",
            "IWENCAI_API_KEY",
        ),
    )
    eastmoney_token: str = "D43BF722C8E33BDC906FB84D85E326E8"
    index_fallback_provider: Literal["akshare", "none"] = "akshare"
    etf_fallback_provider: Literal["akshare", "none"] = "akshare"
    reporting_currency: str = Field(default="CNY", min_length=3, max_length=3)
    auto_update_enabled: bool = True
    auto_update_interval_minutes: int = Field(default=60, ge=1)
    auto_update_lookback_days: int = Field(default=10, ge=1, le=3650)
    search_index_update_hour: int = Field(default=3, ge=0, le=23)
    exchange_rate_update_hour: int = Field(default=23, ge=0, le=23)
    celery_broker_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = []
    mcp_allowed_hosts: list[str] = [
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "app",
        "app:*",
    ]
    mcp_allowed_origins: list[str] = []

    model_config = SettingsConfigDict(
        env_prefix="INVEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Select an installed SQLAlchemy driver for common URL forms."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if value.startswith("mysql://"):
            return value.replace("mysql://", "mysql+pymysql://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
