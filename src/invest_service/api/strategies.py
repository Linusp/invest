from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    OpeningSnapshotRead,
    OpeningSnapshotUpsert,
    PositionRead,
    StrategyCreate,
    StrategyDetail,
    StrategyRead,
    StrategyUpdate,
    TradeCreate,
    TradeRead,
)
from ..services import StrategyService

router = APIRouter(prefix="/strategies", tags=["strategies"])
DB = Annotated[Session, Depends(get_db)]


def get_strategy_service(db: DB, request: Request) -> StrategyService:
    return StrategyService(db, request.app.state.reporting_currency)


Service = Annotated[StrategyService, Depends(get_strategy_service)]


@router.get("", response_model=list[StrategyRead])
def list_strategies(
    service: Service,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return service.list(limit, offset)


@router.post("", response_model=StrategyRead, status_code=status.HTTP_201_CREATED)
def create_strategy(data: StrategyCreate, service: Service):
    return service.create(data)


@router.get("/{strategy_id}", response_model=StrategyDetail)
def get_strategy(strategy_id: str, service: Service):
    return service.detail(strategy_id)


@router.patch("/{strategy_id}", response_model=StrategyRead)
def update_strategy(strategy_id: str, data: StrategyUpdate, service: Service):
    return service.update(strategy_id, data)


@router.get(
    "/{strategy_id}/opening-snapshot",
    response_model=OpeningSnapshotRead | None,
)
def get_opening_snapshot(strategy_id: str, service: Service):
    return service.opening_snapshot(strategy_id)


@router.put(
    "/{strategy_id}/opening-snapshot",
    response_model=OpeningSnapshotRead,
)
def set_opening_snapshot(
    strategy_id: str, data: OpeningSnapshotUpsert, service: Service
):
    return service.set_opening_snapshot(strategy_id, data)


@router.delete(
    "/{strategy_id}/opening-snapshot",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_opening_snapshot(strategy_id: str, service: Service):
    service.delete_opening_snapshot(strategy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{strategy_id}/trades", response_model=list[TradeRead])
def list_trades(strategy_id: str, service: Service):
    return service.trades(strategy_id)


@router.post("/{strategy_id}/trades", response_model=TradeRead, status_code=status.HTTP_201_CREATED)
def add_trade(strategy_id: str, data: TradeCreate, service: Service):
    return service.add_trade(strategy_id, data)


@router.get("/{strategy_id}/positions", response_model=list[PositionRead])
def list_positions(strategy_id: str, service: Service, as_of: date | None = None):
    return service.positions(strategy_id, as_of)
