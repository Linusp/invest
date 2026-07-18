from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_exchange_rate_provider
from ..providers.exchange_rates import EcbExchangeRateProvider
from ..schemas import ExchangeRateRead, ExchangeRateSyncResult
from ..services.exchange_rate import ExchangeRateService

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])
DB = Annotated[Session, Depends(get_db)]
Provider = Annotated[EcbExchangeRateProvider, Depends(get_exchange_rate_provider)]


@router.post("/sync", response_model=ExchangeRateSyncResult)
def sync_exchange_rates(
    db: DB, provider: Provider, request: Request, full_history: bool | None = None
):
    return ExchangeRateService(
        db, provider, request.app.state.reporting_currency
    ).sync(full_history)


@router.get("/{currency}", response_model=ExchangeRateRead)
def get_exchange_rate(currency: str, db: DB, on_date: date | None = None):
    return ExchangeRateService(db).latest(currency, on_date)
