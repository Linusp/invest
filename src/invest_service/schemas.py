from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    AnalysisSession,
    AssetCategory,
    CommentarySource,
    CommentarySubjectType,
    InformationType,
    MarketScopeType,
    TradePlanAction,
    TradePlanLogic,
    TradePlanReviewOutcome,
    TradePlanStatus,
    TradeType,
)


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def normalize_market_scope_code(value: str) -> str:
    code = value.strip().upper()
    if not code or any(not (part.replace("_", "").isalnum()) for part in code.split(".")):
        raise ValueError(
            "market scope code must contain dot-separated letters, numbers or underscores"
        )
    return code


class MarketScopeCreate(APIModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    scope_type: MarketScopeType
    parent_code: str | None = Field(default=None, max_length=128)
    description: str | None = None

    @field_validator("code", "parent_code")
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        return normalize_market_scope_code(value) if value is not None else None


class MarketScopeUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    scope_type: MarketScopeType | None = None
    parent_code: str | None = Field(default=None, max_length=128)
    description: str | None = None

    @field_validator("parent_code")
    @classmethod
    def validate_parent_code(cls, value: str | None) -> str | None:
        return normalize_market_scope_code(value) if value is not None else None


class MarketScopeRead(APIModel):
    code: str
    name: str
    scope_type: MarketScopeType
    parent_code: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class CommentaryCreate(APIModel):
    subject_type: CommentarySubjectType
    market_scope_code: str | None = Field(default=None, max_length=128)
    portfolio_id: str | None = None
    asset_symbol: str | None = Field(default=None, max_length=32)
    asset_category: AssetCategory | None = None
    session: AnalysisSession
    trading_date: date
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    content: dict[str, Any] | str
    content_format: Literal["structured", "markdown", "html"] = "structured"
    source: CommentarySource = CommentarySource.HUMAN
    source_ref: str | None = None
    data_snapshot: dict[str, Any] | list[Any] | None = None
    has_outlook: bool = False
    has_risk: bool = False
    has_trade_plan: bool = False

    @field_validator("market_scope_code")
    @classmethod
    def validate_market_scope_code(cls, value: str | None) -> str | None:
        return normalize_market_scope_code(value) if value is not None else None

    @model_validator(mode="after")
    def validate_subject(self):
        targets = {
            CommentarySubjectType.MARKET: bool(self.market_scope_code),
            CommentarySubjectType.PORTFOLIO: bool(self.portfolio_id),
            CommentarySubjectType.ASSET: bool(
                self.asset_symbol and self.asset_category
            ),
        }
        if not targets[self.subject_type] or sum(targets.values()) != 1:
            raise ValueError(
                "commentary requires exactly one subject matching subject_type"
            )
        if self.subject_type != CommentarySubjectType.ASSET and (
            self.asset_symbol or self.asset_category
        ):
            raise ValueError("asset_symbol and asset_category are only valid for assets")
        return self


class CommentaryRevisionCreate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = None
    content: dict[str, Any] | str
    content_format: Literal["structured", "markdown", "html"] = "structured"
    source: CommentarySource = CommentarySource.HUMAN
    source_ref: str | None = None
    data_snapshot: dict[str, Any] | list[Any] | None = None
    has_outlook: bool | None = None
    has_risk: bool | None = None
    has_trade_plan: bool | None = None


class CommentaryRead(APIModel):
    id: str
    subject_type: CommentarySubjectType
    market_scope_code: str | None
    portfolio_id: str | None
    asset_symbol: str | None
    asset_category: AssetCategory | None
    session: AnalysisSession
    trading_date: date
    title: str
    summary: str | None
    content: dict[str, Any]
    content_markdown: str
    content_html: str
    source: CommentarySource
    source_ref: str | None
    data_snapshot: dict[str, Any] | list[Any] | None
    has_outlook: bool
    has_risk: bool
    has_trade_plan: bool
    revises_id: str | None
    created_at: datetime


class InformationAssetRef(APIModel):
    symbol: str = Field(min_length=1, max_length=32)
    category: AssetCategory


class InformationCreate(APIModel):
    title: str = Field(min_length=1, max_length=500)
    source_name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=4096)
    published_at: datetime
    summary: str | None = None
    content: dict[str, Any] | str
    content_format: Literal["structured", "markdown", "html"] = "structured"
    full_content: dict[str, Any] | str | None = None
    full_content_format: Literal["structured", "markdown", "html"] = "structured"
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    information_type: InformationType
    search_context: str | None = None
    content_fingerprint: str | None = Field(default=None, min_length=16, max_length=64)
    importance: int = Field(default=3, ge=1, le=5)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    market_scope_codes: list[str] = Field(default_factory=list, max_length=100)
    assets: list[InformationAssetRef] = Field(default_factory=list, max_length=100)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("information URL must use http or https")
        return value.strip()

    @field_validator("market_scope_codes")
    @classmethod
    def validate_market_scope_codes(cls, values: list[str]) -> list[str]:
        normalized = [normalize_market_scope_code(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("market_scope_codes must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_assets(self):
        identities = {(item.category, item.symbol.strip().upper()) for item in self.assets}
        if len(identities) != len(self.assets):
            raise ValueError("information assets must not contain duplicates")
        return self


class InformationRead(APIModel):
    id: str
    title: str
    source_name: str
    url: str
    published_at: datetime
    fetched_at: datetime
    summary: str | None
    content: dict[str, Any]
    content_markdown: str
    content_html: str
    full_content: dict[str, Any] | None
    language: str
    information_type: InformationType
    search_context: str | None
    content_fingerprint: str
    importance: int
    confidence: Decimal | None
    market_scope_codes: list[str]
    assets: list[InformationAssetRef]
    is_referenced: bool
    created_at: datetime


class TradePlanCondition(APIModel):
    type: str = Field(min_length=1, max_length=64)
    value: Any
    label: str | None = None
    params: dict[str, Any] | None = None


class TradePlanCreate(APIModel):
    portfolio_id: str
    asset_symbol: str = Field(min_length=1, max_length=32)
    asset_category: AssetCategory
    action: TradePlanAction
    logic: TradePlanLogic = TradePlanLogic.AND
    conditions: list[TradePlanCondition] = Field(min_length=1, max_length=20)
    quantity: Decimal | None = Field(default=None, gt=0)
    amount: Decimal | None = Field(default=None, gt=0)
    position_ratio: Decimal | None = Field(default=None, gt=0, le=1)
    confirm_days: int = Field(default=1, ge=1, le=365)
    valid_from: date | None = None
    valid_until: date | None = None
    reason: str | None = None
    risk_note: str | None = None
    source_commentary_id: str | None = None
    status: TradePlanStatus = TradePlanStatus.DRAFT

    @model_validator(mode="after")
    def validate_shape(self):
        if self.quantity is None and self.amount is None and self.position_ratio is None:
            raise ValueError("trade plan requires quantity, amount or position_ratio")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be before valid_from")
        return self


class TradePlanUpdate(APIModel):
    action: TradePlanAction | None = None
    logic: TradePlanLogic | None = None
    conditions: list[TradePlanCondition] | None = Field(default=None, min_length=1, max_length=20)
    quantity: Decimal | None = Field(default=None, gt=0)
    amount: Decimal | None = Field(default=None, gt=0)
    position_ratio: Decimal | None = Field(default=None, gt=0, le=1)
    confirm_days: int | None = Field(default=None, ge=1, le=365)
    valid_from: date | None = None
    valid_until: date | None = None
    reason: str | None = None
    risk_note: str | None = None
    source_commentary_id: str | None = None


class TradePlanStatusUpdate(APIModel):
    status: TradePlanStatus


class TradePlanRead(APIModel):
    id: str
    portfolio_id: str
    asset_symbol: str
    asset_name: str
    asset_category: AssetCategory
    action: TradePlanAction
    logic: TradePlanLogic
    conditions: list[TradePlanCondition]
    quantity: Decimal | None
    amount: Decimal | None
    position_ratio: Decimal | None
    confirm_days: int
    valid_from: date | None
    valid_until: date | None
    reason: str | None
    risk_note: str | None
    source_commentary_id: str | None
    status: TradePlanStatus
    triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TradePlanReviewCreate(APIModel):
    outcome: TradePlanReviewOutcome
    summary: str | None = None
    content: dict[str, Any] | str
    content_format: Literal["structured", "markdown", "html"] = "structured"
    realized_profit: Decimal | None = None


class TradePlanReviewRead(APIModel):
    id: str
    plan_id: str
    outcome: TradePlanReviewOutcome
    summary: str | None
    content: dict[str, Any]
    realized_profit: Decimal | None
    reviewed_at: datetime


class TradePlanStatusEventRead(APIModel):
    id: str
    plan_id: str
    from_status: TradePlanStatus
    to_status: TradePlanStatus
    reason: str | None
    created_at: datetime


class AssetCreate(APIModel):
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    category: AssetCategory
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    provider_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        return normalize_tag_names(tags)


class TagRead(APIModel):
    name: str


class TagCreate(APIModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return normalize_tag_names([name])[0]


class AssetTagsUpdate(APIModel):
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        return normalize_tag_names(tags)


class AssetTagCreate(APIModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return normalize_tag_names([name])[0]


class AssetTagMembershipRead(APIModel):
    name: str
    favorite_since: date | None
    favorite_price: Decimal | None


class AssetFavoriteUpdate(APIModel):
    is_favorite: bool


class MarketUpdateTriggerRead(APIModel):
    symbol: str
    category: AssetCategory
    queued: bool = True


class AssetRead(APIModel):
    symbol: str
    code: str
    name: str
    category: AssetCategory
    currency: str
    provider_id: str | None
    is_favorite: bool
    favorite_since: date | None
    favorite_price: Decimal | None
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime


class TagGroupRead(APIModel):
    name: str
    position: int
    is_pinned: bool
    asset_count: int


class TagOrderUpdate(APIModel):
    names: list[str] = Field(min_length=1)

    @field_validator("names")
    @classmethod
    def validate_names(cls, names: list[str]) -> list[str]:
        normalized = normalize_tag_names(names)
        if len(normalized) != len(names):
            raise ValueError("tag order must not contain duplicates")
        return normalized


class TagPinUpdate(APIModel):
    is_pinned: bool


class AssetMarketSummary(APIModel):
    symbol: str
    name: str
    category: AssetCategory
    currency: str
    favorite_since: date | None
    favorite_price: Decimal | None
    favorite_return_percent: Decimal | None
    latest_price: Decimal | None
    latest_price_date: date | None
    change: Decimal | None
    change_percent: Decimal | None


def normalize_tag_names(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in tags:
        name = " ".join(value.split())
        if not name:
            raise ValueError("tag must not be empty")
        if len(name) > 64:
            raise ValueError("tag must not exceed 64 characters")
        key = name.casefold()
        if key not in seen:
            normalized.append(name)
            seen.add(key)
    return normalized


class MarketBarRead(APIModel):
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    previous_close: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    volume: Decimal | None = Field(description="成交量，统一为股/基金份额")
    amount: Decimal | None = Field(description="成交额，统一为元")
    source: str


class MarketSyncResult(APIModel):
    symbol: str
    category: AssetCategory
    start_date: date
    end_date: date
    created: int
    updated: int


class ExchangeRateRead(APIModel):
    trade_date: date
    currency: str
    units_per_eur: Decimal
    source: str


class ExchangeRateSyncResult(APIModel):
    start_date: date
    end_date: date
    created: int
    updated: int


class BulkSyncResult(APIModel):
    succeeded: list[MarketSyncResult]
    failed: dict[str, str]


class StrategyCreate(APIModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    investment_style: str | None = Field(default=None, max_length=64)
    is_owned: bool = True
    purpose: str | None = None
    investment_direction: str | None = None
    constraints: str | None = None
    notes: str | None = None


class StrategyUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    investment_style: str | None = Field(default=None, max_length=64)
    is_owned: bool | None = None
    purpose: str | None = None
    investment_direction: str | None = None
    constraints: str | None = None
    notes: str | None = None
    display_order: int | None = None
    is_pinned: bool | None = None


class StrategyRead(APIModel):
    id: str
    name: str
    description: str | None
    investment_style: str | None
    is_owned: bool
    purpose: str | None
    investment_direction: str | None
    constraints: str | None
    notes: str | None
    display_order: int
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class TradeCreate(APIModel):
    type: TradeType
    trade_date: date
    asset_symbol: str | None = None
    asset_category: AssetCategory | None = None
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
    trade_plan_id: str | None = None

    @model_validator(mode="after")
    def validate_trade_shape(self):
        is_security_trade = self.type in (TradeType.BUY, TradeType.SELL)
        if is_security_trade and (not self.asset_symbol or self.quantity <= 0):
            raise ValueError("buy/sell requires asset_symbol and quantity > 0")
        if not is_security_trade and (
            self.asset_symbol is not None
            or self.asset_category is not None
            or self.quantity != 0
        ):
            raise ValueError("deposit/withdraw must not include an asset or quantity")
        return self


class TradeRead(APIModel):
    id: str
    strategy_id: str
    asset_symbol: str | None
    asset_category: AssetCategory | None
    position_id: str | None
    type: TradeType
    trade_date: date
    price: Decimal
    quantity: Decimal
    fee: Decimal
    currency: str
    note: str | None
    idempotency_key: str | None
    trade_plan_id: str | None
    created_at: datetime


class PositionRead(APIModel):
    asset: AssetRead
    quantity: Decimal
    average_cost: Decimal
    cost_basis: Decimal
    cost_basis_report: Decimal
    latest_price: Decimal | None
    latest_price_date: date | None
    market_value: Decimal | None
    market_value_report: Decimal | None
    realized_profit: Decimal
    realized_profit_report: Decimal
    unrealized_profit: Decimal | None
    unrealized_profit_report: Decimal | None


class OpeningPositionCreate(APIModel):
    asset_symbol: str = Field(min_length=1, max_length=32)
    asset_category: AssetCategory | None = None
    quantity: Decimal = Field(gt=0)
    average_cost: Decimal = Field(gt=0)


class OpeningBalanceUpsert(APIModel):
    currency: str = Field(min_length=3, max_length=3)
    cash: Decimal = Decimal("0")
    historical_net_contribution: Decimal | None = None
    historical_realized_profit: Decimal = Decimal("0")


class OpeningSnapshotUpsert(APIModel):
    snapshot_date: date
    balances: list[OpeningBalanceUpsert] = Field(default_factory=list)
    positions: list[OpeningPositionCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_positions(self):
        identities = [
            (item.asset_category, item.asset_symbol.strip().upper())
            for item in self.positions
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("opening snapshot positions must have unique asset identities")
        currencies = [item.currency.strip().upper() for item in self.balances]
        if len(currencies) != len(set(currencies)):
            raise ValueError("opening snapshot balances must have unique currencies")
        return self


class OpeningPositionRead(APIModel):
    asset: AssetRead
    quantity: Decimal
    average_cost: Decimal
    cost_basis: Decimal


class OpeningBalanceRead(APIModel):
    currency: str
    cash: Decimal
    historical_net_contribution: Decimal | None
    historical_realized_profit: Decimal


class OpeningSnapshotRead(APIModel):
    snapshot_date: date
    balances: list[OpeningBalanceRead]
    positions: list[OpeningPositionRead]
    created_at: datetime
    updated_at: datetime


class CurrencyAmountRead(APIModel):
    currency: str
    amount: Decimal
    report_amount: Decimal


class StrategySummary(APIModel):
    reporting_currency: str
    cash_balance: Decimal
    cash_balances: list[CurrencyAmountRead]
    net_contribution: Decimal | None
    market_value: Decimal
    total_value: Decimal
    historical_realized_profit: Decimal
    realized_profit_since_snapshot: Decimal
    realized_profit: Decimal
    unrealized_profit: Decimal
    total_profit: Decimal
    completed_position_count: int
    winning_position_count: int
    win_rate: Decimal | None
    profit_loss_ratio: Decimal | None


class StrategyDetail(StrategyRead):
    summary: StrategySummary
    positions: list[PositionRead]
    trades: list[TradeRead]
    opening_snapshot: OpeningSnapshotRead | None
