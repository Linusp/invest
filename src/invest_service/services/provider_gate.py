"""Provider 熔断与恢复。

规则：
- 当日额度用尽 → ``daily``，到次日 00:00 自动恢复；
- 余额/积分不足、总量额度耗尽 → ``credit``，保持禁用，直到探测成功或手动重置；
- 每次调用前先问闸门，禁用中直接报错，不发网络请求也不计次。
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProviderState

logger = logging.getLogger(__name__)

# 命中这些文案时判定为「余额/额度耗尽」，需要人工充值或探测恢复。
BALANCE_PATTERNS = (
    "积分余额不足",
    "余额不足",
    "欠费",
    "额度已用完",
    "次数已用完",
    "额度不足",
    "quota exceeded",
    "insufficient",
    "credit",
)


class ProviderUnavailable(RuntimeError):
    def __init__(self, provider: str, status: str, reason: str | None):
        self.provider = provider
        self.status = status
        self.reason = reason
        detail = f"{provider} 已被熔断（{status}）"
        if reason:
            detail += f"：{reason}"
        if status == "daily":
            detail += "；次日自动恢复"
        else:
            detail += "；充值后可用 provider_reset 恢复，或等自动探测"
        super().__init__(detail)


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def next_local_midnight() -> datetime:
    local = datetime.now(tz=timezone.utc).astimezone()
    tomorrow = (local + timedelta(days=1)).date()
    return datetime.combine(tomorrow, time.min, tzinfo=local.tzinfo).astimezone(timezone.utc)


class ProviderGateService:
    def __init__(self, session: Session):
        self.session = session

    def _row(self, provider: str) -> ProviderState | None:
        return self.session.get(ProviderState, provider)

    def is_balance_error(self, message: str) -> bool:
        lowered = (message or "").lower()
        return any(pattern.lower() in lowered for pattern in BALANCE_PATTERNS)

    def _expire(self, row: ProviderState) -> bool:
        if row.status == "ok":
            return True
        if row.status != "daily" or row.disabled_until is None:
            return False
        until = row.disabled_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until <= now_utc():
            self.reset(row.provider)
            return True
        return False

    def ensure_available(self, provider: str) -> None:
        row = self._row(provider)
        if row is None or row.status == "ok":
            return
        if self._expire(row):
            return
        raise ProviderUnavailable(provider, row.status, row.reason)

    def disable(
        self,
        provider: str,
        status: str,
        reason: str,
        until: datetime | None = None,
    ) -> None:
        row = self._row(provider)
        if row is None:
            row = ProviderState(provider=provider)
            self.session.add(row)
        row.status = status
        row.reason = reason[:500]
        row.last_error = reason[:1000]
        row.disabled_until = until
        self.session.commit()
        logger.warning("[provider-gate] %s -> %s (%s)", provider, status, reason[:80])

    def hit_daily_limit(self, provider: str, reason: str) -> None:
        self.disable(provider, "daily", reason, next_local_midnight())

    def note_error(self, provider: str, message: str) -> bool:
        """调用失败时调用；余额类错误会熔断并返回 True。"""
        if not self.is_balance_error(message):
            return False
        self.disable(provider, "credit", message)
        return True

    def reset(self, provider: str) -> None:
        row = self._row(provider)
        if row is None:
            return
        row.status = "ok"
        row.reason = None
        row.last_error = None
        row.disabled_until = None
        self.session.commit()
        logger.info("[provider-gate] %s reset", provider)

    def status(self) -> list[dict]:
        rows = list(self.session.scalars(select(ProviderState)))
        return [
            {
                "provider": row.provider,
                "status": row.status,
                "reason": row.reason,
                "disabled_until": row.disabled_until.isoformat() if row.disabled_until else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
