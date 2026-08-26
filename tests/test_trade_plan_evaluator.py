from datetime import date
from decimal import Decimal

from invest_service.services.trade_plan_evaluator import evaluate_plan


def _bar(day, close="95", change_percent="-3", volume="1000", amount="50000"):
    return {
        "trade_date": date.fromisoformat(day),
        "close": Decimal(close),
        "change_percent": Decimal(change_percent),
        "volume": Decimal(volume),
        "amount": Decimal(amount),
    }


def test_evaluator_supports_and_or_and_confirm_days():
    plan = {
        "logic": "and",
        "confirm_days": 2,
        "conditions": [
            {"type": "price_lte", "value": "100"},
            {"type": "change_percent_lte", "value": "-2"},
        ],
    }
    result = evaluate_plan(
        plan,
        [_bar("2026-08-25"), _bar("2026-08-26")],
        as_of=date(2026, 8, 26),
    )
    assert result.matched is True
    assert result.streak == 2
    assert all(item.matched for item in result.conditions)

    or_result = evaluate_plan(
        {**plan, "logic": "or", "confirm_days": 1},
        [_bar("2026-08-26", close="110", change_percent="-3")],
        as_of=date(2026, 8, 26),
    )
    assert or_result.matched is True


def test_evaluator_reports_insufficient_streak_and_unsupported_condition():
    result = evaluate_plan(
        {
            "logic": "and",
            "confirm_days": 2,
            "conditions": [
                {"type": "volume_gte", "value": "2000"},
                {"type": "unknown", "value": 1},
            ],
        },
        [_bar("2026-08-26")],
        as_of=date(2026, 8, 26),
    )
    assert result.matched is False
    assert result.streak == 0
    assert "unsupported" in result.reason
