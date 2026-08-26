from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MarketScopeType
from ..schemas import MarketScopeCreate, MarketScopeRead, MarketScopeUpdate
from ..services import MarketScopeService

router = APIRouter(prefix="/market-scopes", tags=["market-scopes"])
DB = Annotated[Session, Depends(get_db)]


def get_market_scope_service(db: DB) -> MarketScopeService:
    return MarketScopeService(db)


Service = Annotated[MarketScopeService, Depends(get_market_scope_service)]


@router.get("", response_model=list[MarketScopeRead])
def list_market_scopes(
    service: Service,
    scope_type: MarketScopeType | None = None,
    parent_code: str | None = Query(default=None, max_length=128),
):
    normalized_parent = parent_code.strip().upper() if parent_code else None
    return service.list(scope_type, normalized_parent)


@router.post("", response_model=MarketScopeRead, status_code=status.HTTP_201_CREATED)
def create_market_scope(data: MarketScopeCreate, service: Service):
    return service.create(data)


@router.get("/{code}", response_model=MarketScopeRead)
def get_market_scope(code: str, service: Service):
    return service.get(code)


@router.patch("/{code}", response_model=MarketScopeRead)
def update_market_scope(code: str, data: MarketScopeUpdate, service: Service):
    return service.update(code, data)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_market_scope(code: str, service: Service):
    service.delete(code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
