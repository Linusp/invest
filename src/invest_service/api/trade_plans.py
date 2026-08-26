from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AssetCategory, TradePlanAction, TradePlanStatus
from ..schemas import (
    TradePlanCreate,
    TradePlanRead,
    TradePlanReviewCreate,
    TradePlanReviewRead,
    TradePlanStatusEventRead,
    TradePlanStatusUpdate,
    TradePlanUpdate,
)
from ..services import TradePlanService

router = APIRouter(prefix="/trade-plans", tags=["trade-plans"])
DB = Annotated[Session, Depends(get_db)]


def get_service(db: DB, request: Request) -> TradePlanService:
    return TradePlanService(db)


Service = Annotated[TradePlanService, Depends(get_service)]


@router.get("", response_model=list[TradePlanRead])
def list_trade_plans(
    service: Service,
    portfolio_id: str | None = None,
    asset_symbol: str | None = None,
    asset_category: AssetCategory | None = None,
    status: TradePlanStatus | None = None,
    action: TradePlanAction | None = None,
    as_of: date | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return service.list(
        portfolio_id, asset_symbol, asset_category, status, as_of, limit, offset, action
    )


@router.post("", response_model=TradePlanRead, status_code=status.HTTP_201_CREATED)
def create_trade_plan(data: TradePlanCreate, service: Service):
    return service.create(data)


@router.get("/{plan_id}", response_model=TradePlanRead)
def get_trade_plan(plan_id: str, service: Service):
    return service.get(plan_id)


@router.patch("/{plan_id}", response_model=TradePlanRead)
def update_trade_plan(plan_id: str, data: TradePlanUpdate, service: Service):
    return service.update(plan_id, data)


@router.post("/{plan_id}/status", response_model=TradePlanRead)
def change_trade_plan_status(
    plan_id: str, data: TradePlanStatusUpdate, service: Service
):
    return service.change_status(plan_id, data)


@router.post(
    "/{plan_id}/review",
    response_model=TradePlanReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def review_trade_plan(plan_id: str, data: TradePlanReviewCreate, service: Service):
    return service.review(plan_id, data)


@router.get("/{plan_id}/review", response_model=TradePlanReviewRead | None)
def get_trade_plan_review(plan_id: str, service: Service):
    return service.get_review(plan_id)


@router.get("/{plan_id}/history", response_model=list[TradePlanStatusEventRead])
def get_trade_plan_history(plan_id: str, service: Service):
    return service.history(plan_id)
