from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_provider
from ..providers import MarketDataProvider
from ..schemas import (
    AssetMarketSummary,
    TagGroupRead,
    TagOrderUpdate,
    TagPinUpdate,
)
from ..services import MarketService
from .assets import _queue_missing_history

router = APIRouter(prefix="/tags", tags=["tags"])
DB = Annotated[Session, Depends(get_db)]
Provider = Annotated[MarketDataProvider, Depends(get_provider)]


@router.get("", response_model=list[TagGroupRead])
def list_tags(db: DB, provider: Provider):
    return MarketService(db, provider).list_tags()


@router.put("/order", response_model=list[TagGroupRead])
def reorder_tags(data: TagOrderUpdate, db: DB, provider: Provider):
    return MarketService(db, provider).reorder_tags(data.names)


@router.put("/{name}/pin", response_model=list[TagGroupRead])
def pin_tag(name: str, data: TagPinUpdate, db: DB, provider: Provider):
    return MarketService(db, provider).set_tag_pinned(name, data.is_pinned)


@router.get("/{name}/assets", response_model=list[AssetMarketSummary])
def list_tag_assets(
    name: str,
    db: DB,
    provider: Provider,
    request: Request,
    response: Response,
):
    service = MarketService(db, provider)
    tagged_assets = service.assets_for_tag(name)
    _queue_missing_history(
        request,
        response,
        db,
        [asset for asset, _, _ in tagged_assets],
    )
    return service.summarize_assets(tagged_assets)
