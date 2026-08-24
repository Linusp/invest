from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ExchangeRateRead
from ..services.exchange_rate import ExchangeRateService

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/{currency}", response_model=ExchangeRateRead)
def get_exchange_rate(currency: str, db: DB, on_date: date | None = None):
    return ExchangeRateService(db).latest(currency, on_date)
