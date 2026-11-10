from typing import TYPE_CHECKING

from ..models import AssetCategory
from .akshare import AkshareFallbackProvider
from .base import MarketDataProvider
from .eastmoney import EastMoneyProvider
from .fallback import MarketFallbackProvider, PrioritizedMarketProvider
from .iwencai import IwencaiProvider
from .tushare import TushareProvider
from .wind import WindMarketProvider

if TYPE_CHECKING:
    from ..config import Settings


def make_market_provider(settings: "Settings") -> MarketDataProvider:
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
    iwencai = IwencaiProvider(settings.iwencai_api_key)
    akshare = AkshareFallbackProvider(etf_history_provider=eastmoney)
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
    }

    order = [
        name.strip().lower()
        for name in settings.provider_priority.split(",")
        if name.strip()
    ]
    history_providers: dict[AssetCategory, tuple[MarketDataProvider, ...]] = {}
    for category, names in allowed.items():
        chain = [
            provider
            for name in order
            if (provider := providers.get(name)) is not None and name in names
        ]
        history_providers[category] = tuple(chain)

    search_providers: list[MarketDataProvider] = [eastmoney]
    if etf_enabled:
        search_providers.append(akshare)
    if settings.iwencai_api_key:
        search_providers.append(iwencai)
    search_providers.append(tushare)

    return PrioritizedMarketProvider(search_providers, history_providers)
