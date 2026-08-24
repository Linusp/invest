from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_provider
from ..models import Asset, AssetCategory, MarketBar
from ..providers import MarketDataProvider
from ..schemas import (
    AssetCreate,
    AssetFavoriteUpdate,
    AssetRead,
    AssetTagsUpdate,
    MarketBarRead,
)
from ..services import MarketService

router = APIRouter(prefix="/assets", tags=["assets"])
DB = Annotated[Session, Depends(get_db)]
Provider = Annotated[MarketDataProvider, Depends(get_provider)]


@router.get("", response_model=list[AssetRead])
def list_assets(
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
    category: AssetCategory | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    include_hidden: bool = False,
):
    assets = MarketService(db, provider).list_assets(
        category, limit, offset, include_hidden
    )
    _queue_missing_history(request, response, db, assets)
    return assets


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def register_asset(
    data: AssetCreate,
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
):
    asset = MarketService(db, provider).register_asset(data)
    _queue_missing_history(request, response, db, [asset])
    return asset


@router.get("/search", response_model=list[AssetRead])
def search_assets(
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
    q: str = Query(min_length=1),
    category: AssetCategory | None = None,
    limit: int = Query(default=15, ge=1, le=100),
    discover: bool = True,
):
    assets = MarketService(db, provider).search_assets(
        q,
        category,
        limit,
        discover and request.app.state.market_provider_discovery_enabled,
    )
    _queue_missing_history(request, response, db, assets)
    return assets


@router.get("/{symbol}", response_model=AssetRead)
def get_asset(
    symbol: str,
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
):
    asset = MarketService(db, provider).get_asset(symbol)
    _queue_missing_history(request, response, db, [asset])
    return asset


@router.put("/{symbol}/tags", response_model=AssetRead)
def update_asset_tags(
    symbol: str,
    data: AssetTagsUpdate,
    db: DB,
    provider: Provider,
):
    return MarketService(db, provider).update_tags(symbol, data.tags)


@router.put("/{symbol}/favorite", response_model=AssetRead)
def update_asset_favorite(
    symbol: str,
    data: AssetFavoriteUpdate,
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
):
    asset = MarketService(db, provider).set_favorite(symbol, data.is_favorite)
    if asset.is_favorite:
        _queue_missing_history(request, response, db, [asset])
    return asset


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


def _queue_missing_history(
    request: Request,
    response: Response,
    db: Session,
    assets: list[Asset],
) -> None:
    warning = request.app.state.market_provider_warning
    if warning:
        response.headers["X-Invest-Warning"] = (
            "tushare-fallback-missing"
            if request.app.state.market_provider_discovery_enabled
            else "tushare-token-missing"
        )
    if not request.app.state.market_provider_discovery_enabled:
        return
    symbols = [asset.symbol for asset in assets]
    if not symbols:
        return
    populated = set(
        db.scalars(
            select(MarketBar.asset_symbol)
            .where(MarketBar.asset_symbol.in_(symbols))
            .distinct()
        )
    )
    for symbol in symbols:
        if symbol not in populated:
            request.app.state.enqueue_market_update(symbol)
