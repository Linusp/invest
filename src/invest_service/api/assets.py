from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_provider
from ..models import AssetCategory
from ..providers import MarketDataProvider
from ..schemas import (
    AssetCreate,
    AssetRead,
    BulkSyncResult,
    MarketBarRead,
    MarketSyncResult,
)
from ..services import MarketService

router = APIRouter(prefix="/assets", tags=["assets"])
DB = Annotated[Session, Depends(get_db)]
Provider = Annotated[MarketDataProvider, Depends(get_provider)]


@router.get("", response_model=list[AssetRead])
def list_assets(
    db: DB,
    provider: Provider,
    category: AssetCategory | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return MarketService(db, provider).list_assets(category, limit, offset)


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def register_asset(data: AssetCreate, db: DB, provider: Provider):
    return MarketService(db, provider).register_asset(data)


@router.get("/search", response_model=list[AssetRead])
def search_assets(
    db: DB,
    provider: Provider,
    q: str = Query(min_length=1),
    category: AssetCategory | None = None,
    limit: int = Query(default=15, ge=1, le=100),
    discover: bool = True,
):
    return MarketService(db, provider).search_assets(q, category, limit, discover)


@router.post("/sync", response_model=BulkSyncResult)
def sync_all(db: DB, provider: Provider, lookback_days: int = Query(default=10, ge=1, le=3650)):
    return MarketService(db, provider).sync_all(lookback_days)


@router.get("/{symbol}", response_model=AssetRead)
def get_asset(symbol: str, db: DB, provider: Provider):
    return MarketService(db, provider).get_asset(symbol)


@router.get("/{symbol}/history", response_model=list[MarketBarRead])
def get_history(
    symbol: str,
    db: DB,
    provider: Provider,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=1000, ge=1, le=10_000),
):
    return MarketService(db, provider).history(symbol, start_date, end_date, limit)


@router.post("/{symbol}/sync", response_model=MarketSyncResult)
def sync_asset(
    symbol: str,
    db: DB,
    provider: Provider,
    start_date: date | None = None,
    end_date: date | None = None,
    overwrite: bool = False,
    lookback_days: int = Query(default=10, ge=1, le=3650),
):
    return MarketService(db, provider).sync_asset(
        symbol, start_date, end_date, overwrite, lookback_days
    )
