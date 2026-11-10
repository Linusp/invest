from typing import TYPE_CHECKING, Any, Callable

from ..models import AssetCategory
from .akshare import AkshareFallbackProvider
from .akshare_fund import AkshareFundProvider
from .base import MarketDataProvider, ProviderError
from .eastmoney import EastMoneyProvider
from .fallback import MarketFallbackProvider, PrioritizedMarketProvider
from .iwencai import IwencaiProvider
from .tushare import TushareProvider
from .wind import WindMarketProvider

if TYPE_CHECKING:
    from ..config import Settings


def _build_iwencai_hooks(
    settings: "Settings", session_factory: Any
) -> dict[str, Callable]:
    """问财在行情链里的额度记账与熔断。

    provider 层不直接碰数据库：这里把 SessionLocal 相关逻辑包成回调注入。
    """
    if session_factory is None:
        return {}

    def before_call() -> None:
        from ..services.provider_gate import ProviderGateService, ProviderUnavailable
        from ..services.provider_usage import ProviderUsageService

        with session_factory() as session:
            try:
                ProviderGateService(session).ensure_available("iwencai")
            except ProviderUnavailable as exc:
                # provider 层只认 ProviderError，保证 fallback 链能继续降级。
                raise ProviderError(str(exc)) from exc
            used = ProviderUsageService(session).count("iwencai")
            limit = settings.iwencai_daily_limit
            if limit > 0 and used >= limit:
                raise ProviderError(f"问财今日调用已达上限（{used}/{limit}）")

    def record_call() -> None:
        from ..services.provider_usage import ProviderUsageService

        with session_factory() as session:
            ProviderUsageService(session).record("iwencai")

    def on_quota_error(message: str) -> None:
        from ..services.provider_gate import ProviderGateService

        with session_factory() as session:
            ProviderGateService(session).hit_daily_limit("iwencai", message[:200])

    def catalog_needed() -> bool:
        from sqlalchemy import func, or_, select

        from ..models import Asset

        with session_factory() as session:
            return bool(
                session.scalar(
                    select(func.count())
                    .select_from(Asset)
                    .where(
                        or_(
                            Asset.symbol.like("%.HK"),
                            Asset.symbol.like("%.US"),
                        )
                    )
                )
            )

    def available() -> bool:
        from ..services.provider_gate import ProviderGateService

        with session_factory() as session:
            try:
                ProviderGateService(session).ensure_available("iwencai")
            except Exception:
                return False
            return True

    return {
        "available": available,
        "before_call": before_call,
        "record_call": record_call,
        "on_quota_error": on_quota_error,
        "catalog_needed": catalog_needed,
    }


def make_market_provider(
    settings: "Settings", session_factory: Any = None
) -> MarketDataProvider:
    eastmoney = EastMoneyProvider(settings.eastmoney_token)
    index_enabled = settings.index_fallback_provider == "akshare"
    etf_enabled = settings.etf_fallback_provider == "akshare"

    if settings.market_provider == "eastmoney":
        primary: MarketDataProvider = eastmoney
        if index_enabled or etf_enabled:
            return MarketFallbackProvider(
                primary,
                AkshareFallbackProvider(etf_history_provider=eastmoney),
                index_enabled=index_enabled,
                etf_enabled=etf_enabled,
            )
        return primary

    tushare = TushareProvider(settings.tushare_token)
    iwencai = IwencaiProvider(
        settings.iwencai_api_key, **_build_iwencai_hooks(settings, session_factory)
    )
    akshare = AkshareFallbackProvider(etf_history_provider=eastmoney)
    fund = AkshareFundProvider()
    wind_key = settings.wind_key()
    wind = WindMarketProvider(wind_key) if wind_key else None

    if settings.market_provider_order == "configured_first":
        # 旧口径：Tushare 主源、AkShare 兜底。
        primary = tushare
        if index_enabled or etf_enabled:
            return MarketFallbackProvider(
                primary,
                akshare,
                index_enabled=index_enabled,
                etf_enabled=etf_enabled,
            )
        return primary

    # free_first：按 PROVIDER_PRIORITY 组装每个类别的历史行情链。
    # 免费源 → Tushare → Wind / 问财（每日额度）→ 后续可再加 iFinD。
    providers: dict[str, MarketDataProvider | None] = {
        "eastmoney": eastmoney,
        "akshare": akshare,
        "tushare": tushare,
        "wind": wind,
        "iwencai": iwencai if settings.iwencai_api_key else None,
    }
    # 场外基金没有交易所行情，akshare 走独立的净值/目录实现。
    fund_providers = {**providers, "akshare": fund}
    allowed: dict[AssetCategory, set[str]] = {
        AssetCategory.STOCK: {"eastmoney", "akshare", "tushare", "wind", "iwencai"},
        AssetCategory.INDEX: (
            {"akshare", "tushare", "wind", "iwencai"}
            if index_enabled
            else {"tushare", "wind", "iwencai"}
        ),
        AssetCategory.ETF: (
            {"akshare", "tushare", "wind", "iwencai"}
            if etf_enabled
            else {"eastmoney", "tushare", "wind", "iwencai"}
        ),
        AssetCategory.FUND: {"akshare", "wind"},
    }
    per_category = {AssetCategory.FUND: fund_providers}

    order = [
        name.strip().lower()
        for name in settings.provider_priority.split(",")
        if name.strip()
    ]
    history_providers: dict[AssetCategory, tuple[MarketDataProvider, ...]] = {}
    for category, names in allowed.items():
        source = per_category.get(category, providers)
        chain = [
            provider
            for name in order
            if (provider := source.get(name)) is not None and name in names
        ]
        history_providers[category] = tuple(chain)

    search_providers: list[MarketDataProvider] = [eastmoney]
    if etf_enabled:
        search_providers.append(akshare)
    # 场外基金的目录也进搜索索引，否则只能靠手输代码登记。
    search_providers.append(fund)
    if settings.iwencai_api_key:
        search_providers.append(iwencai)
    search_providers.append(tushare)

    return PrioritizedMarketProvider(search_providers, history_providers)
