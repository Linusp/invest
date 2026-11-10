from datetime import datetime, timedelta, timezone

import pytest

from invest_service.services.provider_gate import (
    ProviderGateService,
    ProviderUnavailable,
    next_local_midnight,
)


def test_unknown_provider_is_available(session_factory):
    with session_factory() as session:
        ProviderGateService(session).ensure_available("wind")  # 不应抛错


def test_daily_limit_disables_until_tomorrow(session_factory):
    with session_factory() as session:
        gate = ProviderGateService(session)
        gate.hit_daily_limit("wind", "wind 今日调用已达上限（20/20）")
        with pytest.raises(ProviderUnavailable) as exc:
            gate.ensure_available("wind")
        assert "daily" in str(exc.value)
        assert "次日自动恢复" in str(exc.value)

        row = gate._row("wind")
        until = row.disabled_until.replace(tzinfo=timezone.utc)
        assert until > datetime.now(tz=timezone.utc)
        assert until <= next_local_midnight() + timedelta(seconds=5)


def test_daily_disable_expires(session_factory):
    with session_factory() as session:
        gate = ProviderGateService(session)
        # 手工把恢复时间放到过去，应自动解除。
        gate.disable("wind", "daily", "limit", datetime.now(tz=timezone.utc) - timedelta(minutes=1))
        gate.ensure_available("wind")
        assert gate._row("wind").status == "ok"


def test_balance_error_disables_as_credit(session_factory):
    with session_factory() as session:
        gate = ProviderGateService(session)
        assert gate.note_error("wind", "原因：账户积分余额不足，无法完成当前操作") is True
        with pytest.raises(ProviderUnavailable) as exc:
            gate.ensure_available("wind")
        assert "credit" in str(exc.value)
        assert "充值" in str(exc.value)

        # credit 状态不会因时间自动恢复
        gate.disable("wind", "credit", "余额不足", None)
        with pytest.raises(ProviderUnavailable):
            gate.ensure_available("wind")


def test_non_balance_error_does_not_disable(session_factory):
    with session_factory() as session:
        gate = ProviderGateService(session)
        assert gate.note_error("wind", "网络超时") is False
        gate.ensure_available("wind")


def test_reset_clears_state(session_factory):
    with session_factory() as session:
        gate = ProviderGateService(session)
        gate.disable("wind", "credit", "余额不足")
        gate.reset("wind")
        gate.ensure_available("wind")
        assert gate._row("wind").status == "ok"


def test_status_lists_disabled_providers(session_factory):
    with session_factory() as session:
        gate = ProviderGateService(session)
        gate.disable("wind", "credit", "余额不足")
        rows = {row["provider"]: row for row in gate.status()}
        assert rows["wind"]["status"] == "credit"
        assert "余额不足" in rows["wind"]["reason"]
