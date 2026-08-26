from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..commentary_content import normalize_content
from ..models import (
    Asset,
    AssetCategory,
    Commentary,
    Strategy,
    TradePlan,
    TradePlanStatus,
    TradePlanStatusEvent,
    asset_identity,
    utcnow,
)
from ..schemas import (
    TradePlanCreate,
    TradePlanRead,
    TradePlanReviewCreate,
    TradePlanReviewRead,
    TradePlanStatusUpdate,
    TradePlanUpdate,
)

SIX_PLACES = Decimal("0.000001")


def _six(value: Decimal | None) -> Decimal | None:
    return value.quantize(SIX_PLACES) if value is not None else None


class TradePlanNotFound(LookupError):
    pass


class InvalidTradePlan(ValueError):
    pass


_TRANSITIONS = {
    TradePlanStatus.DRAFT: {TradePlanStatus.ACTIVE, TradePlanStatus.CANCELLED},
    TradePlanStatus.ACTIVE: {
        TradePlanStatus.TRIGGERED,
        TradePlanStatus.EXPIRED,
        TradePlanStatus.CANCELLED,
    },
    TradePlanStatus.TRIGGERED: {
        TradePlanStatus.ACTIVE,
        TradePlanStatus.PARTIALLY_EXECUTED,
        TradePlanStatus.EXECUTED,
        TradePlanStatus.CANCELLED,
    },
    TradePlanStatus.PARTIALLY_EXECUTED: {
        TradePlanStatus.EXECUTED,
        TradePlanStatus.CANCELLED,
    },
    TradePlanStatus.EXECUTED: set(),
    TradePlanStatus.EXPIRED: set(),
    TradePlanStatus.CANCELLED: set(),
}


