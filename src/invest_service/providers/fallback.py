import logging
from dataclasses import replace
from datetime import date
from typing import Mapping, Sequence

from ..models import AssetCategory
from .base import MarketDataProvider, ProviderAsset, ProviderBar, ProviderError

logger = logging.getLogger(__name__)


def _merge_catalog_asset(
    current: ProviderAsset | None,
    incoming: ProviderAsset,
) -> ProviderAsset:
    if current is None:
        return incoming
    aliases = list(current.aliases)
    aliases.extend(incoming.aliases)
    if incoming.name.casefold() != current.name.casefold():
        aliases.append(incoming.name)
    aliases = list(dict.fromkeys(alias for alias in aliases if alias))
    tags = tuple(dict.fromkeys((*current.default_tags, *incoming.default_tags)))
    return replace(current, aliases=tuple(aliases), default_tags=tags)


def _collect_catalogs(providers: Sequence[MarketDataProvider]) -> list[ProviderAsset]:
    by_identity: dict[tuple[AssetCategory, str], ProviderAsset] = {}
    errors: list[str] = []
    supported = 0
    seen_providers: set[int] = set()
    for provider in providers:
        if id(provider) in seen_providers:
            continue
        seen_providers.add(id(provider))
        catalog = getattr(provider, "catalog", None)
        if catalog is None:
            continue
        provider_catalog = getattr(type(provider), "catalog", None)
        if provider_catalog is MarketDataProvider.catalog:
            continue
        supported += 1
        try:
            assets = catalog()
        except ProviderError as exc:
            errors.append(f"{provider.name}: {exc}")
            logger.warning("Market catalog provider %s failed: %s", provider.name, exc)
            continue
        for asset in assets:
            key = (asset.category, asset.symbol)
            by_identity[key] = _merge_catalog_asset(
                by_identity.get(key),
                asset,
            )
    if supported and not by_identity and errors:
        raise ProviderError(f"All market catalog providers failed: {'; '.join(errors)}")
    return list(by_identity.values())


class PrioritizedMarketProvider(MarketDataProvider):
    """Try provider chains in order and stop before paid fallbacks when possible."""

    name = "prioritized"

    def __init__(
        self,
        search_providers: Sequence[MarketDataProvider],
        history_providers: Mapping[
            AssetCategory,
            Sequence[MarketDataProvider],
        ],
    ):
        self.search_providers = tuple(search_providers)
        self.history_providers = {
            category: tuple(providers) for category, providers in history_providers.items()
        }

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        errors: list[str] = []
        completed_without_error = False
        for position, provider in enumerate(self.search_providers):
            try:
                results = provider.search(query, limit, category)
                completed_without_error = True
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                if position + 1 < len(self.search_providers):
                    logger.info(
                        "Market search provider %s failed; trying %s: %s",
                        provider.name,
                        self.search_providers[position + 1].name,
                        exc,
                    )
                continue
            if results:
                return results[:limit]
            if position + 1 < len(self.search_providers):
                logger.info(
                    "Market search provider %s returned no results; trying %s",
                    provider.name,
                    self.search_providers[position + 1].name,
                )
        if completed_without_error:
            return []
        raise ProviderError(f"All market search providers failed: {'; '.join(errors)}")

    def catalog(self) -> list[ProviderAsset]:
        """Aggregate every full-list source; ordering only decides metadata precedence."""
        return _collect_catalogs(self.search_providers)

    def history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        providers = self.history_providers.get(asset.category, ())
        if not providers:
            raise ProviderError(
                f"No market history provider is configured for {asset.category.value}"
            )

        errors: list[str] = []
        completed_without_error = False
        for position, provider in enumerate(providers):
            try:
                bars = provider.history(asset, start_date, end_date)
                completed_without_error = True
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                if position + 1 < len(providers):
                    logger.info(
                        "Market history provider %s failed for %s; trying %s: %s",
                        provider.name,
                        asset.symbol,
                        providers[position + 1].name,
                        exc,
                    )
                continue
            if bars:
                return bars
            if position + 1 < len(providers):
                logger.info(
                    "Market history provider %s returned no rows for %s; trying %s",
                    provider.name,
                    asset.symbol,
                    providers[position + 1].name,
                )
        if completed_without_error:
            return []
        raise ProviderError(
            f"All market history providers failed for {asset.symbol}: {'; '.join(errors)}"
        )


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
            fallback_results = self.fallback.search(query, limit=limit, category=AssetCategory.ETF)
        except ProviderError:
            if primary_error is not None:
                raise primary_error
            return primary_results

        by_identity = {
            (asset.category, asset.symbol): asset for asset in primary_results
        }
        for asset in fallback_results:
            by_identity.setdefault((asset.category, asset.symbol), asset)
        return list(by_identity.values())[:limit]

    def catalog(self) -> list[ProviderAsset]:
        return _collect_catalogs((self.primary, self.fallback))

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
