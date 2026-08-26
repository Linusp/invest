from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .database import SessionLocal
from .models import (
    AnalysisSession,
    AssetCategory,
    CommentarySource,
    CommentarySubjectType,
    InformationType,
    MarketScopeType,
    TradePlanAction,
    TradePlanLogic,
    TradePlanStatus,
    TradeType,
)
from .providers import MarketDataProvider, make_market_provider
from .schemas import (
    AssetCreate,
    AssetTagCreate,
    AssetTagsUpdate,
    CommentaryCreate,
    CommentaryRevisionCreate,
    InformationAssetRef,
    InformationCreate,
    MarketScopeCreate,
    MarketScopeRead,
    MarketScopeUpdate,
    MarketUpdateTriggerRead,
    OpeningBalanceUpsert,
    OpeningPositionCreate,
    OpeningSnapshotRead,
    OpeningSnapshotUpsert,
    StrategyCreate,
    StrategyUpdate,
    TradeCreate,
    TradePlanCondition,
    TradePlanCreate,
    TradePlanStatusUpdate,
    TradePlanUpdate,
)
from .services import (
    CommentaryService,
    InformationService,
    MarketScopeService,
    MarketService,
    StrategyService,
    TradePlanService,
)
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

    def market_scopes(session):
        return MarketScopeService(session)

    def commentaries(session):
        return CommentaryService(session)

    def information(session):
        return InformationService(session)

    def trade_plans(session):
        return TradePlanService(session)

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
    def create_market_scope(
        code: str,
        name: str,
        scope_type: str,
        parent_code: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Create a market, sector, theme or commodity scope."""
        with session_factory() as session:
            scope = market_scopes(session).create(
                MarketScopeCreate(
                    code=code,
                    name=name,
                    scope_type=MarketScopeType(scope_type),
                    parent_code=parent_code,
                    description=description,
                )
            )
            return _json(MarketScopeRead.model_validate(scope))

    @mcp.tool()
    def list_market_scopes(
        scope_type: str | None = None, parent_code: str | None = None
    ) -> list[dict]:
        """List market scopes, optionally filtered by type or parent."""
        with session_factory() as session:
            scopes = market_scopes(session).list(
                MarketScopeType(scope_type) if scope_type else None,
                parent_code.strip().upper() if parent_code else None,
            )
            return [_json(MarketScopeRead.model_validate(item)) for item in scopes]

    @mcp.tool()
    def get_market_scope(code: str) -> dict:
        """Get one market scope by its stable code."""
        with session_factory() as session:
            scope = market_scopes(session).get(code)
            return _json(MarketScopeRead.model_validate(scope))

    @mcp.tool()
    def update_market_scope(
        code: str,
        name: str | None = None,
        scope_type: str | None = None,
        parent_code: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Update market scope metadata or hierarchy."""
        changes = {
            key: value
            for key, value in {
                "name": name,
                "scope_type": MarketScopeType(scope_type) if scope_type else None,
                "parent_code": parent_code,
                "description": description,
            }.items()
            if value is not None
        }
        with session_factory() as session:
            scope = market_scopes(session).update(
                code, MarketScopeUpdate(**changes)
            )
            return _json(MarketScopeRead.model_validate(scope))

    @mcp.tool()
    def delete_market_scope(code: str) -> None:
        """Delete an empty market scope."""
        with session_factory() as session:
            market_scopes(session).delete(code)

    @mcp.tool()
    def create_commentary(
        subject_type: str,
        session: str,
        trading_date: str,
        title: str,
        content: dict[str, Any] | str,
        market_scope_code: str | None = None,
        portfolio_id: str | None = None,
        asset_symbol: str | None = None,
        asset_category: str | None = None,
        summary: str | None = None,
        content_format: str = "structured",
        source: str = "human",
        source_ref: str | None = None,
        data_snapshot: dict[str, Any] | None = None,
        has_outlook: bool = False,
        has_risk: bool = False,
        has_trade_plan: bool = False,
        output_format: str = "markdown",
    ) -> dict:
        """Add an immutable market, portfolio or asset commentary."""
        payload = CommentaryCreate(
            subject_type=CommentarySubjectType(subject_type),
            market_scope_code=market_scope_code,
            portfolio_id=portfolio_id,
            asset_symbol=asset_symbol,
            asset_category=AssetCategory(asset_category) if asset_category else None,
            session=AnalysisSession(session),
            trading_date=date.fromisoformat(trading_date),
            title=title,
            summary=summary,
            content=content,
            content_format=content_format,
            source=CommentarySource(source),
            source_ref=source_ref,
            data_snapshot=data_snapshot,
            has_outlook=has_outlook,
            has_risk=has_risk,
            has_trade_plan=has_trade_plan,
        )
        with session_factory() as database_session:
            commentary = commentaries(database_session).create(payload)
            return _commentary_for_mcp(commentary, output_format)

    @mcp.tool()
    def list_commentaries(
        subject_type: str | None = None,
        market_scope_code: str | None = None,
        portfolio_id: str | None = None,
        asset_symbol: str | None = None,
        asset_category: str | None = None,
        session: str | None = None,
        source: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
        output_format: str = "markdown",
    ) -> list[dict]:
        """Query commentaries by subject, date, session, source or text."""
        with session_factory() as database_session:
            items = commentaries(database_session).list(
                subject_type=(
                    CommentarySubjectType(subject_type) if subject_type else None
                ),
                market_scope_code=market_scope_code,
                portfolio_id=portfolio_id,
                asset_symbol=asset_symbol,
                asset_category=(
                    AssetCategory(asset_category) if asset_category else None
                ),
                analysis_session=AnalysisSession(session) if session else None,
                source=CommentarySource(source) if source else None,
                start_date=date.fromisoformat(start_date) if start_date else None,
                end_date=date.fromisoformat(end_date) if end_date else None,
                query=query,
                limit=limit,
                offset=offset,
            )
            return [_commentary_for_mcp(item, output_format) for item in items]

    @mcp.tool()
    def get_commentary(
        commentary_id: str, output_format: str = "markdown"
    ) -> dict:
        """Get one commentary as Markdown or structured blocks."""
        with session_factory() as database_session:
            commentary = commentaries(database_session).get(commentary_id)
            return _commentary_for_mcp(commentary, output_format)

    @mcp.tool()
    def revise_commentary(
        commentary_id: str,
        content: dict[str, Any] | str,
        title: str | None = None,
        summary: str | None = None,
        content_format: str = "structured",
        source: str = "human",
        source_ref: str | None = None,
        data_snapshot: dict[str, Any] | None = None,
        has_outlook: bool | None = None,
        has_risk: bool | None = None,
        has_trade_plan: bool | None = None,
        output_format: str = "markdown",
    ) -> dict:
        """Create a revision while preserving the original commentary."""
        payload = CommentaryRevisionCreate(
            title=title,
            summary=summary,
            content=content,
            content_format=content_format,
            source=CommentarySource(source),
            source_ref=source_ref,
            data_snapshot=data_snapshot,
            has_outlook=has_outlook,
            has_risk=has_risk,
            has_trade_plan=has_trade_plan,
        )
        with session_factory() as database_session:
            commentary = commentaries(database_session).revise(
                commentary_id, payload
            )
            return _commentary_for_mcp(commentary, output_format)

    @mcp.tool()
    def submit_information(
        title: str,
        source_name: str,
        url: str,
        published_at: str,
        content: dict[str, Any] | str,
        information_type: str,
        summary: str | None = None,
        content_format: str = "structured",
        language: str = "zh-CN",
        search_context: str | None = None,
        content_fingerprint: str | None = None,
        importance: int = 3,
        confidence: float | None = None,
        market_scope_codes: list[str] | None = None,
        assets: list[dict[str, str]] | None = None,
        output_format: str = "markdown",
    ) -> dict:
        """Submit externally discovered information without fetching it in Invest."""
        payload = InformationCreate(
            title=title,
            source_name=source_name,
            url=url,
            published_at=datetime.fromisoformat(published_at),
            summary=summary,
            content=content,
            content_format=content_format,
            language=language,
            information_type=InformationType(information_type),
            search_context=search_context,
            content_fingerprint=content_fingerprint,
            importance=importance,
            confidence=Decimal(str(confidence)) if confidence is not None else None,
            market_scope_codes=market_scope_codes or [],
            assets=[InformationAssetRef(**item) for item in assets or []],
        )
        with session_factory() as database_session:
            item = information(database_session).submit(payload)
            return _information_for_mcp(item, output_format)

    @mcp.tool()
    def list_information(
        market_scope_code: str | None = None,
        asset_symbol: str | None = None,
        asset_category: str | None = None,
        published_from: str | None = None,
        published_to: str | None = None,
        source_name: str | None = None,
        information_type: str | None = None,
        query: str | None = None,
        min_importance: int | None = None,
        referenced: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        output_format: str = "markdown",
    ) -> list[dict]:
        """Filter submitted information by object, time, source, type or text."""
        with session_factory() as database_session:
            items = information(database_session).list(
                market_scope_code=market_scope_code,
                asset_symbol=asset_symbol,
                asset_category=(
                    AssetCategory(asset_category) if asset_category else None
                ),
                published_from=(
                    datetime.fromisoformat(published_from)
                    if published_from
                    else None
                ),
                published_to=(
                    datetime.fromisoformat(published_to) if published_to else None
                ),
                source_name=source_name,
                information_type=(
                    InformationType(information_type) if information_type else None
                ),
                query=query,
                min_importance=min_importance,
                referenced=referenced,
                limit=limit,
                offset=offset,
            )
            return [_information_for_mcp(item, output_format) for item in items]

    @mcp.tool()
    def get_information(
        information_id: str, output_format: str = "markdown"
    ) -> dict:
        """Get one submitted information record."""
        with session_factory() as database_session:
            item = information(database_session).get(information_id)
            return _information_for_mcp(item, output_format)

    @mcp.tool()
    def link_information_to_commentary(
        commentary_id: str, information_id: str
    ) -> None:
        """Use an information record as evidence for a commentary."""
        with session_factory() as database_session:
            information(database_session).link_commentary(
                commentary_id, information_id
            )

    @mcp.tool()
    def unlink_information_from_commentary(
        commentary_id: str, information_id: str
    ) -> None:
        """Remove an information reference from a commentary."""
        with session_factory() as database_session:
            information(database_session).unlink_commentary(
                commentary_id, information_id
            )

    @mcp.tool()
    def list_commentary_information(
        commentary_id: str, output_format: str = "markdown"
    ) -> list[dict]:
        """List information cited by a commentary."""
        with session_factory() as database_session:
            items = information(database_session).for_commentary(commentary_id)
            return [_information_for_mcp(item, output_format) for item in items]

    @mcp.tool()
    def create_trade_plan(
        portfolio_id: str,
        asset_symbol: str,
        asset_category: str,
        action: str,
        conditions: list[dict[str, Any]],
        quantity: float | None = None,
        amount: float | None = None,
        position_ratio: float | None = None,
        logic: str = "and",
        confirm_days: int = 1,
        valid_from: str | None = None,
        valid_until: str | None = None,
        reason: str | None = None,
        risk_note: str | None = None,
        source_commentary_id: str | None = None,
        status: str = "draft",
    ) -> dict:
        """Create a buy/sell plan; triggering never creates a trade automatically."""
        payload = TradePlanCreate(
            portfolio_id=portfolio_id,
            asset_symbol=asset_symbol,
            asset_category=AssetCategory(asset_category),
            action=TradePlanAction(action),
            logic=TradePlanLogic(logic),
            conditions=[TradePlanCondition(**item) for item in conditions],
            quantity=Decimal(str(quantity)) if quantity is not None else None,
            amount=Decimal(str(amount)) if amount is not None else None,
            position_ratio=(
                Decimal(str(position_ratio)) if position_ratio is not None else None
            ),
            confirm_days=confirm_days,
            valid_from=date.fromisoformat(valid_from) if valid_from else None,
            valid_until=date.fromisoformat(valid_until) if valid_until else None,
            reason=reason,
            risk_note=risk_note,
            source_commentary_id=source_commentary_id,
            status=TradePlanStatus(status),
        )
        with session_factory() as database_session:
            return _json(trade_plans(database_session).create(payload).model_dump(mode="json"))

    @mcp.tool()
    def list_trade_plans(
        portfolio_id: str | None = None,
        asset_symbol: str | None = None,
        asset_category: str | None = None,
        status: str | None = None,
        as_of: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List plans by portfolio, asset, status or effective date."""
        with session_factory() as database_session:
            items = trade_plans(database_session).list(
                portfolio_id,
                asset_symbol,
                AssetCategory(asset_category) if asset_category else None,
                TradePlanStatus(status) if status else None,
                date.fromisoformat(as_of) if as_of else None,
                limit,
                offset,
            )
            return [_json(item.model_dump(mode="json")) for item in items]

    @mcp.tool()
    def get_trade_plan(plan_id: str) -> dict:
        """Get one trade plan and its current lifecycle status."""
        with session_factory() as database_session:
            return _json(
                trade_plans(database_session).get(plan_id).model_dump(mode="json")
            )

    @mcp.tool()
    def update_trade_plan(
        plan_id: str,
        action: str | None = None,
        logic: str | None = None,
        conditions: list[dict[str, Any]] | None = None,
        quantity: float | None = None,
        amount: float | None = None,
        position_ratio: float | None = None,
        confirm_days: int | None = None,
        reason: str | None = None,
        risk_note: str | None = None,
    ) -> dict:
        """Modify a draft trade plan."""
        payload = TradePlanUpdate(
            action=TradePlanAction(action) if action else None,
            logic=TradePlanLogic(logic) if logic else None,
            conditions=[TradePlanCondition(**item) for item in conditions]
            if conditions is not None
            else None,
            quantity=Decimal(str(quantity)) if quantity is not None else None,
            amount=Decimal(str(amount)) if amount is not None else None,
            position_ratio=(
                Decimal(str(position_ratio)) if position_ratio is not None else None
            ),
            confirm_days=confirm_days,
            reason=reason,
            risk_note=risk_note,
        )
        with session_factory() as database_session:
            return _json(
                trade_plans(database_session).update(plan_id, payload).model_dump(mode="json")
            )

    @mcp.tool()
    def change_trade_plan_status(plan_id: str, status: str) -> dict:
        """Move a plan through its lifecycle; this never writes a trade."""
        with session_factory() as database_session:
            return _json(
                trade_plans(database_session)
                .change_status(plan_id, TradePlanStatusUpdate(status=TradePlanStatus(status)))
                .model_dump(mode="json")
            )

    @mcp.tool()
    def create_portfolio(
        name: str,
        description: str | None = None,
        initial_capital: float | None = None,
        investment_style: str | None = None,
        is_owned: bool = True,
        purpose: str | None = None,
        investment_direction: str | None = None,
        constraints: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Create a portfolio ledger with its investment profile."""
        with session_factory() as session:
            strategy = strategies(session).create(
                StrategyCreate(
                    name=name,
                    description=description,
                    initial_capital=(
                        Decimal(str(initial_capital))
                        if initial_capital is not None
                        else None
                    ),
                    investment_style=investment_style,
                    is_owned=is_owned,
                    purpose=purpose,
                    investment_direction=investment_direction,
                    constraints=constraints,
                    notes=notes,
                )
            )
            return _json_strategy(strategy)

    @mcp.tool()
    def list_portfolios() -> list[dict]:
        """List portfolio ledgers."""
        with session_factory() as session:
            return [_json_strategy(item) for item in strategies(session).list()]

    @mcp.tool()
    def get_portfolio(portfolio_id: str) -> dict:
        """Get portfolio metadata, summary, trades and current positions."""
        with session_factory() as session:
            return _json(strategies(session).detail(portfolio_id))

    @mcp.tool()
    def update_portfolio(
        portfolio_id: str,
        name: str | None = None,
        description: str | None = None,
        initial_capital: float | None = None,
        investment_style: str | None = None,
        is_owned: bool | None = None,
        purpose: str | None = None,
        investment_direction: str | None = None,
        constraints: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Modify portfolio metadata and investment profile fields."""
        changes = {}
        values = {
            "name": name,
            "description": description,
            "investment_style": investment_style,
            "is_owned": is_owned,
            "purpose": purpose,
            "investment_direction": investment_direction,
            "constraints": constraints,
            "notes": notes,
        }
        changes.update({key: value for key, value in values.items() if value is not None})
        if initial_capital is not None:
            changes["initial_capital"] = Decimal(str(initial_capital))
        with session_factory() as session:
            strategy = strategies(session).update(
                portfolio_id, StrategyUpdate(**changes)
            )
            return _json_strategy(strategy)

    @mcp.tool()
    def create_strategy(name: str, description: str | None = None) -> dict:
        """Compatibility alias for creating a portfolio ledger."""
        return create_portfolio(name=name, description=description)

    @mcp.tool()
    def list_strategies() -> list[dict]:
        """Compatibility alias for listing portfolio ledgers."""
        return list_portfolios()

    @mcp.tool()
    def get_strategy(strategy_id: str) -> dict:
        """Compatibility alias for getting a portfolio ledger."""
        return get_portfolio(strategy_id)

    @mcp.tool()
    def update_strategy(
        strategy_id: str, name: str | None = None, description: str | None = None
    ) -> dict:
        """Compatibility alias for modifying a portfolio ledger."""
        return update_portfolio(strategy_id, name=name, description=description)

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

    @mcp.tool()
    def set_portfolio_opening_snapshot(
        portfolio_id: str,
        snapshot_date: str,
        balances: list[dict[str, Any]],
        positions: list[dict[str, Any]],
    ) -> dict:
        """Set a portfolio's opening cash and holdings snapshot."""
        return set_strategy_opening_snapshot(
            portfolio_id, snapshot_date, balances, positions
        )

    @mcp.tool()
    def get_portfolio_opening_snapshot(portfolio_id: str) -> dict | None:
        """Get a portfolio's opening cash and holdings snapshot."""
        return get_strategy_opening_snapshot(portfolio_id)

    @mcp.tool()
    def delete_portfolio_opening_snapshot(portfolio_id: str) -> None:
        """Delete a portfolio opening snapshot when it has no later transactions."""
        return delete_strategy_opening_snapshot(portfolio_id)

    @mcp.tool()
    def get_portfolio_trades(portfolio_id: str) -> list[dict]:
        """List all portfolio transactions in reverse chronological order."""
        return get_strategy_trades(portfolio_id)

    @mcp.tool()
    def get_portfolio_positions(
        portfolio_id: str, as_of: str | None = None
    ) -> list[dict]:
        """Calculate portfolio holdings, cost basis and P/L."""
        return get_strategy_positions(portfolio_id, as_of)

    @mcp.tool()
    def add_portfolio_trade(
        portfolio_id: str,
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
        """Add a transaction to a portfolio ledger."""
        return add_strategy_trade(
            portfolio_id,
            trade_type,
            trade_date,
            price,
            asset_symbol,
            asset_category,
            quantity,
            fee,
            note,
            idempotency_key,
            currency,
        )

    return mcp


def _json_asset(asset) -> dict:
    from .schemas import AssetRead

    return _json(AssetRead.model_validate(asset))


def _json_strategy(strategy) -> dict:
    from .schemas import StrategyRead

    return _json(StrategyRead.model_validate(strategy))


def _commentary_for_mcp(commentary, output_format: str) -> dict:
    if output_format not in {"markdown", "structured"}:
        raise ValueError("output_format must be markdown or structured")
    payload = commentary.model_dump(mode="json")
    markdown = payload.pop("content_markdown")
    payload.pop("content_html")
    if output_format == "markdown":
        payload["content"] = markdown
    return payload


def _information_for_mcp(information, output_format: str) -> dict:
    if output_format not in {"markdown", "structured"}:
        raise ValueError("output_format must be markdown or structured")
    payload = information.model_dump(mode="json")
    markdown = payload.pop("content_markdown")
    payload.pop("content_html")
    if output_format == "markdown":
        payload["content"] = markdown
    return payload


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
