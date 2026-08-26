from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..models import (
    Asset,
    AssetCategory,
    MarketBar,
    OpeningBalance,
    OpeningPosition,
    OpeningSnapshot,
    Strategy,
    Trade,
    TradeType,
    asset_identity,
)
from ..position_cycles import assign_position_ids, ordered_trades
from ..schemas import (
    AssetRead,
    CurrencyAmountRead,
    OpeningSnapshotRead,
    OpeningSnapshotUpsert,
    PositionRead,
    StrategyCreate,
    StrategyDetail,
    StrategyRead,
    StrategySummary,
    StrategyUpdate,
    TradeCreate,
    TradeRead,
)
from .exchange_rate import ExchangeRateService

ZERO = Decimal("0")
EPSILON = Decimal("0.000001")
SIX_PLACES = Decimal("0.000001")


def _six(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES)


class StrategyNotFound(LookupError):
    pass


class InvalidTrade(ValueError):
    pass


@dataclass
class _Position:
    asset: Asset
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    cost_basis_report: Decimal = ZERO
    realized_profit: Decimal = ZERO
    realized_profit_report: Decimal = ZERO


@dataclass
class _PositionCycle:
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    maximum_investment: Decimal = ZERO
    profit: Decimal = ZERO


class StrategyService:
    def __init__(self, session: Session, reporting_currency: str | None = None):
        self.session = session
        self.reporting_currency = (
            reporting_currency or get_settings().reporting_currency
        ).upper()
        self.exchange_rates = ExchangeRateService(
            session, reporting_currency=self.reporting_currency
        )

    def _resolve_asset(
        self,
        symbol: str,
        category: AssetCategory | None,
    ) -> Asset:
        symbol = symbol.strip().upper()
        if category is not None:
            asset = self.session.get(Asset, asset_identity(category, symbol))
        else:
            matches = list(
                self.session.scalars(
                    select(Asset).where(Asset.symbol == symbol).limit(2)
                )
            )
            if len(matches) > 1:
                raise InvalidTrade(
                    f"Asset {symbol} is ambiguous; asset_category is required"
                )
            asset = matches[0] if matches else None
        if asset is None:
            raise InvalidTrade(f"Asset {symbol} must be registered before trading")
        return asset

    def create(self, data: StrategyCreate) -> Strategy:
        strategy = Strategy(
            name=data.name.strip(),
            description=data.description,
            initial_capital=(
                _six(data.initial_capital) if data.initial_capital is not None else None
            ),
            investment_style=data.investment_style,
            is_owned=data.is_owned,
            purpose=data.purpose,
            investment_direction=data.investment_direction,
            constraints=data.constraints,
            notes=data.notes,
            legacy_currency=self.reporting_currency,
        )
        self.session.add(strategy)
        self.session.commit()
        return strategy

    def list(self, limit: int = 100, offset: int = 0) -> list[Strategy]:
        return list(
            self.session.scalars(
                select(Strategy).order_by(Strategy.created_at.desc()).offset(offset).limit(limit)
            )
        )

    def get(self, strategy_id: str) -> Strategy:
        strategy = self.session.scalar(
            select(Strategy)
            .options(
                selectinload(Strategy.trades).selectinload(Trade.asset),
                selectinload(Strategy.opening_snapshot)
                .selectinload(OpeningSnapshot.positions)
                .selectinload(OpeningPosition.asset),
                selectinload(Strategy.opening_snapshot).selectinload(
                    OpeningSnapshot.balances
                ),
            )
            .where(Strategy.id == strategy_id)
        )
        if strategy is None:
            raise StrategyNotFound(f"Strategy {strategy_id} was not found")
        return strategy

    def update(self, strategy_id: str, data: StrategyUpdate) -> Strategy:
        strategy = self.get(strategy_id)
        if data.name is not None:
            strategy.name = data.name.strip()
        for field in (
            "description",
            "initial_capital",
            "investment_style",
            "is_owned",
            "purpose",
            "investment_direction",
            "constraints",
            "notes",
        ):
            if field in data.model_fields_set:
                value = getattr(data, field)
                if field == "initial_capital" and value is not None:
                    value = _six(value)
                setattr(strategy, field, value)
        self.session.commit()
        return strategy

    def trades(self, strategy_id: str) -> list[Trade]:
        self.get(strategy_id)
        return list(
            self.session.scalars(
                select(Trade)
                .where(Trade.strategy_id == strategy_id)
                .order_by(Trade.trade_date.desc(), Trade.created_at.desc(), Trade.id.desc())
            )
        )

    def add_trade(self, strategy_id: str, data: TradeCreate) -> Trade:
        strategy = self.get(strategy_id)
        if (
            strategy.opening_snapshot is not None
            and data.trade_date <= strategy.opening_snapshot.snapshot_date
        ):
            raise InvalidTrade(
                "Trade date must be after opening snapshot date "
                f"{strategy.opening_snapshot.snapshot_date}"
            )
        if data.idempotency_key:
            existing = self.session.scalar(
                select(Trade).where(
                    Trade.strategy_id == strategy_id,
                    Trade.idempotency_key == data.idempotency_key,
                )
            )
            if existing:
                return existing
        symbol = data.asset_symbol.upper() if data.asset_symbol else None
        asset = self._resolve_asset(symbol, data.asset_category) if symbol else None
        currency = asset.currency if asset is not None else (
            data.currency or self.reporting_currency
        ).upper()
        trade = Trade(
            strategy=strategy,
            asset=asset,
            type=data.type,
            trade_date=data.trade_date,
            price=data.price,
            quantity=data.quantity,
            fee=data.fee,
            currency=currency,
            note=data.note,
            idempotency_key=data.idempotency_key,
        )
        self.session.add(trade)
        try:
            self.session.flush()
            assign_position_ids(strategy.trades, strategy.opening_snapshot)
            self._build_ledger(strategy, reject_negative=True)
            self.session.commit()
        except (InvalidTrade, IntegrityError):
            self.session.rollback()
            raise
        return trade

    def set_opening_snapshot(
        self,
        strategy_id: str,
        data: OpeningSnapshotUpsert,
    ) -> OpeningSnapshot:
        strategy = self.get(strategy_id)
        conflicting_trade = next(
            (trade for trade in strategy.trades if trade.trade_date <= data.snapshot_date),
            None,
        )
        if conflicting_trade is not None:
            raise InvalidTrade(
                "Opening snapshot date must be before every existing trade; "
                f"found trade on {conflicting_trade.trade_date}"
            )

        assets: dict[tuple[AssetCategory | None, str], Asset] = {}
        for item in data.positions:
            symbol = item.asset_symbol.strip().upper()
            assets[(item.asset_category, symbol)] = self._resolve_asset(
                symbol,
                item.asset_category,
            )

        snapshot = strategy.opening_snapshot
        if snapshot is None:
            snapshot = OpeningSnapshot(strategy=strategy)
            self.session.add(snapshot)
        else:
            snapshot.positions.clear()
            snapshot.balances.clear()
            self.session.flush()

        snapshot.snapshot_date = data.snapshot_date
        snapshot.legacy_cash = ZERO
        snapshot.legacy_historical_net_contribution = None
        snapshot.legacy_historical_realized_profit = ZERO
        for item in data.balances:
            snapshot.balances.append(
                OpeningBalance(
                    currency=item.currency.strip().upper(),
                    cash=_six(item.cash),
                    historical_net_contribution=(
                        _six(item.historical_net_contribution)
                        if item.historical_net_contribution is not None
                        else None
                    ),
                    historical_realized_profit=_six(item.historical_realized_profit),
                )
            )
        for item in data.positions:
            symbol = item.asset_symbol.strip().upper()
            snapshot.positions.append(
                OpeningPosition(
                    asset=assets[(item.asset_category, symbol)],
                    quantity=_six(item.quantity),
                    cost_basis=_six(item.quantity * item.average_cost),
                )
            )
        self.session.flush()
        assign_position_ids(strategy.trades, snapshot)
        self.session.commit()
        return snapshot

    def opening_snapshot(self, strategy_id: str) -> OpeningSnapshot | None:
        return self.get(strategy_id).opening_snapshot

    def delete_opening_snapshot(self, strategy_id: str) -> None:
        strategy = self.get(strategy_id)
        if strategy.opening_snapshot is None:
            return
        if strategy.trades:
            raise InvalidTrade("Opening snapshot cannot be deleted while trades exist")
        self.session.delete(strategy.opening_snapshot)
        self.session.commit()

    def _ordered_trades(self, strategy: Strategy) -> list[Trade]:
        return ordered_trades(strategy.trades)

    def _completed_position_returns(self, strategy: Strategy) -> list[Decimal]:
        cycles: dict[str, _PositionCycle] = {}
        opening_cycle_ids: dict[str, str] = {}
        snapshot = strategy.opening_snapshot

        if snapshot is not None:
            opening_keys = {item.asset_key for item in snapshot.positions}
            for trade in self._ordered_trades(strategy):
                if (
                    trade.asset_key in opening_keys
                    and trade.position_id is not None
                    and trade.asset_key not in opening_cycle_ids
                ):
                    opening_cycle_ids[trade.asset_key] = trade.position_id
            for item in snapshot.positions:
                position_id = opening_cycle_ids.get(item.asset_key)
                if position_id is None:
                    continue
                cycles[position_id] = _PositionCycle(
                    quantity=item.quantity,
                    cost_basis=item.cost_basis,
                    maximum_investment=item.cost_basis,
                )

        for trade in self._ordered_trades(strategy):
            if trade.type not in (TradeType.BUY, TradeType.SELL):
                continue
            if trade.position_id is None:
                continue
            cycle = cycles.setdefault(trade.position_id, _PositionCycle())
            gross = trade.price * trade.quantity
            if trade.type == TradeType.BUY:
                cycle.quantity += trade.quantity
                cycle.cost_basis += gross + trade.fee
                cycle.maximum_investment = max(
                    cycle.maximum_investment,
                    cycle.cost_basis,
                )
                continue

            average_cost = (
                cycle.cost_basis / cycle.quantity
                if cycle.quantity > EPSILON
                else ZERO
            )
            removed_cost = average_cost * min(trade.quantity, cycle.quantity)
            cycle.quantity -= trade.quantity
            cycle.cost_basis -= removed_cost
            cycle.profit += gross - trade.fee - removed_cost
            if abs(cycle.quantity) <= EPSILON:
                cycle.quantity = ZERO
                cycle.cost_basis = ZERO

        return [
            cycle.profit / cycle.maximum_investment
            for cycle in cycles.values()
            if cycle.quantity == ZERO and cycle.maximum_investment > ZERO
        ]

    def _build_ledger(
        self,
        strategy: Strategy,
        reject_negative: bool = False,
        as_of: date | None = None,
    ) -> tuple[dict[str, _Position], dict[str, Decimal], Decimal | None, Decimal]:
        positions: dict[str, _Position] = {}
        cash: dict[str, Decimal] = defaultdict(lambda: ZERO)
        net_contribution: Decimal | None = ZERO
        historical_realized_profit = ZERO
        snapshot = strategy.opening_snapshot
        snapshot_applies = snapshot is not None and (
            as_of is None or snapshot.snapshot_date <= as_of
        )
        if snapshot_applies:
            for balance in snapshot.balances:
                currency = balance.currency
                cash[currency] += balance.cash
                if balance.historical_net_contribution is None:
                    net_contribution = None
                elif net_contribution is not None:
                    net_contribution += self.exchange_rates.convert(
                        balance.historical_net_contribution,
                        currency,
                        self.reporting_currency,
                        snapshot.snapshot_date,
                    )
                historical_realized_profit += self.exchange_rates.convert(
                    balance.historical_realized_profit,
                    currency,
                    self.reporting_currency,
                    snapshot.snapshot_date,
                )
            for item in snapshot.positions:
                cost_basis_report = self.exchange_rates.convert(
                    item.cost_basis,
                    item.asset.currency,
                    self.reporting_currency,
                    snapshot.snapshot_date,
                )
                positions[item.asset_key] = _Position(
                    asset=item.asset,
                    quantity=item.quantity,
                    cost_basis=item.cost_basis,
                    cost_basis_report=cost_basis_report,
                )
        for trade in self._ordered_trades(strategy):
            if as_of and trade.trade_date > as_of:
                continue
            if snapshot_applies and trade.trade_date <= snapshot.snapshot_date:
                continue
            if trade.type == TradeType.DEPOSIT:
                cash[trade.currency] += trade.price
                if net_contribution is not None:
                    net_contribution += self.exchange_rates.convert(
                        trade.price,
                        trade.currency,
                        self.reporting_currency,
                        trade.trade_date,
                    )
                continue
            if trade.type == TradeType.WITHDRAW:
                cash[trade.currency] -= trade.price
                if net_contribution is not None:
                    net_contribution -= self.exchange_rates.convert(
                        trade.price,
                        trade.currency,
                        self.reporting_currency,
                        trade.trade_date,
                    )
                continue

            assert trade.asset is not None
            position = positions.setdefault(trade.asset_key, _Position(asset=trade.asset))
            gross = trade.price * trade.quantity
            if trade.type == TradeType.BUY:
                gross_report = self.exchange_rates.convert(
                    gross + trade.fee,
                    trade.currency,
                    self.reporting_currency,
                    trade.trade_date,
                )
                position.quantity += trade.quantity
                position.cost_basis += gross + trade.fee
                position.cost_basis_report += gross_report
                cash[trade.currency] -= gross + trade.fee
                continue

            if reject_negative and trade.quantity - position.quantity > EPSILON:
                raise InvalidTrade(
                    f"Sell quantity {trade.quantity} exceeds {trade.asset_symbol} position "
                    f"{position.quantity} on {trade.trade_date}"
                )
            sold_quantity = min(trade.quantity, position.quantity)
            average_cost = position.cost_basis / position.quantity if position.quantity else ZERO
            average_cost_report = (
                position.cost_basis_report / position.quantity
                if position.quantity
                else ZERO
            )
            removed_cost = average_cost * sold_quantity
            removed_cost_report = average_cost_report * sold_quantity
            position.quantity -= sold_quantity
            position.cost_basis -= removed_cost
            position.cost_basis_report -= removed_cost_report
            position.realized_profit += gross - trade.fee - removed_cost
            proceeds_report = self.exchange_rates.convert(
                gross - trade.fee,
                trade.currency,
                self.reporting_currency,
                trade.trade_date,
            )
            position.realized_profit_report += proceeds_report - removed_cost_report
            cash[trade.currency] += gross - trade.fee
            if abs(position.quantity) <= EPSILON:
                position.quantity = ZERO
                position.cost_basis = ZERO
                position.cost_basis_report = ZERO
        return positions, cash, net_contribution, historical_realized_profit

    def positions(self, strategy_id: str, as_of: date | None = None) -> list[PositionRead]:
        strategy = self.get(strategy_id)
        positions, _, _, _ = self._build_ledger(strategy, as_of=as_of)
        result = []
        for position in positions.values():
            if position.quantity <= EPSILON:
                continue
            price_stmt = select(MarketBar).where(MarketBar.asset_key == position.asset.key)
            if as_of:
                price_stmt = price_stmt.where(MarketBar.trade_date <= as_of)
            latest = self.session.scalar(price_stmt.order_by(MarketBar.trade_date.desc()).limit(1))
            latest_price = latest.close if latest else None
            market_value = latest_price * position.quantity if latest_price is not None else None
            valuation_date = as_of or date.today()
            market_value_report = (
                self.exchange_rates.convert(
                    market_value,
                    position.asset.currency,
                    self.reporting_currency,
                    valuation_date,
                )
                if market_value is not None
                else None
            )
            average_cost = position.cost_basis / position.quantity
            result.append(
                PositionRead(
                    asset=AssetRead.model_validate(position.asset),
                    quantity=_six(position.quantity),
                    average_cost=_six(average_cost),
                    cost_basis=_six(position.cost_basis),
                    cost_basis_report=_six(position.cost_basis_report),
                    latest_price=latest_price,
                    latest_price_date=latest.trade_date if latest else None,
                    market_value=_six(market_value) if market_value is not None else None,
                    market_value_report=(
                        _six(market_value_report)
                        if market_value_report is not None
                        else None
                    ),
                    realized_profit=_six(position.realized_profit),
                    realized_profit_report=_six(position.realized_profit_report),
                    unrealized_profit=_six(market_value - position.cost_basis)
                    if market_value is not None
                    else None,
                    unrealized_profit_report=(
                        _six(market_value_report - position.cost_basis_report)
                        if market_value_report is not None
                        else None
                    ),
                )
            )
        return sorted(result, key=lambda item: item.asset.symbol)

    def detail(self, strategy_id: str) -> StrategyDetail:
        strategy = self.get(strategy_id)
        ledger, cash, net_contribution, historical_realized = self._build_ledger(strategy)
        positions = self.positions(strategy_id)
        valuation_date = date.today()
        cash_balances = [
            CurrencyAmountRead(
                currency=currency,
                amount=_six(amount),
                report_amount=_six(
                    self.exchange_rates.convert(
                        amount,
                        currency,
                        self.reporting_currency,
                        valuation_date,
                    )
                ),
            )
            for currency, amount in sorted(cash.items())
            if abs(amount) > EPSILON
        ]
        cash_report = sum((item.report_amount for item in cash_balances), ZERO)
        market_value = sum((item.market_value_report or ZERO for item in positions), ZERO)
        unrealized = sum(
            (item.unrealized_profit_report or ZERO for item in positions), ZERO
        )
        realized_since_snapshot = sum(
            (item.realized_profit_report for item in ledger.values()), ZERO
        )
        realized = historical_realized + realized_since_snapshot
        total_value = cash_report + market_value
        total_profit = (
            total_value - net_contribution
            if net_contribution is not None
            else realized + unrealized
        )
        completed_returns = self._completed_position_returns(strategy)
        winning_returns = [value for value in completed_returns if value > ZERO]
        losing_returns = [value for value in completed_returns if value < ZERO]
        win_rate = (
            Decimal(len(winning_returns)) / Decimal(len(completed_returns))
            if completed_returns
            else None
        )
        profit_loss_ratio = None
        if winning_returns and losing_returns:
            average_win = sum(winning_returns, ZERO) / Decimal(len(winning_returns))
            average_loss = abs(
                sum(losing_returns, ZERO) / Decimal(len(losing_returns))
            )
            if average_loss > ZERO:
                profit_loss_ratio = average_win / average_loss
        return StrategyDetail(
            **StrategyRead.model_validate(strategy).model_dump(),
            summary=StrategySummary(
                reporting_currency=self.reporting_currency,
                cash_balance=_six(cash_report),
                cash_balances=cash_balances,
                net_contribution=_six(net_contribution)
                if net_contribution is not None
                else None,
                market_value=_six(market_value),
                total_value=_six(total_value),
                historical_realized_profit=_six(historical_realized),
                realized_profit_since_snapshot=_six(realized_since_snapshot),
                realized_profit=_six(realized),
                unrealized_profit=_six(unrealized),
                total_profit=_six(total_profit),
                completed_position_count=len(completed_returns),
                winning_position_count=len(winning_returns),
                win_rate=_six(win_rate) if win_rate is not None else None,
                profit_loss_ratio=(
                    _six(profit_loss_ratio)
                    if profit_loss_ratio is not None
                    else None
                ),
            ),
            positions=positions,
            trades=[TradeRead.model_validate(item) for item in self.trades(strategy_id)],
            opening_snapshot=OpeningSnapshotRead.model_validate(strategy.opening_snapshot)
            if strategy.opening_snapshot is not None
            else None,
        )
