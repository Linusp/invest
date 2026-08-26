from contextlib import asynccontextmanager
from threading import Lock
from time import monotonic

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from .api import (
    assets_router,
    commentaries_router,
    exchange_rates_router,
    information_router,
    market_scopes_router,
    portfolios_router,
    strategies_router,
    tags_router,
    trade_plans_router,
)
from .config import Settings, get_settings
from .database import Base, make_engine, make_session_factory
from .mcp_server import build_mcp
from .models import AssetCategory
from .providers import (
    EcbExchangeRateProvider,
    MarketDataProvider,
    ProviderError,
    make_market_provider,
)
from .schema_compat import migrate_legacy_data, prepare_legacy_schema
from .services import (
    AssetNotFound,
    CommentaryNotFound,
    ExchangeRateUnavailable,
    InformationNotFound,
    InvalidTrade,
    InvalidTradePlan,
    MarketScopeInUse,
    MarketScopeNotFound,
    MarketService,
    StrategyNotFound,
    TagNotFound,
    TradePlanNotFound,
)
from .web import router as web_router
from .web.routes import WEB_DIR


def create_app(
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    exchange_rate_provider: EcbExchangeRateProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    provider_was_injected = provider is not None
    provider = provider or make_market_provider(settings)
    exchange_rate_provider = exchange_rate_provider or EcbExchangeRateProvider()
    app_engine = make_engine(settings.database_url)
    session_factory = make_session_factory(app_engine)
    mcp = build_mcp(
        session_factory,
        provider,
        settings.mcp_allowed_hosts,
        settings.mcp_allowed_origins,
        settings.reporting_currency,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_legacy_schema(app_engine)
        tags_table_existed = inspect(app_engine).has_table("tags")
        Base.metadata.create_all(bind=app_engine)
        migrate_legacy_data(app_engine)
        with session_factory() as session:
            market_service = MarketService(session, provider)
            if not tags_table_existed:
                market_service.backfill_default_tags()
            market_service.ensure_default_asset()
            market_service.backfill_market_metadata()
            market_service.seed_search_index()
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                app_engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.market_provider = provider
    app.state.exchange_rate_provider = exchange_rate_provider
    app.state.session_factory = session_factory
    app.state.reporting_currency = settings.reporting_currency.upper()
    app.state.mcp = mcp
    tushare_token_missing = (
        not provider_was_injected
        and settings.market_provider == "tushare"
        and not settings.tushare_token
    )
    configured_provider_blocked = (
        tushare_token_missing and settings.market_provider_order == "configured_first"
    )
    app.state.market_provider_discovery_enabled = not configured_provider_blocked
    if not tushare_token_missing:
        app.state.market_provider_warning = None
    elif settings.market_provider_order == "free_first":
        app.state.market_provider_warning = (
            "未配置 Tushare Token，本地搜索仍可用；目录和行情更新将只使用免费源。"
        )
    else:
        app.state.market_provider_warning = (
            "未配置 Tushare Token，本地搜索仍可用；Tushare 目录补全和部分行情更新"
            "已暂停。请设置 INVEST_TUSHARE_TOKEN，或将 "
            "INVEST_MARKET_PROVIDER_ORDER 改为 free_first，然后重启 app、worker 服务。"
        )
    enqueued_at: dict[str, float] = {}
    enqueue_lock = Lock()

    def enqueue_market_update(category: AssetCategory, symbol: str) -> None:
        from .celery_app import update_asset_market_data

        identity = f"{category.value}:{symbol}"
        now = monotonic()
        with enqueue_lock:
            if now - enqueued_at.get(identity, 0) < 300:
                return
            update_asset_market_data.delay(symbol, category.value)
            enqueued_at[identity] = now

    app.state.enqueue_market_update = enqueue_market_update
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    @app.exception_handler(AssetNotFound)
    @app.exception_handler(CommentaryNotFound)
    @app.exception_handler(InformationNotFound)
    @app.exception_handler(StrategyNotFound)
    @app.exception_handler(TagNotFound)
    @app.exception_handler(TradePlanNotFound)
    @app.exception_handler(MarketScopeNotFound)
    async def not_found_handler(_, exc):
        return _error_response(404, str(exc))

    @app.exception_handler(ExchangeRateUnavailable)
    async def exchange_rate_unavailable_handler(_, exc):
        return _error_response(409, str(exc))

    @app.exception_handler(InvalidTrade)
    @app.exception_handler(MarketScopeInUse)
    @app.exception_handler(InvalidTradePlan)
    @app.exception_handler(IntegrityError)
    async def conflict_handler(_, exc):
        return _error_response(409, str(exc))

    @app.exception_handler(ValueError)
    async def value_error_handler(_, exc):
        return _error_response(422, str(exc))

    @app.exception_handler(ProviderError)
    async def provider_error_handler(_, exc):
        return _error_response(502, str(exc))

    app.include_router(assets_router, prefix="/api/v1")
    app.include_router(commentaries_router, prefix="/api/v1")
    app.include_router(exchange_rates_router, prefix="/api/v1")
    app.include_router(information_router, prefix="/api/v1")
    app.include_router(market_scopes_router, prefix="/api/v1")
    app.include_router(portfolios_router, prefix="/api/v1")
    app.include_router(strategies_router, prefix="/api/v1")
    app.include_router(tags_router, prefix="/api/v1")
    app.include_router(trade_plans_router, prefix="/api/v1")
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.mount("/mcp", mcp.streamable_http_app())
    return app


def _error_response(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


app = create_app()


def run():
    uvicorn.run("invest_service.main:app", host="0.0.0.0", port=8000)
