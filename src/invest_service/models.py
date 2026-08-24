from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AssetCategory(str, enum.Enum):
    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"


class TradeType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


asset_tags = Table(
    "asset_tags",
    Base.metadata,
    Column(
        "asset_symbol",
        String(32),
        ForeignKey("assets.symbol", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_name",
        String(64),
        ForeignKey("tags.name", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Tag(Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    assets: Mapped[list["Asset"]] = relationship(
        secondary=asset_tags,
        back_populates="tags",
    )


class Asset(Base):
    __tablename__ = "assets"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[AssetCategory] = mapped_column(
        Enum(AssetCategory, native_enum=False), index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="CNY", index=True)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    is_favorite: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    history: Mapped[list["MarketBar"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(
        secondary=asset_tags,
        back_populates="assets",
        lazy="selectin",  # codespell:ignore selectin
        order_by=Tag.name,
    )


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("asset_symbol", "trade_date", name="uq_market_bar_asset_date"),
        Index("ix_market_bars_asset_date", "asset_symbol", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_symbol: Mapped[str] = mapped_column(
        ForeignKey("assets.symbol", ondelete="CASCADE"), index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    change: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    change_percent: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    source: Mapped[str] = mapped_column(String(32), default="tushare")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    asset: Mapped[Asset] = relationship(back_populates="history")


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("trade_date", "currency", name="uq_exchange_rate_date_currency"),
        Index("ix_exchange_rates_currency_date", "currency", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    units_per_eur: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    source: Mapped[str] = mapped_column(String(32), default="ecb")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    legacy_currency: Mapped[str] = mapped_column("currency", String(3), default="CNY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    trades: Mapped[list["Trade"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )
    opening_snapshot: Mapped[OpeningSnapshot | None] = relationship(
        back_populates="strategy",
        cascade="all, delete-orphan",
        uselist=False,
    )


class OpeningSnapshot(Base):
    __tablename__ = "strategy_opening_snapshots"

    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date)
    legacy_cash: Mapped[Decimal] = mapped_column(
        "cash", Numeric(24, 6), default=Decimal("0")
    )
    legacy_historical_net_contribution: Mapped[Decimal | None] = mapped_column(
        "historical_net_contribution", Numeric(24, 6)
    )
    legacy_historical_realized_profit: Mapped[Decimal] = mapped_column(
        "historical_realized_profit",
        Numeric(24, 6), default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    strategy: Mapped[Strategy] = relationship(back_populates="opening_snapshot")
    positions: Mapped[list[OpeningPosition]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    balances: Mapped[list[OpeningBalance]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class OpeningBalance(Base):
    __tablename__ = "strategy_opening_balances"
    __table_args__ = (
        UniqueConstraint("strategy_id", "currency", name="uq_opening_balance_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategy_opening_snapshots.strategy_id", ondelete="CASCADE"),
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3))
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"))
    historical_net_contribution: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    historical_realized_profit: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal("0")
    )

    snapshot: Mapped[OpeningSnapshot] = relationship(back_populates="balances")


class OpeningPosition(Base):
    __tablename__ = "strategy_opening_positions"
    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "asset_symbol",
            name="uq_opening_position_strategy_asset",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategy_opening_snapshots.strategy_id", ondelete="CASCADE"),
        index=True,
    )
    asset_symbol: Mapped[str] = mapped_column(
        ForeignKey("assets.symbol", ondelete="RESTRICT"),
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(24, 6))

    snapshot: Mapped[OpeningSnapshot] = relationship(back_populates="positions")
    asset: Mapped[Asset] = relationship()

    @property
    def average_cost(self) -> Decimal:
        return self.cost_basis / self.quantity


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_strategy_date", "strategy_id", "trade_date", "created_at"),
        UniqueConstraint("strategy_id", "idempotency_key", name="uq_trade_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    asset_symbol: Mapped[str | None] = mapped_column(
        ForeignKey("assets.symbol", ondelete="RESTRICT"), index=True
    )
    position_id: Mapped[str | None] = mapped_column(String(36), index=True)
    type: Mapped[TradeType] = mapped_column(Enum(TradeType, native_enum=False), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0"))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    strategy: Mapped[Strategy] = relationship(back_populates="trades")
    asset: Mapped[Asset | None] = relationship()
