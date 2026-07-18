from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .api import assets_router, exchange_rates_router, strategies_router
from .config import Settings, get_settings
from .database import Base, SessionLocal, engine
from .mcp_server import build_mcp
from .providers import (
    EcbExchangeRateProvider,
    MarketDataProvider,
    ProviderError,
    make_market_provider,
)
from .scheduler import make_scheduler
from .schema_compat import migrate_legacy_data, prepare_legacy_schema
from .services import (
    AssetNotFound,
    ExchangeRateUnavailable,
    InvalidTrade,
    StrategyNotFound,
)
from .web import router as web_router
from .web.routes import WEB_DIR


def create_app(
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    exchange_rate_provider: EcbExchangeRateProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    provider = provider or make_market_provider(settings)
    exchange_rate_provider = exchange_rate_provider or EcbExchangeRateProvider()
    mcp = build_mcp(
        SessionLocal,
        provider,
        settings.mcp_allowed_hosts,
        settings.mcp_allowed_origins,
        settings.reporting_currency,
    )
    scheduler = make_scheduler(
        SessionLocal,
        provider,
        settings.auto_update_interval_minutes,
        settings.auto_update_lookback_days,
        exchange_rate_provider,
        settings.exchange_rate_update_hour,
        settings.reporting_currency,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_legacy_schema(engine)
        Base.metadata.create_all(bind=engine)
        migrate_legacy_data(engine)
        async with mcp.session_manager.run():
            if settings.auto_update_enabled:
                scheduler.start()
            try:
                yield
            finally:
                if scheduler.running:
                    scheduler.shutdown(wait=False)

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.market_provider = provider
    app.state.exchange_rate_provider = exchange_rate_provider
    app.state.reporting_currency = settings.reporting_currency.upper()
    app.state.mcp = mcp
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
    @app.exception_handler(StrategyNotFound)
    async def not_found_handler(_, exc):
        return _error_response(404, str(exc))

    @app.exception_handler(ExchangeRateUnavailable)
    async def exchange_rate_unavailable_handler(_, exc):
        return _error_response(409, str(exc))

    @app.exception_handler(InvalidTrade)
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
    app.include_router(exchange_rates_router, prefix="/api/v1")
    app.include_router(strategies_router, prefix="/api/v1")
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
