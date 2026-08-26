from __future__ import annotations

import enum
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    false,
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


class MarketScopeType(str, enum.Enum):
    MARKET = "market"
    SECTOR = "sector"
    THEME = "theme"
    COMMODITY = "commodity"


class CommentarySubjectType(str, enum.Enum):
    MARKET = "market"
    PORTFOLIO = "portfolio"
    ASSET = "asset"


class AnalysisSession(str, enum.Enum):
    PRE_MARKET = "pre_market"
    INTRADAY = "intraday"
    POST_MARKET = "post_market"
    DAILY = "daily"
    WEEKLY = "weekly"


class CommentarySource(str, enum.Enum):
    HUMAN = "human"
    AI = "ai"
    IMPORT = "import"
    SYSTEM = "system"


class InformationType(str, enum.Enum):
    NEWS = "news"
    ANNOUNCEMENT = "announcement"
    RESEARCH = "research"
    MACRO = "macro"
    EVENT = "event"


class TradePlanAction(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class TradePlanLogic(str, enum.Enum):
    AND = "and"
    OR = "or"


class TradePlanStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    PARTIALLY_EXECUTED = "partially_executed"
    EXECUTED = "executed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TradePlanReviewOutcome(str, enum.Enum):
    PROFITABLE = "profitable"
    UNPROFITABLE = "unprofitable"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"


def asset_identity(category: AssetCategory | str, symbol: str) -> str:
    category_value = (
        category.value
        if isinstance(category, AssetCategory)
        else str(category).lower()
    )
    canonical = f"{category_value}:{symbol.strip().upper()}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


class TradeType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


class MarketScope(Base):
    __tablename__ = "market_scopes"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    scope_type: Mapped[MarketScopeType] = mapped_column(
        Enum(MarketScopeType), index=True
    )
    parent_code: Mapped[str | None] = mapped_column(
        ForeignKey("market_scopes.code", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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
    Column("favorite_since", Date, nullable=True, default=date.today),
    Column("favorite_price", Numeric(20, 6), nullable=True),
)

information_market_scopes = Table(
    "information_market_scopes",
    Base.metadata,
    Column(
        "information_id",
        String(36),
        ForeignKey("information.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "market_scope_code",
        String(128),
        ForeignKey("market_scopes.code", ondelete="RESTRICT"),
        primary_key=True,
    ),
)

information_assets = Table(
    "information_assets",
    Base.metadata,
    Column(
        "information_id",
        String(36),
        ForeignKey("information.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "asset_symbol",
        String(32),
        ForeignKey("assets.symbol", ondelete="CASCADE"),
        primary_key=True,
    ),
)

commentary_information = Table(
    "commentary_information",
    Base.metadata,
    Column(
        "commentary_id",
        String(36),
        ForeignKey("commentaries.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "information_id",
        String(36),
        ForeignKey("information.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Tag(Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    assets: Mapped[list["Asset"]] = relationship(
        secondary=asset_tags,
        back_populates="tags",
    )


class Asset(Base):
    __tablename__ = "assets"

    key: Mapped[str] = mapped_column("symbol", String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column("market_symbol", String(32), index=True)
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
    favorite_since: Mapped[date | None] = mapped_column(Date, default=date.today)
    favorite_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
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


class AssetSearchIndex(Base):
    """Lightweight, provider-fed document used by all interactive asset search."""

    __tablename__ = "asset_search_index"

    key: Mapped[str] = mapped_column("symbol", String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column("market_symbol", String(32), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[AssetCategory] = mapped_column(
        Enum(AssetCategory, native_enum=False), index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    provider_id: Mapped[str | None] = mapped_column(String(64))
    aliases: Mapped[str] = mapped_column(Text, default="[]")
    default_tags: Mapped[str] = mapped_column(Text, default="[]")
    pinyin_full: Mapped[str] = mapped_column(Text, default="")
    pinyin_initials: Mapped[str] = mapped_column(Text, default="")
    search_text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("asset_symbol", "trade_date", name="uq_market_bar_asset_date"),
        Index("ix_market_bars_asset_date", "asset_symbol", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_key: Mapped[str] = mapped_column(
        "asset_symbol",
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
    initial_capital: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    investment_style: Mapped[str | None] = mapped_column(String(64))
    is_owned: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    purpose: Mapped[str | None] = mapped_column(Text)
    investment_direction: Mapped[str | None] = mapped_column(Text)
    constraints: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
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


class Commentary(Base):
    __tablename__ = "commentaries"
    __table_args__ = (
        Index("ix_commentaries_subject_date", "subject_type", "trading_date"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    subject_type: Mapped[CommentarySubjectType] = mapped_column(
        Enum(CommentarySubjectType, native_enum=False), index=True
    )
    market_scope_code: Mapped[str | None] = mapped_column(
        ForeignKey("market_scopes.code", ondelete="RESTRICT"), index=True
    )
    portfolio_id: Mapped[str | None] = mapped_column(
        "strategy_id",
        ForeignKey("strategies.id", ondelete="CASCADE"),
        index=True,
    )
    asset_key: Mapped[str | None] = mapped_column(
        "asset_symbol",
        ForeignKey("assets.symbol", ondelete="CASCADE"),
        index=True,
    )
    analysis_session: Mapped[AnalysisSession] = mapped_column(
        "session", Enum(AnalysisSession, native_enum=False), index=True
    )
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSON)
    source: Mapped[CommentarySource] = mapped_column(
        Enum(CommentarySource, native_enum=False), index=True
    )
    source_ref: Mapped[str | None] = mapped_column(Text)
    data_snapshot: Mapped[dict | list | None] = mapped_column(JSON)
    has_outlook: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    has_risk: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    has_trade_plan: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    revises_id: Mapped[str | None] = mapped_column(
        ForeignKey("commentaries.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    asset: Mapped[Asset | None] = relationship()


class Information(Base):
    __tablename__ = "information"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(500), index=True)
    source_name: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSON)
    full_content: Mapped[dict | None] = mapped_column(JSON)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    information_type: Mapped[InformationType] = mapped_column(
        Enum(InformationType, native_enum=False), index=True
    )
    search_context: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    importance: Mapped[int] = mapped_column(Integer, default=3, index=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    market_scopes: Mapped[list[MarketScope]] = relationship(
        secondary=information_market_scopes, lazy="selectin"  # codespell:ignore selectin
    )
    assets: Mapped[list[Asset]] = relationship(
        secondary=information_assets, lazy="selectin"  # codespell:ignore selectin
    )
    commentaries: Mapped[list[Commentary]] = relationship(
        secondary=commentary_information, lazy="selectin"  # codespell:ignore selectin
    )


class TradePlan(Base):
    __tablename__ = "trade_plans"
    __table_args__ = (
        Index("ix_trade_plans_portfolio_status", "strategy_id", "status"),
        Index("ix_trade_plans_asset_status", "asset_symbol", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    portfolio_id: Mapped[str] = mapped_column(
        "strategy_id", ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    asset_key: Mapped[str] = mapped_column(
        "asset_symbol", ForeignKey("assets.symbol", ondelete="CASCADE"), index=True
    )
    action: Mapped[TradePlanAction] = mapped_column(
        Enum(TradePlanAction, native_enum=False)
    )
    logic: Mapped[TradePlanLogic] = mapped_column(
        Enum(TradePlanLogic, native_enum=False), default=TradePlanLogic.AND
    )
    conditions: Mapped[list] = mapped_column(JSON)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    position_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    confirm_days: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    risk_note: Mapped[str | None] = mapped_column(Text)
    source_commentary_id: Mapped[str | None] = mapped_column(
        ForeignKey("commentaries.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[TradePlanStatus] = mapped_column(
        Enum(TradePlanStatus, native_enum=False), index=True, default=TradePlanStatus.DRAFT
    )
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    asset: Mapped[Asset] = relationship()
    review: Mapped["TradePlanReview | None"] = relationship(
        back_populates="plan", cascade="all, delete-orphan", uselist=False
    )
    status_history: Mapped[list["TradePlanStatusEvent"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TradePlanStatusEvent.created_at",
    )


class TradePlanStatusEvent(Base):
    __tablename__ = "trade_plan_status_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("trade_plans.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[TradePlanStatus] = mapped_column(
        Enum(TradePlanStatus, native_enum=False)
    )
    to_status: Mapped[TradePlanStatus] = mapped_column(
        Enum(TradePlanStatus, native_enum=False)
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan: Mapped[TradePlan] = relationship(back_populates="status_history")


class TradePlanReview(Base):
    __tablename__ = "trade_plan_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("trade_plans.id", ondelete="CASCADE"), unique=True, index=True
    )
    outcome: Mapped[TradePlanReviewOutcome] = mapped_column(
        Enum(TradePlanReviewOutcome, native_enum=False)
    )
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSON)
    realized_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan: Mapped[TradePlan] = relationship(back_populates="review")


class OpeningSnapshot(Base):
    __tablename__ = "strategy_opening_snapshots"

    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date)
    legacy_cash: Mapped[Decimal] = mapped_column("cash", Numeric(24, 6), default=Decimal("0"))
    legacy_historical_net_contribution: Mapped[Decimal | None] = mapped_column(
        "historical_net_contribution", Numeric(24, 6)
    )
    legacy_historical_realized_profit: Mapped[Decimal] = mapped_column(
        "historical_realized_profit", Numeric(24, 6), default=Decimal("0")
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
    asset_key: Mapped[str] = mapped_column(
        "asset_symbol",
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

    @property
    def asset_symbol(self) -> str:
        return self.asset.symbol

    @property
    def asset_category(self) -> AssetCategory:
        return self.asset.category


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
    asset_key: Mapped[str | None] = mapped_column(
        "asset_symbol",
        ForeignKey("assets.symbol", ondelete="RESTRICT"), index=True
    )
    position_id: Mapped[str | None] = mapped_column(String(36), index=True)
    trade_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True
    )
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
    trade_plan: Mapped[TradePlan | None] = relationship()

    @property
    def asset_symbol(self) -> str | None:
        return self.asset.symbol if self.asset is not None else None

    @property
    def asset_category(self) -> AssetCategory | None:
        return self.asset.category if self.asset is not None else None


@event.listens_for(Asset, "before_insert")
def set_asset_identity(_, __, asset: Asset) -> None:
    if not asset.key:
        asset.key = asset_identity(asset.category, asset.symbol)
