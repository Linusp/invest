from typing import TYPE_CHECKING

from ..models import AssetCategory
from .akshare import AkshareFallbackProvider
from .base import MarketDataProvider
from .eastmoney import EastMoneyProvider
from .fallback import MarketFallbackProvider, PrioritizedMarketProvider
from .tushare import TushareProvider

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
    akshare = AkshareFallbackProvider(etf_history_provider=eastmoney)
    if settings.market_provider_order == "free_first":
        search_providers: list[MarketDataProvider] = [eastmoney]
        if etf_enabled:
            search_providers.append(akshare)
        search_providers.append(tushare)
        return PrioritizedMarketProvider(
            search_providers,
            {
                AssetCategory.STOCK: (akshare, eastmoney, tushare),
                AssetCategory.INDEX: (
                    (akshare, tushare) if index_enabled else (tushare,)
                ),
                AssetCategory.ETF: (
                    (akshare, tushare) if etf_enabled else (eastmoney, tushare)
                ),
            },
        )

    primary = tushare
    if index_enabled or etf_enabled:
        return MarketFallbackProvider(
            primary,
            akshare,
            index_enabled=index_enabled,
            etf_enabled=etf_enabled,
        )
    return primary
