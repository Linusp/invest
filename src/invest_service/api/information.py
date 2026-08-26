from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AssetCategory, InformationType
from ..schemas import InformationCreate, InformationRead
from ..services import InformationService

router = APIRouter(prefix="/information", tags=["information"])
DB = Annotated[Session, Depends(get_db)]


def get_information_service(db: DB) -> InformationService:
    return InformationService(db)


Service = Annotated[InformationService, Depends(get_information_service)]


@router.get("", response_model=list[InformationRead])
def list_information(
    service: Service,
    market_scope_code: str | None = None,
    asset_symbol: str | None = None,
    asset_category: AssetCategory | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    source_name: str | None = None,
    information_type: InformationType | None = None,
    query: str | None = Query(default=None, max_length=255),
    min_importance: int | None = Query(default=None, ge=1, le=5),
    referenced: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return service.list(
        market_scope_code=market_scope_code,
        asset_symbol=asset_symbol,
        asset_category=asset_category,
        published_from=published_from,
        published_to=published_to,
        source_name=source_name,
        information_type=information_type,
        query=query,
        min_importance=min_importance,
        referenced=referenced,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=InformationRead, status_code=status.HTTP_201_CREATED)
def submit_information(data: InformationCreate, service: Service):
    return service.submit(data)


@router.get("/{information_id}", response_model=InformationRead)
def get_information(information_id: str, service: Service):
    return service.get(information_id)
