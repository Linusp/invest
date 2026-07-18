from datetime import date

from ..models import AssetCategory
from .base import MarketDataProvider, ProviderAsset, ProviderBar, ProviderError


class MarketFallbackProvider(MarketDataProvider):
    def __init__(
        self,
        primary: MarketDataProvider,
        fallback: MarketDataProvider,
        *,
        index_enabled: bool = True,
        etf_enabled: bool = True,
    ):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.index_enabled = index_enabled
        self.etf_enabled = etf_enabled

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        primary_error: ProviderError | None = None
        try:
            primary_results = self.primary.search(query, limit, category)
        except ProviderError as exc:
            primary_error = exc
            primary_results = []

        should_search_etf = self.etf_enabled and category in (None, AssetCategory.ETF)
        if not should_search_etf or (category == AssetCategory.ETF and primary_results):
            if primary_error is not None:
                raise primary_error
            return primary_results

        try:
            fallback_results = self.fallback.search(
                query, limit=limit, category=AssetCategory.ETF
            )
        except ProviderError:
            if primary_error is not None:
                raise primary_error
            return primary_results

        by_symbol = {asset.symbol: asset for asset in primary_results}
        for asset in fallback_results:
            by_symbol.setdefault(asset.symbol, asset)
        return list(by_symbol.values())[:limit]

    def history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        fallback_enabled = (
            asset.category == AssetCategory.INDEX
            and self.index_enabled
            or asset.category == AssetCategory.ETF
            and self.etf_enabled
        )
        if not fallback_enabled:
            return self.primary.history(asset, start_date, end_date)

        primary_error: ProviderError | None = None
        try:
            bars = self.primary.history(asset, start_date, end_date)
            if bars:
                return bars
        except ProviderError as exc:
            primary_error = exc

        try:
            return self.fallback.history(asset, start_date, end_date)
        except ProviderError as fallback_error:
            if primary_error is None:
                raise
            raise ProviderError(
                f"{primary_error}; market fallback failed: {fallback_error}"
            ) from fallback_error


IndexFallbackProvider = MarketFallbackProvider
