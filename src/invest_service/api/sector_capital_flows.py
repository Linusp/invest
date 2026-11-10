from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import SectorCapitalFlowService, SectorFlowNotFound

router = APIRouter(prefix="/sector-capital-flows", tags=["sector-capital-flows"])
DB = Annotated[Session, Depends(get_db)]

ORDER_BY_FIELDS = (
    "main_net",
    "super_large_net",
    "large_net",
    "mid_net",
    "small_net",
    "change_percent",
    "market_cap",
)


INTRADAY_FIELDS = ("main_net", "super_large_net", "large_net", "mid_net", "small_net")


@router.get("/intraday")
def intraday_series(
    db: DB,
    trade_date: date | None = Query(default=None, description="交易日，默认取库内最新"),
    top: int = Query(default=30, ge=1, le=100, description="按收盘时点绝对值取前 N 个板块"),
    field: str = Query(default="main_net", description="资金流字段"),
):
    """Aligned 1-minute series for the board-flow animation."""
    if field not in INTRADAY_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"field must be one of: {', '.join(INTRADAY_FIELDS)}",
        )
    return SectorCapitalFlowService(db).intraday_series(trade_date, top=top, field=field)


@router.get("/intraday/dates")
def intraday_dates(
    db: DB,
    limit: int = Query(default=10, ge=1, le=60),
):
    """Dates that have intraday flow points, newest first."""
    return {"dates": SectorCapitalFlowService(db).intraday_dates(limit=limit)}


@router.get("")
def list_sector_capital_flows(
    db: DB,
    trade_date: date | None = Query(default=None, description="交易日，默认取库内最新"),
    order_by: str = Query(default="main_net", description="排序字段"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=500),
    tracked_only: bool = Query(
        default=False,
        description="仅返回已同步为 market scope 的板块",
    ),
):
    """Rank EastMoney boards by a capital-flow column for one trading day."""
    if order_by not in ORDER_BY_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"order_by must be one of: {', '.join(ORDER_BY_FIELDS)}",
        )
    service = SectorCapitalFlowService(db)
    scope_codes = service.sector_codes_for_scope() if tracked_only else None
    rows = service.list_flows(
        trade_date=trade_date,
        order_by=order_by,
        direction=direction,
        limit=limit,
        scope_codes=scope_codes,
    )
    return {
        "trade_date": (trade_date or service.latest_trade_date()),
        "order_by": order_by,
        "direction": direction,
        "count": len(rows),
        "rows": rows,
    }


@router.get("/{sector_code}/history")
def get_sector_capital_flow_history(
    sector_code: str,
    db: DB,
    days: int = Query(default=30, ge=1, le=90),
):
    """Daily net-flow history for one EastMoney board, oldest first."""
    service = SectorCapitalFlowService(db)
    try:
        rows = service.flow_history(sector_code, days=days)
    except SectorFlowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return {
        "sector_code": sector_code.strip().upper(),
        "count": len(rows),
        "rows": rows,
    }
