import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import sessionmaker

from .providers import MarketDataProvider
from .providers.exchange_rates import EcbExchangeRateProvider
from .services import ExchangeRateService, MarketService

logger = logging.getLogger(__name__)


def make_scheduler(
    session_factory: sessionmaker,
    provider: MarketDataProvider,
    interval_minutes: int,
    lookback_days: int,
    exchange_rate_provider: EcbExchangeRateProvider | None = None,
    exchange_rate_update_hour: int = 23,
    reporting_currency: str = "CNY",
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    def update_market_data():
        with session_factory() as session:
            result = MarketService(session, provider).sync_all(lookback_days)
            logger.info(
                "Automatic market update finished: %d succeeded, %d failed",
                len(result.succeeded),
                len(result.failed),
            )
            for symbol, error in result.failed.items():
                logger.warning("Automatic update failed for %s: %s", symbol, error)

    scheduler.add_job(
        update_market_data,
        "interval",
        minutes=interval_minutes,
        id="market-data-update",
        next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")),
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if exchange_rate_provider is not None:
        def update_exchange_rates():
            with session_factory() as session:
                result = ExchangeRateService(
                    session, exchange_rate_provider, reporting_currency
                ).sync()
                logger.info(
                    "Exchange-rate update finished: %d created, %d updated",
                    result.created,
                    result.updated,
                )

        scheduler.add_job(
            update_exchange_rates,
            "cron",
            hour=exchange_rate_update_hour,
            minute=30,
            id="exchange-rate-update",
            next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    return scheduler
