from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AnalysisSession,
    AssetCategory,
    CommentarySource,
    CommentarySubjectType,
)
from ..schemas import (
    CommentaryCreate,
    CommentaryRead,
    CommentaryRevisionCreate,
    InformationRead,
)
from ..services import CommentaryService, InformationService

router = APIRouter(prefix="/commentaries", tags=["commentaries"])
DB = Annotated[Session, Depends(get_db)]


def get_commentary_service(db: DB) -> CommentaryService:
    return CommentaryService(db)


Service = Annotated[CommentaryService, Depends(get_commentary_service)]


def get_information_service(db: DB) -> InformationService:
    return InformationService(db)


Information = Annotated[InformationService, Depends(get_information_service)]


@router.get("", response_model=list[CommentaryRead])
def list_commentaries(
    service: Service,
    subject_type: CommentarySubjectType | None = None,
    market_scope_code: str | None = None,
    portfolio_id: str | None = None,
    asset_symbol: str | None = None,
    asset_category: AssetCategory | None = None,
    session: AnalysisSession | None = None,
    source: CommentarySource | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    query: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return service.list(
        subject_type=subject_type,
        market_scope_code=market_scope_code,
        portfolio_id=portfolio_id,
        asset_symbol=asset_symbol,
        asset_category=asset_category,
        analysis_session=session,
        source=source,
        start_date=start_date,
        end_date=end_date,
        query=query,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=CommentaryRead, status_code=status.HTTP_201_CREATED)
def create_commentary(data: CommentaryCreate, service: Service):
    return service.create(data)


@router.get("/{commentary_id}", response_model=CommentaryRead)
def get_commentary(commentary_id: str, service: Service):
    return service.get(commentary_id)


@router.post(
    "/{commentary_id}/revisions",
    response_model=CommentaryRead,
    status_code=status.HTTP_201_CREATED,
)
def revise_commentary(
    commentary_id: str, data: CommentaryRevisionCreate, service: Service
):
    return service.revise(commentary_id, data)


@router.get("/{commentary_id}/information", response_model=list[InformationRead])
def list_commentary_information(commentary_id: str, information: Information):
    return information.for_commentary(commentary_id)


@router.post(
    "/{commentary_id}/information/{information_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def link_commentary_information(
    commentary_id: str, information_id: str, information: Information
):
    information.link_commentary(commentary_id, information_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{commentary_id}/information/{information_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlink_commentary_information(
    commentary_id: str, information_id: str, information: Information
):
    information.unlink_commentary(commentary_id, information_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
