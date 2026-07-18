from fastapi import Request

from .database import get_db
from .providers import EcbExchangeRateProvider, MarketDataProvider


def get_provider(request: Request) -> MarketDataProvider:
    return request.app.state.market_provider


def get_exchange_rate_provider(request: Request) -> EcbExchangeRateProvider:
    return request.app.state.exchange_rate_provider


__all__ = ["get_db", "get_exchange_rate_provider", "get_provider"]
