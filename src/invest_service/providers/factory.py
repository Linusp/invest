from typing import TYPE_CHECKING

from .akshare import AkshareFallbackProvider
from .base import MarketDataProvider
from .eastmoney import EastMoneyProvider
from .fallback import MarketFallbackProvider
from .tushare import TushareProvider

if TYPE_CHECKING:
    from ..config import Settings


def make_market_provider(settings: "Settings") -> MarketDataProvider:
    if settings.market_provider == "eastmoney":
        primary: MarketDataProvider = EastMoneyProvider(settings.eastmoney_token)
    else:
        primary = TushareProvider(settings.tushare_token)
    index_enabled = settings.index_fallback_provider == "akshare"
    etf_enabled = settings.etf_fallback_provider == "akshare"
    if index_enabled or etf_enabled:
        return MarketFallbackProvider(
            primary,
            AkshareFallbackProvider(),
            index_enabled=index_enabled,
            etf_enabled=etf_enabled,
        )
    return primary