class TradePlanService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: TradePlanCreate) -> TradePlanRead:
        self._validate_refs(data.portfolio_id, data.asset_category, data.asset_symbol)
        if data.source_commentary_id and self.session.get(
            Commentary, data.source_commentary_id
        ) is None:
            raise InvalidTradePlan("source commentary was not found")
        plan = TradePlan(
            portfolio_id=data.portfolio_id,
            asset_key=asset_identity(data.asset_category, data.asset_symbol),
            action=data.action,
            logic=data.logic,
            conditions=[condition.model_dump(mode="json") for condition in data.conditions],
            quantity=_six(data.quantity),
            amount=_six(data.amount),
            position_ratio=_six(data.position_ratio),
            confirm_days=data.confirm_days,
            valid_from=data.valid_from,
            valid_until=data.valid_until,
            reason=data.reason,
            risk_note=data.risk_note,
            source_commentary_id=data.source_commentary_id,
            status=data.status,
        )
        self.session.add(plan)
        self.session.commit()
        return self._read(self._load(plan.id))

    def list(
        self,
        portfolio_id: str | None = None,
        asset_symbol: str | None = None,
        asset_category: AssetCategory | None = None,
        status: TradePlanStatus | None = None,
        as_of: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradePlanRead]:
        statement = select(TradePlan).options(selectinload(TradePlan.asset))
        if portfolio_id:
            statement = statement.where(TradePlan.portfolio_id == portfolio_id)
        if status:
            statement = statement.where(TradePlan.status == status)
        if asset_symbol and asset_category:
            statement = statement.where(
                TradePlan.asset_key == asset_identity(asset_category, asset_symbol)
            )
        if as_of:
            statement = statement.where(
                (TradePlan.valid_from.is_(None) | (TradePlan.valid_from <= as_of)),
                (TradePlan.valid_until.is_(None) | (TradePlan.valid_until >= as_of)),
            )
        plans = list(
            self.session.scalars(
                statement.order_by(TradePlan.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return [self._read(plan) for plan in plans]

    def get(self, plan_id: str) -> TradePlanRead:
        return self._read(self._load(plan_id))

    def update(self, plan_id: str, data: TradePlanUpdate) -> TradePlanRead:
        plan = self._load(plan_id)
        if plan.status != TradePlanStatus.DRAFT:
            raise InvalidTradePlan("only draft trade plans can be edited")
        values = data.model_dump(exclude_unset=True, mode="json")
        for field, value in values.items():
            if field == "conditions":
                value = [item.model_dump(mode="json") for item in data.conditions or []]
            setattr(plan, field, value)
        if plan.valid_from and plan.valid_until and plan.valid_until < plan.valid_from:
            raise InvalidTradePlan("valid_until must not be before valid_from")
        self.session.commit()
        return self._read(self._load(plan_id))

    def change_status(self, plan_id: str, data: TradePlanStatusUpdate) -> TradePlanRead:
        plan = self._load(plan_id)
        if data.status == plan.status:
            return self._read(plan)
        if data.status not in _TRANSITIONS[plan.status]:
            raise InvalidTradePlan(
                f"cannot change trade plan from {plan.status.value} to {data.status.value}"
            )
        previous = plan.status
        plan.status = data.status
        if data.status == TradePlanStatus.TRIGGERED:
            plan.triggered_at = utcnow()
        self.session.add(
            TradePlanStatusEvent(
                plan_id=plan.id, from_status=previous, to_status=data.status
            )
        )
        self.session.commit()
        return self._read(self._load(plan_id))

    def history(self, plan_id: str):
        plan = self._load(plan_id)
        return list(
            self.session.scalars(
                select(TradePlanStatusEvent)
                .where(TradePlanStatusEvent.plan_id == plan.id)
                .order_by(TradePlanStatusEvent.created_at)
            )
        )

    def review(self, plan_id: str, data: TradePlanReviewCreate) -> TradePlanReviewRead:
        plan = self._load(plan_id)
        review = plan.review
        if review is None:
            from ..models import TradePlanReview

            review = TradePlanReview(plan_id=plan.id)
            self.session.add(review)
        review.outcome = data.outcome
        review.summary = data.summary
        review.content = normalize_content(data.content, data.content_format)
        review.realized_profit = data.realized_profit
        self.session.commit()
        return self._review_read(review)

    def get_review(self, plan_id: str) -> TradePlanReviewRead | None:
        plan = self._load(plan_id)
        return self._review_read(plan.review) if plan.review else None

    def _validate_refs(
        self, portfolio_id: str, category: AssetCategory, symbol: str
    ) -> None:
        if self.session.get(Strategy, portfolio_id) is None:
            raise InvalidTradePlan(f"Portfolio {portfolio_id} was not found")
        if self.session.get(Asset, asset_identity(category, symbol)) is None:
            raise InvalidTradePlan(f"Asset {category.value}:{symbol} was not found")

    def _load(self, plan_id: str) -> TradePlan:
        plan = self.session.scalar(
            select(TradePlan)
            .options(selectinload(TradePlan.asset))
            .where(TradePlan.id == plan_id)
        )
        if plan is None:
            raise TradePlanNotFound(f"Trade plan {plan_id} was not found")
        return plan

    @staticmethod
    def _read(plan: TradePlan) -> TradePlanRead:
        return TradePlanRead(
            id=plan.id,
            portfolio_id=plan.portfolio_id,
            asset_symbol=plan.asset.symbol,
            asset_name=plan.asset.name,
            asset_category=plan.asset.category,
            action=plan.action,
            logic=plan.logic,
            conditions=plan.conditions,
            quantity=plan.quantity,
            amount=plan.amount,
            position_ratio=plan.position_ratio,
            confirm_days=plan.confirm_days,
            valid_from=plan.valid_from,
            valid_until=plan.valid_until,
            reason=plan.reason,
            risk_note=plan.risk_note,
            source_commentary_id=plan.source_commentary_id,
            status=plan.status,
            triggered_at=plan.triggered_at,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    @staticmethod
    def _review_read(review) -> TradePlanReviewRead:
        return TradePlanReviewRead(
            id=review.id,
            plan_id=review.plan_id,
            outcome=review.outcome,
            summary=review.summary,
            content=review.content,
            realized_profit=review.realized_profit,
            reviewed_at=review.reviewed_at,
        )
