"""MCP 工具的输出模型。

用途：让 ``tools/list`` 的 ``outputSchema`` 具备真实字段，而不是泛化的
``{result: object}``。模型刻意保持宽松（字段大多可选、``extra="allow"``），
只承诺「至少包含这些字段」，不限制上游继续加字段。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class OutModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssetOut(OutModel):
    symbol: str | None = None
    code: str | None = None
    name: str | None = None
    category: str | None = None
    currency: str | None = None
    provider_id: str | None = None
    is_favorite: bool | None = None
    tags: list[dict[str, Any]] | None = None


class TagOut(OutModel):
    name: str | None = None
    position: int | None = None
    is_pinned: bool | None = None
    asset_count: int | None = None


class AssetTagOut(OutModel):
    name: str | None = None
    favorite_since: str | None = None
    favorite_price: float | str | None = None


class BarOut(OutModel):
    trade_date: str | None = None
    open: float | str | None = None
    high: float | str | None = None
    low: float | str | None = None
    close: float | str | None = None
    previous_close: float | str | None = None
    change: float | str | None = None
    change_percent: float | str | None = None
    volume: float | str | None = None
    amount: float | str | None = None
    source: str | None = None


class PositionOut(OutModel):
    asset: AssetOut | None = None
    quantity: float | str | None = None
    average_cost: float | str | None = None
    cost_basis: float | str | None = None
    latest_price: float | str | None = None
    latest_price_date: str | None = None
    market_value: float | str | None = None
    realized_profit: float | str | None = None
    unrealized_profit: float | str | None = None


class TradeOut(OutModel):
    id: str | None = None
    trade_type: str | None = None
    trade_date: str | None = None
    quantity: float | str | None = None
    price: float | str | None = None
    fee: float | str | None = None
    amount: float | str | None = None
    notes: str | None = None


class PortfolioSummaryOut(OutModel):
    total_value: float | str | None = None
    market_value: float | str | None = None
    cash_balance: float | str | None = None
    net_contribution: float | str | None = None
    total_profit: float | str | None = None
    realized_profit: float | str | None = None
    unrealized_profit: float | str | None = None


class PortfolioOut(OutModel):
    id: str | None = None
    name: str | None = None
    description: str | None = None
    summary: PortfolioSummaryOut | None = None
    positions: list[PositionOut] | None = None
    trades: list[TradeOut] | None = None


class SnapshotOut(OutModel):
    snapshot_date: str | None = None
    cash_balances: list[dict[str, Any]] | None = None
    positions: list[dict[str, Any]] | None = None


class ScopeOut(OutModel):
    code: str | None = None
    name: str | None = None
    scope_type: str | None = None
    parent_code: str | None = None
    description: str | None = None


class CommentaryOut(OutModel):
    id: str | None = None
    subject_type: str | None = None
    subject_code: str | None = None
    title: str | None = None
    content: str | dict[str, Any] | None = None
    created_at: str | None = None


class InformationOut(OutModel):
    id: str | None = None
    title: str | None = None
    url: str | None = None
    source_name: str | None = None
    published_at: str | None = None
    content: str | None = None


class TradePlanOut(OutModel):
    id: str | None = None
    portfolio_id: str | None = None
    asset_symbol: str | None = None
    action: str | None = None
    status: str | None = None
    conditions: list[dict[str, Any]] | None = None
    valid_from: str | None = None
    valid_until: str | None = None


class PlanEventOut(OutModel):
    status: str | None = None
    changed_at: str | None = None
    reason: str | None = None


class PlanReviewOut(OutModel):
    plan_id: str | None = None
    outcome: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None


class SectorFlowRow(OutModel):
    sector_code: str | None = None
    sector_name: str | None = None
    trade_date: str | None = None
    main_net: float | str | None = None
    super_large_net: float | str | None = None
    large_net: float | str | None = None
    mid_net: float | str | None = None
    small_net: float | str | None = None
    change_percent: float | str | None = None
    market_cap: float | str | None = None


class ExchangeRateOut(OutModel):
    currency: str | None = None
    rate: float | str | None = None
    rate_date: str | None = None
    source: str | None = None


class SkillRunOut(OutModel):
    id: int | None = None
    source: str | None = None
    skill: str | None = None
    prompt: str | None = None
    output: str | None = None
    duration_ms: int | None = None
    cache_hit: bool | None = None
    created_at: str | None = None


class ProviderStatusOut(OutModel):
    provider: str | None = None
    status: str | None = None
    reason: str | None = None
    disabled_until: str | None = None
    calls_today: int | None = None


class ProviderResetOut(OutModel):
    provider: str | None = None
    status: str | None = None


class ExternalResult(OutModel):
    """外部数据源的统一返回：原始数据 + 是否命中缓存。"""

    tool: str | None = None
    arguments: dict[str, Any] | None = None
    query: str | None = None
    domain: str | None = None
    data: Any = None
    cached: bool | None = None


class MarketHistoryOut(OutModel):
    symbol: str | None = None
    category: str | None = None
    bars: list[BarOut] | None = None


class DeleteOut(OutModel):
    status: str | None = None
    deleted: bool | None = None
    code: str | None = None
