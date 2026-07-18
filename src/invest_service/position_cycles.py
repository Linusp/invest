from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timezone
from decimal import Decimal

from .models import OpeningSnapshot, Trade, TradeType

ZERO = Decimal("0")
EPSILON = Decimal("0.000001")


def ordered_trades(trades: list[Trade]) -> list[Trade]:
    def order_key(item: Trade):
        created_at = item.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return item.trade_date, created_at.timestamp(), item.id

    return sorted(trades, key=order_key)


def assign_position_ids(
    trades: list[Trade],
    opening_snapshot: OpeningSnapshot | None = None,
) -> bool:
    """Assign one stable ID to each end-of-day holding cycle.

    A cycle only closes when the position is zero after all trades for a date.
    Existing IDs are retained where possible so a backfill or a newly appended
    trade does not unnecessarily rewrite historical identifiers.
    """
    changed = False
    security_trades: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        if trade.type in (TradeType.BUY, TradeType.SELL):
            assert trade.asset_symbol is not None
            security_trades[trade.asset_symbol].append(trade)
        elif trade.position_id is not None:
            trade.position_id = None
            changed = True

    opening_quantities = {
        item.asset_symbol: item.quantity
        for item in opening_snapshot.positions
    } if opening_snapshot is not None else {}

    used_ids: set[str] = set()
    for symbol, symbol_trades in sorted(security_trades.items()):
        quantity = opening_quantities.get(symbol, ZERO)
        active = quantity > EPSILON
        segments: list[list[Trade]] = []
        current_segment: list[Trade] | None = [] if active else None

        by_date: dict[object, list[Trade]] = defaultdict(list)
        for trade in ordered_trades(symbol_trades):
            by_date[trade.trade_date].append(trade)

        for trade_date in sorted(by_date):
            daily_trades = by_date[trade_date]
            if not active:
                current_segment = []
                active = True
            assert current_segment is not None
            current_segment.extend(daily_trades)

            for trade in daily_trades:
                if trade.type == TradeType.BUY:
                    quantity += trade.quantity
                else:
                    quantity -= trade.quantity

            if abs(quantity) <= EPSILON:
                quantity = ZERO
                segments.append(current_segment)
                current_segment = None
                active = False

        if current_segment:
            segments.append(current_segment)

        for segment in segments:
            position_id = next(
                (
                    trade.position_id
                    for trade in segment
                    if trade.position_id and trade.position_id not in used_ids
                ),
                None,
            )
            if position_id is None:
                position_id = str(uuid.uuid4())
            used_ids.add(position_id)
            for trade in segment:
                if trade.position_id != position_id:
                    trade.position_id = position_id
                    changed = True

    return changed
