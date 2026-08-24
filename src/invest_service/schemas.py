from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import AssetCategory, TradeType


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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


class AssetTagsUpdate(APIModel):
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        return normalize_tag_names(tags)


class AssetFavoriteUpdate(APIModel):
    is_favorite: bool


class AssetRead(APIModel):
    symbol: str
    code: str
    name: str
    category: AssetCategory
    currency: str
    provider_id: str | None
    is_favorite: bool
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime


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
    volume: Decimal | None
    amount: Decimal | None
    source: str


class MarketSyncResult(APIModel):
    symbol: str
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


class StrategyUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class StrategyRead(APIModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class TradeCreate(APIModel):
    type: TradeType
    trade_date: date
    asset_symbol: str | None = None
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_trade_shape(self):
        is_security_trade = self.type in (TradeType.BUY, TradeType.SELL)
        if is_security_trade and (not self.asset_symbol or self.quantity <= 0):
            raise ValueError("buy/sell requires asset_symbol and quantity > 0")
        if not is_security_trade and (self.asset_symbol is not None or self.quantity != 0):
            raise ValueError("deposit/withdraw must not include an asset or quantity")
        return self


class TradeRead(APIModel):
    id: str
    strategy_id: str
    asset_symbol: str | None
    position_id: str | None
    type: TradeType
    trade_date: date
    price: Decimal
    quantity: Decimal
    fee: Decimal
    currency: str
    note: str | None
    idempotency_key: str | None
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
        symbols = [item.asset_symbol.strip().upper() for item in self.positions]
        if len(symbols) != len(set(symbols)):
            raise ValueError("opening snapshot positions must have unique asset symbols")
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
