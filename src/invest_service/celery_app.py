import logging
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init
from sqlalchemy.orm import sessionmaker

from .config import Settings, get_settings
from .database import Base, SessionLocal, engine
from .models import AssetCategory, MarketBar, TradePlan, TradePlanStatus
from .providers import (
    EcbExchangeRateProvider,
    MarketDataProvider,
    ProviderError,
    make_market_provider,
)
from .providers.ifind_mcp import IfindMcpClient
from .providers.sector_flow import EastMoneySectorFlow
from .schema_compat import migrate_legacy_data, prepare_legacy_schema
from .services import ExchangeRateService, MarketService
from .services.provider_gate import ProviderGateService
from .services.provider_probe import probe_provider
from .services.quote_snapshot import QuoteSnapshotService
from .services.sector_capital_flow import SectorCapitalFlowService
from .services.trade_plan_evaluator import evaluate_plan

logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")

MARKET_UPDATE_SOFT_TIME_LIMIT = 15 * 60
MARKET_UPDATE_TIME_LIMIT = 16 * 60
ASSET_UPDATE_SOFT_TIME_LIMIT = 3 * 60
ASSET_UPDATE_TIME_LIMIT = 4 * 60
EXCHANGE_RATE_SOFT_TIME_LIMIT = 2 * 60
EXCHANGE_RATE_TIME_LIMIT = 3 * 60
SEARCH_INDEX_SOFT_TIME_LIMIT = 25 * 60
SEARCH_INDEX_TIME_LIMIT = 30 * 60
SECTOR_FLOW_SOFT_TIME_LIMIT = 15 * 60
SECTOR_FLOW_TIME_LIMIT = 20 * 60
QUOTE_SNAPSHOT_SOFT_TIME_LIMIT = 120
QUOTE_SNAPSHOT_TIME_LIMIT = 180


def build_beat_schedule(settings: Settings) -> dict[str, dict[str, Any]]:
    if not settings.auto_update_enabled:
        return {}
    interval_seconds = settings.auto_update_interval_minutes * 60
    schedule: dict[str, dict[str, Any]] = {
        "update-market-data": {
            "task": "invest.update_market_data",
            "schedule": interval_seconds,
            "options": {"expires": interval_seconds},
        },
        "update-exchange-rates": {
            "task": "invest.update_exchange_rates",
            "schedule": crontab(
                hour=settings.exchange_rate_update_hour,
                minute=30,
            ),
            "options": {"expires": 6 * 60 * 60},
        },
        "update-search-index": {
            "task": "invest.update_search_index",
            "schedule": crontab(
                hour=settings.search_index_update_hour,
                minute=10,
            ),
            "options": {"expires": 12 * 60 * 60},
        },
        "evaluate-trade-plans": {
            "task": "invest.evaluate_trade_plans",
            "schedule": interval_seconds,
            "options": {"expires": interval_seconds},
        },
    }
    if settings.sector_flow_enabled:
        # EOD backfill for the daily sector capital-flow snapshot.
        schedule["update-sector-capital-flow"] = {
            "task": "invest.update_sector_capital_flow",
            "schedule": crontab(
                hour=settings.sector_flow_update_hour,
                minute=settings.sector_flow_update_minute,
            ),
            "options": {"expires": 6 * 60 * 60},
        }
        # Optional intraday refresh of the current trading day's snapshot.
        if settings.sector_flow_update_minutes > 0:
            refresh_seconds = settings.sector_flow_update_minutes * 60
            schedule["update-sector-capital-flow-intraday"] = {
                "task": "invest.update_sector_capital_flow",
                "schedule": refresh_seconds,
                "options": {"expires": refresh_seconds},
            }
        # 1-minute board flow series used by the animation.
        if settings.sector_flow_intraday_minutes > 0:
            flow_seconds = settings.sector_flow_intraday_minutes * 60
            schedule["update-sector-flow-points"] = {
                "task": "invest.update_sector_flow_points",
                "schedule": flow_seconds,
                "options": {"expires": flow_seconds},
            }
    # 每天探测一次被余额熔断的 provider，恢复了就自动放行。
    schedule["recover-provider-states"] = {
        "task": "invest.recover_provider_states",
        "schedule": crontab(hour=9, minute=10),
        "options": {"expires": 6 * 60 * 60},
    }
    if settings.quote_snapshot_enabled:
        snapshot_seconds = settings.quote_snapshot_interval_minutes * 60
        schedule["update-quote-snapshots"] = {
            "task": "invest.update_quote_snapshots",
            "schedule": snapshot_seconds,
            "options": {"expires": snapshot_seconds},
        }
    return schedule


settings = get_settings()
celery_app = Celery("invest_service", broker=settings.celery_broker_url)
celery_app.conf.update(
    beat_schedule=build_beat_schedule(settings),
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    task_acks_late=True,
    task_ignore_result=True,
    timezone="Asia/Shanghai",
    worker_prefetch_multiplier=1,
)


@worker_init.connect
def initialize_worker_database(**_: Any) -> None:
    """Make standalone workers safe to start before the API process."""
    prepare_legacy_schema(engine)
    Base.metadata.create_all(bind=engine)
    migrate_legacy_data(engine)
    engine.dispose()


