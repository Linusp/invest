"""Persistence and queries for EastMoney board capital-flow rows."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MarketScope, MarketScopeType, SectorCapitalFlow
from ..providers.sector_flow import EastMoneySectorFlow, SectorBoard, SectorFlowError

logger = logging.getLogger(__name__)

INTERVAL_DAILY = "1d"


class SectorFlowNotFound(LookupError):
    pass


class SectorCapitalFlowService:
    def __init__(self, session: Session):
        self.session = session

    # -- refresh ----------------------------------------------------------

    def refresh_daily(
        self,
        lookback_days: int = 30,
        provider: EastMoneySectorFlow | None = None,
        sync_scopes: bool = True,
        scopes_top: int = 30,
        scopes_parent: str | None = "em_industry",
    ) -> dict[str, int]:
        """Pull the EastMoney BK pool daily flows and upsert into the table."""
        provider = provider or EastMoneySectorFlow()
        boards = provider.industry_boards()
        boards_by_code = {board.code: board for board in boards}

        # Gather the full snapshot in memory first, then upsert by key.
        incoming: dict[tuple[str, date], dict] = {}
        for board in boards:
            try:
                flows = provider.daily_flows(board.code, days=lookback_days)
            except SectorFlowError as exc:
                logger.warning(
                    "[sector-flow] skip %s(%s): %s", board.name, board.code, exc
                )
                continue
            for flow in flows:
                incoming[(board.code, flow.trade_date)] = {
                    "sector_code": board.code,
                    "sector_name": board.name,
                    "trade_date": flow.trade_date,
                    "interval": INTERVAL_DAILY,
                    "main_net": _dec(flow.main_net),
                    "super_large_net": _dec(flow.super_large_net),
                    "large_net": _dec(flow.large_net),
                    "mid_net": _dec(flow.mid_net),
                    "small_net": _dec(flow.small_net),
                    "change_percent": _dec(board.change_percent),
                    "market_cap": _dec(board.market_cap),
                    "source": "eastmoney",
                }

        created = 0
        updated = 0
        # Load existing keys within the snapshot span to decide insert vs update.
        existing = {
            (row.sector_code, row.trade_date): row
            for row in self.session.scalars(
                select(SectorCapitalFlow).where(
                    SectorCapitalFlow.sector_code.in_(list(boards_by_code)),
                    SectorCapitalFlow.interval == INTERVAL_DAILY,
                )
            )
        }
        for key, values in incoming.items():
            row = existing.get(key)
            if row is None:
                self.session.add(SectorCapitalFlow(**values))
                created += 1
            else:
                changed = False
                for field, value in values.items():
                    if field in ("sector_code", "trade_date", "interval"):
                        continue
                    if getattr(row, field) != value:
                        setattr(row, field, value)
                        changed = True
                if changed:
                    updated += 1
        self.session.commit()
        logger.info(
            "[sector-flow] daily refresh: %d rows fetched, %d created, %d updated",
            len(incoming),
            created,
            updated,
        )

        synced = 0
        if sync_scopes and boards:
            top_boards = sorted(boards, key=lambda b: b.market_cap, reverse=True)[
                :scopes_top
            ]
            synced = self.sync_tracked_scopes(top_boards, parent_code=scopes_parent)
        return {
            "boards": len(boards),
            "created": created,
            "updated": updated,
            "scopes_synced": synced,
        }

    def sync_tracked_scopes(
        self,
        boards: list[SectorBoard],
        parent_code: str | None = "em_industry",
    ) -> int:
        """Create SECTOR market scopes for the tracked boards (create-only).

        Never deletes or overwrites an existing scope. A parent scope (default
        ``em_industry``) is created lazily to group the auto-synced boards so
        they do not mix with hand-managed scopes at the top level.
        """
        parent_scope: MarketScope | None = None
        if parent_code:
            parent_code = parent_code.strip()
            if parent_code:
                parent_scope = self.session.get(MarketScope, parent_code)
                if parent_scope is None:
                    parent_scope = MarketScope(
                        code=parent_code,
                        name="东方财富行业板块",
                        scope_type=MarketScopeType.SECTOR,
                        description="自动同步的东方财富 BK 行业板块（板块资金流数据源）",
                    )
                    self.session.add(parent_scope)
                    self.session.commit()
                    logger.info("[sector-flow] created parent scope %s", parent_code)

        created = 0
        for board in boards:
            code = board.code.strip().upper()
            if not code:
                continue
            if self.session.get(MarketScope, code) is not None:
                continue  # never overwrite an existing scope
            scope = MarketScope(
                code=code,
                name=board.name,
                scope_type=MarketScopeType.SECTOR,
                parent_code=parent_scope.code if parent_scope else None,
                description="东方财富板块资金流（自动同步，只读来源）",
            )
            self.session.add(scope)
            created += 1
        if created:
            self.session.commit()
            logger.info(
                "[sector-flow] synced %d board scopes under %s",
                created,
                parent_code or "<root>",
            )
        return created

    # -- queries ----------------------------------------------------------

    def latest_trade_date(self) -> date | None:
        return self.session.scalar(
            select(func.max(SectorCapitalFlow.trade_date)).where(
                SectorCapitalFlow.interval == INTERVAL_DAILY
            )
        )

    def list_flows(
        self,
        trade_date: date | None = None,
        order_by: str = "main_net",
        direction: str = "desc",
        limit: int = 50,
        scope_codes: list[str] | None = None,
    ) -> list[dict]:
        """Rank boards by a net-flow column for one trade date."""
        target = trade_date or self.latest_trade_date()
        if target is None:
            return []
        column = getattr(SectorCapitalFlow, order_by, SectorCapitalFlow.main_net)
        query = select(SectorCapitalFlow).where(
            SectorCapitalFlow.trade_date == target,
            SectorCapitalFlow.interval == INTERVAL_DAILY,
        )
        if scope_codes:
            query = query.where(SectorCapitalFlow.sector_code.in_(scope_codes))
        query = query.order_by(column.asc() if direction == "asc" else column.desc())
        rows = list(self.session.scalars(query.limit(limit)))
        return [_row_json(row) for row in rows]

    def flow_history(
        self,
        sector_code: str,
        days: int = 30,
    ) -> list[dict]:
        """Daily net-flow history for one board, oldest first."""
        sector_code = sector_code.strip().upper()
        rows = list(
            self.session.scalars(
                select(SectorCapitalFlow)
                .where(
                    SectorCapitalFlow.sector_code == sector_code,
                    SectorCapitalFlow.interval == INTERVAL_DAILY,
                )
                .order_by(SectorCapitalFlow.trade_date.desc())
                .limit(days)
            )
        )
        if not rows:
            raise SectorFlowNotFound(f"No capital-flow data for sector {sector_code}")
        return [_row_json(row) for row in reversed(rows)]

    def sector_codes_for_scope(self, parent_code: str | None = None) -> list[str]:
        """Board codes that exist as synced SECTOR scopes (for scoping rankings)."""
        query = select(MarketScope.code).where(
            MarketScope.scope_type == MarketScopeType.SECTOR
        )
        if parent_code:
            query = query.where(MarketScope.parent_code == parent_code)
        return list(self.session.scalars(query))


def _dec(value: float | Decimal) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _row_json(row: SectorCapitalFlow) -> dict:
    return {
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "trade_date": row.trade_date.isoformat(),
        "interval": row.interval,
        "main_net": row.main_net,
        "super_large_net": row.super_large_net,
        "large_net": row.large_net,
        "mid_net": row.mid_net,
        "small_net": row.small_net,
        "change_percent": row.change_percent,
        "market_cap": row.market_cap,
        "source": row.source,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
