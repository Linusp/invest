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
    AssetTagCreate,
    AssetTagMembershipRead,
    AssetTagsUpdate,
    MarketBarRead,
    MarketUpdateTriggerRead,
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
    assets = MarketService(db, provider).list_assets(category, limit, offset, include_hidden)
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
    q: str = Query(min_length=1),
    category: AssetCategory | None = None,
    limit: int = Query(default=15, ge=1, le=100),
):
    return MarketService(db, provider).search_assets(q, category, limit)


@router.put("/{category}/{symbol}/tags", response_model=AssetRead)
@router.put("/{symbol}/tags", response_model=AssetRead, deprecated=True)
def update_asset_tags(
    symbol: str,
    data: AssetTagsUpdate,
    db: DB,
    provider: Provider,
    category: AssetCategory | None = None,
):
    return MarketService(db, provider).update_tags(symbol, data.tags, category)


@router.get(
    "/{category}/{symbol}/tags",
    response_model=list[AssetTagMembershipRead],
)
@router.get(
    "/{symbol}/tags",
    response_model=list[AssetTagMembershipRead],
    deprecated=True,
)
def list_asset_tags(
    symbol: str,
    db: DB,
    provider: Provider,
    category: AssetCategory | None = None,
):
    return MarketService(db, provider).tag_memberships(symbol, category)


@router.post("/{category}/{symbol}/tags", response_model=AssetRead)
@router.post("/{symbol}/tags", response_model=AssetRead, deprecated=True)
def add_asset_tag(
    symbol: str,
    data: AssetTagCreate,
    db: DB,
    provider: Provider,
    category: AssetCategory | None = None,
):
    return MarketService(db, provider).add_tag(symbol, data.name, category)


@router.delete("/{category}/{symbol}/tags/{name}", response_model=AssetRead)
@router.delete("/{symbol}/tags/{name}", response_model=AssetRead, deprecated=True)
def remove_asset_tag(
    symbol: str,
    name: str,
    db: DB,
    provider: Provider,
    category: AssetCategory | None = None,
):
    return MarketService(db, provider).remove_tag(symbol, name, category)


@router.put("/{category}/{symbol}/favorite", response_model=AssetRead)
@router.put("/{symbol}/favorite", response_model=AssetRead, deprecated=True)
def update_asset_favorite(
    symbol: str,
    data: AssetFavoriteUpdate,
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
    category: AssetCategory | None = None,
):
    asset = MarketService(db, provider).set_favorite(
        symbol,
        data.is_favorite,
        category,
    )
    if asset.is_favorite:
        _queue_missing_history(request, response, db, [asset])
    return asset


@router.get("/{category}/{symbol}/history", response_model=list[MarketBarRead])
@router.get("/{symbol}/history", response_model=list[MarketBarRead], deprecated=True)
def get_history(
    symbol: str,
    db: DB,
    provider: Provider,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=1000, ge=1, le=10_000),
    category: AssetCategory | None = None,
):
    return MarketService(db, provider).history(
        symbol,
        start_date,
        end_date,
        limit,
        category,
    )


@router.post(
    "/{category}/{symbol}/refresh",
    response_model=MarketUpdateTriggerRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@router.post(
    "/{symbol}/refresh",
    response_model=MarketUpdateTriggerRead,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
)
def refresh_asset_market_data(
    symbol: str,
    db: DB,
    provider: Provider,
    request: Request,
    category: AssetCategory | None = None,
):
    asset = MarketService(db, provider).get_asset(symbol, category)
    request.app.state.enqueue_market_update(asset.category, asset.symbol)
    return MarketUpdateTriggerRead(
        symbol=asset.symbol,
        category=asset.category,
    )


# Keep the generic two-segment route after legacy routes such as
# /{symbol}/history. Starlette matches path templates in declaration order.
@router.get("/{category}/{symbol}", response_model=AssetRead)
@router.get("/{symbol}", response_model=AssetRead, deprecated=True)
def get_asset(
    symbol: str,
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
    category: AssetCategory | None = None,
):
    asset = MarketService(db, provider).get_asset(symbol, category)
    _queue_missing_history(request, response, db, [asset])
    return asset


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
    keys = [asset.key for asset in assets]
    if not keys:
        return
    populated = set(
        db.scalars(
            select(MarketBar.asset_key)
            .where(MarketBar.asset_key.in_(keys))
            .distinct()
        )
    )
    for asset in assets:
        if asset.key not in populated:
            request.app.state.enqueue_market_update(asset.category, asset.symbol)
