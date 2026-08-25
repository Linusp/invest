from datetime import date
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .database import SessionLocal
from .models import AssetCategory, TradeType
from .providers import MarketDataProvider, make_market_provider
from .schemas import (
    AssetCreate,
    AssetTagCreate,
    AssetTagsUpdate,
    MarketUpdateTriggerRead,
    OpeningBalanceUpsert,
    OpeningPositionCreate,
    OpeningSnapshotRead,
    OpeningSnapshotUpsert,
    StrategyCreate,
    StrategyUpdate,
    TradeCreate,
)
from .services import MarketService, StrategyService
from .services.exchange_rate import ExchangeRateService


def _json(model: Any):
    if isinstance(model, list):
        return [_json(item) for item in model]
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


def build_mcp(
    session_factory: sessionmaker,
    provider: MarketDataProvider,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    reporting_currency: str | None = None,
) -> FastMCP:
    mcp = FastMCP(
        "invest",
        instructions=(
            "Query and update stock, ETF and index market data; create and inspect investment "
            "strategies; add trades and query derived positions."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts or ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
            allowed_origins=allowed_origins or [],
        ),
    )

    def strategies(session):
        return StrategyService(session, reporting_currency)

    @mcp.tool()
    def search_assets(query: str, category: str | None = None, limit: int = 15) -> list[dict]:
        """Fuzzy-search the periodically refreshed local asset index."""
        parsed_category = AssetCategory(category) if category else None
        with session_factory() as session:
            assets = MarketService(session, provider).search_assets(query, parsed_category, limit)
            return [_json_asset(asset) for asset in assets]

    @mcp.tool()
    def list_assets(
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_hidden: bool = False,
    ) -> list[dict]:
        """List registered favorite assets, optionally including hidden assets."""
        with session_factory() as session:
            assets = MarketService(session, provider).list_assets(
                AssetCategory(category) if category else None,
                limit,
                offset,
                include_hidden,
            )
            return [_json_asset(asset) for asset in assets]

    @mcp.tool()
    def get_asset(symbol: str, category: str | None = None) -> dict:
        """Get one asset; pass category when a symbol is ambiguous."""
        with session_factory() as session:
            asset = MarketService(session, provider).get_asset(
                symbol, AssetCategory(category) if category else None
            )
            return _json_asset(asset)

    @mcp.tool()
    def register_asset(
        symbol: str,
        name: str,
        category: str,
        provider_id: str | None = None,
        currency: str | None = None,
    ) -> dict:
        """Register a stock, ETF or index before recording trades or fetching market data."""
        with session_factory() as session:
            asset = MarketService(session, provider).register_asset(
                AssetCreate(
                    symbol=symbol,
                    name=name,
                    category=AssetCategory(category),
                    provider_id=provider_id,
                    currency=currency,
                )
            )
            from .celery_app import update_asset_market_data

            update_asset_market_data.delay(asset.symbol, asset.category.value)
            return _json_asset(asset)

    @mcp.tool()
    def refresh_asset_market_data(symbol: str, category: str | None = None) -> dict:
        """Queue an immediate background refresh for one registered asset."""
        with session_factory() as session:
            asset = MarketService(session, provider).get_asset(
                symbol, AssetCategory(category) if category else None
            )
            from .celery_app import update_asset_market_data

            update_asset_market_data.delay(asset.symbol, asset.category.value)
            return _json(
                MarketUpdateTriggerRead(
                    symbol=asset.symbol,
                    category=asset.category,
                )
            )

    @mcp.tool()
    def set_asset_favorite(symbol: str, is_favorite: bool, category: str | None = None) -> dict:
        """Add or remove an asset from favorites."""
        with session_factory() as session:
            asset = MarketService(session, provider).set_favorite(
                symbol, is_favorite, AssetCategory(category) if category else None
            )
            return _json_asset(asset)

    @mcp.tool()
    def list_asset_tags(symbol: str, category: str | None = None) -> list[dict]:
        """List an asset's tag memberships and per-tag favorite snapshots."""
        with session_factory() as session:
            rows = MarketService(session, provider).tag_memberships(
                symbol, AssetCategory(category) if category else None
            )
            return [_json(row) for row in rows]

    @mcp.tool()
    def update_asset_tags(
        symbol: str, tags: list[str], category: str | None = None
    ) -> dict:
        """Replace all tag memberships for an asset."""
        with session_factory() as session:
            asset = MarketService(session, provider).update_tags(
                symbol,
                AssetTagsUpdate(tags=tags).tags,
                AssetCategory(category) if category else None,
            )
            return _json_asset(asset)

    @mcp.tool()
    def add_asset_tag(symbol: str, name: str, category: str | None = None) -> dict:
        """Add an asset to a tag, creating the custom tag when needed."""
        with session_factory() as session:
            asset = MarketService(session, provider).add_tag(
                symbol,
                AssetTagCreate(name=name).name,
                AssetCategory(category) if category else None,
            )
            return _json_asset(asset)

    @mcp.tool()
    def remove_asset_tag(symbol: str, name: str, category: str | None = None) -> dict:
        """Remove an asset from one tag without changing other memberships."""
        with session_factory() as session:
            asset = MarketService(session, provider).remove_tag(
                symbol, name, AssetCategory(category) if category else None
            )
            return _json_asset(asset)

    @mcp.tool()
    def get_market_history(
        symbol: str,
        category: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Return persisted daily OHLCV market history in ascending date order."""
        with session_factory() as session:
            rows = MarketService(session, provider).history(
                symbol,
                date.fromisoformat(start_date) if start_date else None,
                date.fromisoformat(end_date) if end_date else None,
                limit,
                AssetCategory(category) if category else None,
            )
            from .schemas import MarketBarRead

            return [_json(MarketBarRead.model_validate(row)) for row in rows]

    @mcp.tool()
    def list_tags() -> list[dict]:
        """List visible system and custom favorite groups."""
        with session_factory() as session:
            return [_json(item) for item in MarketService(session, provider).list_tags()]

    @mcp.tool()
    def create_tag(name: str) -> dict:
        """Create or reveal an empty custom favorite group."""
        from .schemas import TagCreate

        with session_factory() as session:
            tag = MarketService(session, provider).create_tag(TagCreate(name=name))
            return _json(tag)

    @mcp.tool()
    def delete_tag(name: str) -> None:
        """Delete a custom group; system category groups cannot be deleted."""
        with session_factory() as session:
            MarketService(session, provider).delete_tag(name)

    @mcp.tool()
    def reorder_tags(names: list[str]) -> list[dict]:
        """Set the complete display order of favorite groups."""
        with session_factory() as session:
            return [_json(item) for item in MarketService(session, provider).reorder_tags(names)]

    @mcp.tool()
    def pin_tag(name: str, is_pinned: bool) -> list[dict]:
        """Pin or unpin a favorite group."""
        with session_factory() as session:
            groups = MarketService(session, provider).set_tag_pinned(name, is_pinned)
            return [_json(item) for item in groups]

    @mcp.tool()
    def list_tag_assets(name: str) -> list[dict]:
        """List summarized market data for assets in a favorite group."""
        with session_factory() as session:
            service = MarketService(session, provider)
            return [_json(item) for item in service.summarize_assets(service.assets_for_tag(name))]

    @mcp.tool()
    def get_exchange_rate(currency: str, on_date: str | None = None) -> dict:
        """Get the latest ECB exchange rate on or before a date."""
        with session_factory() as session:
            from .schemas import ExchangeRateRead

            rate = ExchangeRateService(session).latest(
                currency, date.fromisoformat(on_date) if on_date else None
            )
            return _json(ExchangeRateRead.model_validate(rate))

    @mcp.tool()
    def create_strategy(name: str, description: str | None = None) -> dict:
        """Create a persisted investment strategy."""
        with session_factory() as session:
            strategy = strategies(session).create(
                StrategyCreate(name=name, description=description)
            )
            return _json_strategy(strategy)

    @mcp.tool()
    def list_strategies() -> list[dict]:
        """List investment strategies."""
        with session_factory() as session:
            return [_json_strategy(item) for item in strategies(session).list()]

    @mcp.tool()
    def get_strategy(strategy_id: str) -> dict:
        """Get strategy metadata, summary, trades and current positions."""
        with session_factory() as session:
            return _json(strategies(session).detail(strategy_id))

    @mcp.tool()
    def update_strategy(
        strategy_id: str, name: str | None = None, description: str | None = None
    ) -> dict:
        """Modify a strategy name or description."""
        changes = {}
        if name is not None:
            changes["name"] = name
        if description is not None:
            changes["description"] = description
        with session_factory() as session:
            strategy = strategies(session).update(strategy_id, StrategyUpdate(**changes))
            return _json_strategy(strategy)

    @mcp.tool()
    def set_strategy_opening_snapshot(
        strategy_id: str,
        snapshot_date: str,
        balances: list[dict[str, Any]],
        positions: list[dict[str, Any]],
    ) -> dict:
        """Set current cash and holdings as the opening state before later transactions."""
        payload = OpeningSnapshotUpsert(
            snapshot_date=date.fromisoformat(snapshot_date),
            balances=[OpeningBalanceUpsert(**item) for item in balances],
            positions=[OpeningPositionCreate(**item) for item in positions],
        )
        with session_factory() as session:
            snapshot = strategies(session).set_opening_snapshot(strategy_id, payload)
            return _json(OpeningSnapshotRead.model_validate(snapshot))

    @mcp.tool()
    def get_strategy_opening_snapshot(strategy_id: str) -> dict | None:
        """Get a strategy's opening cash and holdings snapshot."""
        with session_factory() as session:
            snapshot = strategies(session).opening_snapshot(strategy_id)
            return _json(OpeningSnapshotRead.model_validate(snapshot)) if snapshot else None

    @mcp.tool()
    def delete_strategy_opening_snapshot(strategy_id: str) -> None:
        """Delete a strategy opening snapshot when it has no later transactions."""
        with session_factory() as session:
            strategies(session).delete_opening_snapshot(strategy_id)

    @mcp.tool()
    def get_strategy_trades(strategy_id: str) -> list[dict]:
        """List all strategy transactions in reverse chronological order."""
        from .schemas import TradeRead

        with session_factory() as session:
            return [
                _json(TradeRead.model_validate(item))
                for item in strategies(session).trades(strategy_id)
            ]

    @mcp.tool()
    def get_strategy_positions(strategy_id: str, as_of: str | None = None) -> list[dict]:
        """Calculate strategy holdings, cost basis and P/L from its transaction ledger."""
        with session_factory() as session:
            return [
                _json(item)
                for item in strategies(session).positions(
                    strategy_id, date.fromisoformat(as_of) if as_of else None
                )
            ]

    @mcp.tool()
    def add_strategy_trade(
        strategy_id: str,
        trade_type: str,
        trade_date: str,
        price: float,
        asset_symbol: str | None = None,
        asset_category: str | None = None,
        quantity: float = 0,
        fee: float = 0,
        note: str | None = None,
        idempotency_key: str | None = None,
        currency: str | None = None,
    ) -> dict:
        """Add a buy, sell, deposit or withdrawal transaction to a strategy."""
        from .schemas import TradeRead

        with session_factory() as session:
            trade = strategies(session).add_trade(
                strategy_id,
                TradeCreate(
                    type=TradeType(trade_type),
                    trade_date=date.fromisoformat(trade_date),
                    price=Decimal(str(price)),
                    asset_symbol=asset_symbol,
                    asset_category=(
                        AssetCategory(asset_category) if asset_category else None
                    ),
                    quantity=Decimal(str(quantity)),
                    fee=Decimal(str(fee)),
                    currency=currency,
                    note=note,
                    idempotency_key=idempotency_key,
                ),
            )
            return _json(TradeRead.model_validate(trade))

    return mcp


def _json_asset(asset) -> dict:
    from .schemas import AssetRead

    return _json(AssetRead.model_validate(asset))


def _json_strategy(strategy) -> dict:
    from .schemas import StrategyRead

    return _json(StrategyRead.model_validate(strategy))


settings = get_settings()
default_provider = make_market_provider(settings)
mcp = build_mcp(
    SessionLocal,
    default_provider,
    settings.mcp_allowed_hosts,
    settings.mcp_allowed_origins,
    settings.reporting_currency,
)


def run_stdio():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
