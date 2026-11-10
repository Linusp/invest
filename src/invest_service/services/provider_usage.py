"""外部 provider 的调用额度记账。

按「provider + 自然日」累计真实调用次数（缓存命中不计），用于：
- 在接近每日上限时拒绝新调用，避免额度被无声耗尽；
- 通过 REST/MCP 查看当天与近几天的消耗。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProviderUsage


class ProviderUsageService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def today() -> date:
        return datetime.now(tz=timezone.utc).astimezone().date()

    def count(self, provider: str, day: date | None = None) -> int:
        row = self.session.scalar(
            select(ProviderUsage).where(
                ProviderUsage.provider == provider,
                ProviderUsage.day == (day or self.today()),
            )
        )
        return row.calls if row else 0

    def record(self, provider: str, calls: int = 1) -> int:
        day = self.today()
        row = self.session.scalar(
            select(ProviderUsage).where(
                ProviderUsage.provider == provider, ProviderUsage.day == day
            )
        )
        if row is None:
            row = ProviderUsage(provider=provider, day=day, calls=0)
            self.session.add(row)
        row.calls += calls
        self.session.commit()
        return row.calls

    def ensure_capacity(self, provider: str, limit: int) -> None:
        """超限时抛 ValueError，由调用方转成明确的业务错误。"""
        if limit <= 0:
            return
        used = self.count(provider)
        if used >= limit:
            raise ValueError(f"{provider} 今日调用已达上限（{used}/{limit}）")

    def recent(self, days: int = 7) -> list[dict]:
        since = self.today() - timedelta(days=max(days - 1, 0))
        rows = self.session.scalars(
            select(ProviderUsage)
            .where(ProviderUsage.day >= since)
            .order_by(ProviderUsage.day.desc(), ProviderUsage.provider)
        )
        return [
            {"provider": row.provider, "day": row.day.isoformat(), "calls": row.calls}
            for row in rows
        ]