def run_market_update(
    session_factory: sessionmaker,
    provider: MarketDataProvider,
    lookback_days: int,
) -> dict[str, Any]:
    with session_factory() as session:
        result = MarketService(session, provider).sync_all(lookback_days)
    logger.info(
        "Market update finished: %d succeeded, %d failed",
        len(result.succeeded),
        len(result.failed),
    )
    for symbol, error in result.failed.items():
        logger.warning("Market update failed for %s: %s", symbol, error)
    return {
        "succeeded": [item.model_dump(mode="json") for item in result.succeeded],
        "failed": result.failed,
    }


def run_asset_update(
    session_factory: sessionmaker,
    provider: MarketDataProvider,
    symbol: str,
    lookback_days: int,
    category: AssetCategory | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        result = MarketService(session, provider).sync_asset(
            symbol,
            lookback_days=lookback_days,
            category=category,
        )
    logger.info(
        "Market update for %s finished: %d created, %d updated",
        symbol,
        result.created,
        result.updated,
    )
    return result.model_dump(mode="json")


def run_exchange_rate_update(
    session_factory: sessionmaker,
    provider: EcbExchangeRateProvider,
    reporting_currency: str,
) -> dict[str, Any]:
    with session_factory() as session:
        result = ExchangeRateService(session, provider, reporting_currency).sync()
    logger.info(
        "Exchange-rate update finished: %d created, %d updated",
        result.created,
        result.updated,
    )
    return result.model_dump(mode="json")


def run_search_index_update(
    session_factory: sessionmaker,
    provider: MarketDataProvider,
) -> dict[str, int]:
    with session_factory() as session:
        result = MarketService(session, provider).sync_search_index()
    logger.info(
        "Search-index update finished: %d discovered, %d indexed",
        result.discovered,
        result.indexed,
    )
    return {
        "discovered": result.discovered,
        "indexed": result.indexed,
    }


def run_trade_plan_evaluation(
    session_factory: sessionmaker, as_of=None
) -> dict[str, int]:
    evaluation_date = as_of or date.today()
    triggered = 0
    scanned = 0
    with session_factory() as session:
        plans = list(
            session.query(TradePlan)
            .filter(TradePlan.status == TradePlanStatus.ACTIVE)
            .all()
        )
        for plan in plans:
            if plan.valid_from and evaluation_date < plan.valid_from:
                continue
            if plan.valid_until and evaluation_date > plan.valid_until:
                plan.status = TradePlanStatus.EXPIRED
                continue
            bars = list(
                session.query(MarketBar)
                .filter(
                    MarketBar.asset_key == plan.asset_key,
                    MarketBar.trade_date <= evaluation_date,
                )
                .order_by(MarketBar.trade_date.asc())
                .all()
            )
            scanned += 1
            result = evaluate_plan(
                {
                    "logic": plan.logic.value,
                    "confirm_days": plan.confirm_days,
                    "conditions": plan.conditions,
                },
                [
                    {
                        "trade_date": bar.trade_date,
                        "close": bar.close,
                        "change_percent": bar.change_percent,
                        "volume": bar.volume,
                        "amount": bar.amount,
                    }
                    for bar in bars
                ],
                evaluation_date,
            )
            if result.matched:
                plan.status = TradePlanStatus.TRIGGERED
                plan.triggered_at = datetime.now(timezone.utc)
                triggered += 1
        session.commit()
    return {"scanned": scanned, "triggered": triggered}


@celery_app.task(
    name="invest.update_market_data",
    soft_time_limit=MARKET_UPDATE_SOFT_TIME_LIMIT,
    time_limit=MARKET_UPDATE_TIME_LIMIT,
)
def update_market_data() -> dict[str, Any]:
    current_settings = get_settings()
    return run_market_update(
        SessionLocal,
        make_market_provider(current_settings, SessionLocal),
        current_settings.auto_update_lookback_days,
    )


@celery_app.task(
    name="invest.update_asset_market_data",
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=ASSET_UPDATE_SOFT_TIME_LIMIT,
    time_limit=ASSET_UPDATE_TIME_LIMIT,
)
def update_asset_market_data(
    symbol: str,
    category: str | None = None,
) -> dict[str, Any]:
    current_settings = get_settings()
    return run_asset_update(
        SessionLocal,
        make_market_provider(current_settings, SessionLocal),
        symbol,
        current_settings.auto_update_lookback_days,
        AssetCategory(category) if category else None,
    )


@celery_app.task(
    name="invest.update_exchange_rates",
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=EXCHANGE_RATE_SOFT_TIME_LIMIT,
    time_limit=EXCHANGE_RATE_TIME_LIMIT,
)
def update_exchange_rates() -> dict[str, Any]:
    current_settings = get_settings()
    return run_exchange_rate_update(
        SessionLocal,
        EcbExchangeRateProvider(),
        current_settings.reporting_currency,
    )


@celery_app.task(
    name="invest.update_search_index",
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=SEARCH_INDEX_SOFT_TIME_LIMIT,
    time_limit=SEARCH_INDEX_TIME_LIMIT,
)
def update_search_index() -> dict[str, int]:
    current_settings = get_settings()
    return run_search_index_update(
        SessionLocal,
        make_market_provider(current_settings, SessionLocal),
    )


@celery_app.task(name="invest.evaluate_trade_plans")
def evaluate_trade_plans() -> dict[str, int]:
    return run_trade_plan_evaluation(SessionLocal)


def run_sector_capital_flow_update(
    session_factory: sessionmaker,
    settings: Settings,
) -> dict[str, Any]:
    provider = EastMoneySectorFlow()
    with session_factory() as session:
        service = SectorCapitalFlowService(session)
        result = service.refresh_daily(
            lookback_days=settings.sector_flow_lookback_days,
            provider=provider,
            sync_scopes=settings.sector_flow_sync_scopes_enabled,
            scopes_top=settings.sector_flow_sync_scopes_top,
            scopes_parent=settings.sector_flow_sync_scopes_parent,
        )
        # 收盘后再抓一次分钟序列，保证每个交易日都留下完整的当日回放。
        if settings.sector_flow_intraday_minutes > 0:
            result["intraday"] = service.refresh_intraday(
                provider=provider, top=settings.sector_flow_intraday_top
            )
    logger.info(
        "[sector-flow] refresh finished: %s",
        result,
    )
    return result


@celery_app.task(
    name="invest.update_sector_capital_flow",
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
    soft_time_limit=SECTOR_FLOW_SOFT_TIME_LIMIT,
    time_limit=SECTOR_FLOW_TIME_LIMIT,
)
def update_sector_capital_flow() -> dict[str, Any]:
    current_settings = get_settings()
    if not current_settings.sector_flow_enabled:
        return {"disabled": True}
    return run_sector_capital_flow_update(SessionLocal, current_settings)


def run_sector_flow_points_update(
    session_factory: sessionmaker,
    settings: Settings,
) -> dict[str, Any]:
    with session_factory() as session:
        result = SectorCapitalFlowService(session).refresh_intraday(
            top=settings.sector_flow_intraday_top
        )
    logger.info("[sector-flow] intraday points: %s", result)
    return result


@celery_app.task(
    name="invest.update_sector_flow_points",
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
    soft_time_limit=120,
    time_limit=180,
)
def update_sector_flow_points() -> dict[str, Any]:
    current_settings = get_settings()
    if not current_settings.sector_flow_enabled:
        return {"disabled": True}
    if current_settings.sector_flow_intraday_minutes <= 0:
        return {"disabled": "intraday disabled"}
    if not _in_trading_window():
        return {"skipped": "outside trading hours"}
    return run_sector_flow_points_update(SessionLocal, current_settings)


def _in_trading_window(moment: datetime | None = None) -> bool:
    """A 股连续竞价时段（含集合竞价与收盘后的最后一次快照）。"""
    current = (moment or datetime.now(tz=SHANGHAI)).astimezone(SHANGHAI)
    if current.weekday() >= 5:
        return False
    return (9, 15) <= (current.hour, current.minute) <= (15, 10)


def run_quote_snapshot_update(
    session_factory: sessionmaker,
    settings: Settings,
) -> dict[str, Any]:
    key = settings.ifind_key()
    if not key:
        raise ProviderError("iFinD MCP key is not configured")
    client = IfindMcpClient(key)
    try:
        with session_factory() as session:
            result = QuoteSnapshotService(session).refresh(
                client, favorites_only=settings.quote_snapshot_favorites_only
            )
    finally:
        client.client.close()
    logger.info("[quote-snapshot] refresh finished: %s", result)
    return result


@celery_app.task(
    name="invest.update_quote_snapshots",
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
    soft_time_limit=QUOTE_SNAPSHOT_SOFT_TIME_LIMIT,
    time_limit=QUOTE_SNAPSHOT_TIME_LIMIT,
)
def update_quote_snapshots() -> dict[str, Any]:
    current_settings = get_settings()
    if not current_settings.quote_snapshot_enabled:
        return {"disabled": True}
    if not _in_trading_window():
        return {"skipped": "outside trading hours"}
    return run_quote_snapshot_update(SessionLocal, current_settings)


@celery_app.task(name="invest.recover_provider_states")
def recover_provider_states() -> dict[str, Any]:
    """对 credit 状态的 provider 做一次轻量探测，成功则解除熔断。"""
    current_settings = get_settings()
    recovered: list[str] = []
    still_down: list[str] = []
    with SessionLocal() as session:
        gate = ProviderGateService(session)
        for row in gate.status():
            if row["status"] != "credit":
                continue
            provider = row["provider"]
            ok, detail = probe_provider(provider, current_settings)
            if ok:
                gate.reset(provider)
                recovered.append(provider)
            else:
                still_down.append(provider)
                logger.info("[provider-gate] %s still down: %s", provider, detail[:120])
    return {"recovered": recovered, "still_down": still_down}


def run_worker() -> None:
    celery_app.worker_main(["worker", "--loglevel=INFO"])


def run_beat() -> None:
    celery_app.start(["beat", "--loglevel=INFO"])
