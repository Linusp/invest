from datetime import date

from fastapi import APIRouter, Query, Response, status

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
from .strategies import Service

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.get("", response_model=list[StrategyRead])
def list_portfolios(
    service: Service,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return service.list(limit, offset)


@router.post("", response_model=StrategyRead, status_code=status.HTTP_201_CREATED)
def create_portfolio(data: StrategyCreate, service: Service):
    return service.create(data)


@router.get("/{portfolio_id}", response_model=StrategyDetail)
def get_portfolio(portfolio_id: str, service: Service):
    return service.detail(portfolio_id)


@router.patch("/{portfolio_id}", response_model=StrategyRead)
def update_portfolio(portfolio_id: str, data: StrategyUpdate, service: Service):
    return service.update(portfolio_id, data)


@router.get(
    "/{portfolio_id}/opening-snapshot",
    response_model=OpeningSnapshotRead | None,
)
def get_opening_snapshot(portfolio_id: str, service: Service):
    return service.opening_snapshot(portfolio_id)


@router.put(
    "/{portfolio_id}/opening-snapshot",
    response_model=OpeningSnapshotRead,
)
def set_opening_snapshot(
    portfolio_id: str, data: OpeningSnapshotUpsert, service: Service
):
    return service.set_opening_snapshot(portfolio_id, data)


@router.delete(
    "/{portfolio_id}/opening-snapshot",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_opening_snapshot(portfolio_id: str, service: Service):
    service.delete_opening_snapshot(portfolio_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{portfolio_id}/trades", response_model=list[TradeRead])
def list_trades(portfolio_id: str, service: Service):
    return service.trades(portfolio_id)


@router.post(
    "/{portfolio_id}/trades",
    response_model=TradeRead,
    status_code=status.HTTP_201_CREATED,
)
def add_trade(portfolio_id: str, data: TradeCreate, service: Service):
    return service.add_trade(portfolio_id, data)


@router.get("/{portfolio_id}/positions", response_model=list[PositionRead])
def list_positions(
    portfolio_id: str, service: Service, as_of: date | None = None
):
    return service.positions(portfolio_id, as_of)
