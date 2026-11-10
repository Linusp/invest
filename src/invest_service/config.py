from functools import lru_cache
from pathlib import Path
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
    # EastMoney sector (板块) capital-flow collection.
    sector_flow_enabled: bool = False
    sector_flow_lookback_days: int = Field(default=30, ge=1, le=90)
    # Refresh cadence while trading (minutes); 0 disables intraday refresh.
    sector_flow_update_minutes: int = Field(default=0, ge=0)
    # Daily (EOD) backfill time on trading days.
    sector_flow_update_hour: int = Field(default=15, ge=0, le=23)
    sector_flow_update_minute: int = Field(default=40, ge=0, le=59)
    # MarketScope (SECTOR) auto-sync for the top-N tracked boards only.
    sector_flow_sync_scopes_enabled: bool = True
    sector_flow_sync_scopes_top: int = Field(default=30, ge=1, le=200)
    sector_flow_sync_scopes_parent: str | None = "em_industry"

    # iFinD MCP real-time quote snapshots. The key may be given inline or via a
    # mounted secret file; the file form keeps it out of .env and compose files.
    ifind_mcp_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_IFIND_MCP_KEY", "IFIND_MCP_KEY"),
    )
    ifind_mcp_key_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_IFIND_MCP_KEY_FILE", "IFIND_MCP_KEY_FILE"),
    )
    quote_snapshot_enabled: bool = False
    quote_snapshot_interval_minutes: int = Field(default=30, ge=5)
    # 只抓自选标的：每次约 6 次 MCP 调用，避免把整个目录都拉一遍。
    quote_snapshot_favorites_only: bool = True

    # Wind（万得）MCP 行情源；与 iFinD 一样支持密钥文件，避免明文进配置。
    # 会消耗 Wind 积分（而非普通调用额度）的工具，默认禁用，逗号分隔。
    wind_blocked_tools: str = "get_company_announcements"
    wind_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_WIND_API_KEY", "WIND_API_KEY"),
    )
    wind_api_key_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_WIND_API_KEY_FILE", "WIND_API_KEY_FILE"),
    )
    # 盈米基金 MCP（基金/组合/投研能力）。
    yingmi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_YINGMI_API_KEY", "YINGMI_API_KEY"),
    )
    # 东方财富妙想 MCP（Choice 数据库）。
    mx_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_MX_API_KEY", "MX_API_KEY"),
    )
    # 易方达指数直通车（指数 / ETF / 场外指数基金）。
    indexhub_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_INDEXHUB_API_KEY", "INDEX_HUB_API_KEY"),
    )
    # 通达信 TdxAiData 后台数据服务（积分制）。
    tdx_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INVEST_TDX_API_KEY", "TDX_API_KEY"),
    )
    # 历史行情的源优先级（从高到低，逗号分隔）。
    provider_priority: str = "akshare,eastmoney,tushare,wind,iwencai"
    # 外部能力（Wind/iFinD/问财）的响应缓存，减少额度消耗。
    external_cache_enabled: bool = True
    # 每日调用上限（0 = 不限制）。问财进阶版约 500 次/天，iFinD 试用为总量额度。
    wind_daily_limit: int = Field(default=0, ge=0)
    iwencai_daily_limit: int = Field(default=0, ge=0)
    yingmi_daily_limit: int = Field(default=0, ge=0)
    mx_daily_limit: int = Field(default=0, ge=0)
    indexhub_daily_limit: int = Field(default=0, ge=0)
    tdx_daily_limit: int = Field(default=0, ge=0)
    ifind_daily_limit: int = Field(default=0, ge=0)

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

    def wind_key(self) -> str | None:
        """Resolve the Wind MCP key, preferring the mounted secret file."""
        if self.wind_api_key:
            return self.wind_api_key.strip() or None
        if self.wind_api_key_file:
            try:
                return Path(self.wind_api_key_file).read_text(encoding="utf-8").strip() or None
            except OSError:
                return None
        return None

    def ifind_key(self) -> str | None:
        """Resolve the iFinD MCP key from config, falling back to the secret file."""
        if self.ifind_mcp_key:
            return self.ifind_mcp_key.strip() or None
        if self.ifind_mcp_key_file:
            try:
                return Path(self.ifind_mcp_key_file).read_text(encoding="utf-8").strip() or None
            except OSError:
                return None
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
