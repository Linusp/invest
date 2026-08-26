from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ConditionEvaluation:
    type: str
    matched: bool
    actual: Decimal | None
    expected: Any
    reason: str


@dataclass(frozen=True)
class PlanEvaluation:
    matched: bool
    streak: int
    conditions: list[ConditionEvaluation]
    reason: str


def evaluate_plan(plan: dict[str, Any], bars: list[dict[str, Any]], as_of: date) -> PlanEvaluation:
    ordered = sorted(
        (bar for bar in bars if bar["trade_date"] <= as_of),
        key=lambda bar: bar["trade_date"],
    )
    if not ordered:
        return PlanEvaluation(False, 0, [], "no market bar for evaluation date")
    conditions = plan.get("conditions", [])
    logic = plan.get("logic", "and")
    confirm_days = int(plan.get("confirm_days", 1))
    latest = ordered[-1]
    latest_results = [_evaluate_condition(condition, latest) for condition in conditions]
    if any(item.reason.startswith("unsupported") for item in latest_results):
        return PlanEvaluation(False, 0, latest_results, "unsupported condition type")
    streak = 0
    for bar in reversed(ordered):
        results = [_evaluate_condition(condition, bar) for condition in conditions]
        if _combine(results, logic):
            streak += 1
        else:
            break
    matched = streak >= confirm_days
    reason = "conditions met" if matched else f"conditions met for {streak}/{confirm_days} days"
    return PlanEvaluation(matched, streak, latest_results, reason)


def _combine(results: list[ConditionEvaluation], logic: str) -> bool:
    if not results or any(item.reason.startswith("unsupported") for item in results):
        return False
    return (
        any(item.matched for item in results)
        if logic == "or"
        else all(item.matched for item in results)
    )


def _evaluate_condition(condition: dict[str, Any], bar: dict[str, Any]) -> ConditionEvaluation:
    condition_type = condition.get("type", "")
    field, operator = {
        "price_lte": ("close", "lte"),
        "price_gte": ("close", "gte"),
        "change_percent_lte": ("change_percent", "lte"),
        "change_percent_gte": ("change_percent", "gte"),
        "volume_lte": ("volume", "lte"),
        "volume_gte": ("volume", "gte"),
        "amount_lte": ("amount", "lte"),
        "amount_gte": ("amount", "gte"),
    }.get(condition_type, (None, None))
    expected = condition.get("value")
    if field is None:
        return ConditionEvaluation(
            condition_type, False, None, expected, "unsupported condition type"
        )
    actual = bar.get(field)
    if actual is None:
        return ConditionEvaluation(condition_type, False, None, expected, f"missing {field}")
    expected_decimal = Decimal(str(expected))
    matched = actual <= expected_decimal if operator == "lte" else actual >= expected_decimal
    return ConditionEvaluation(
        condition_type,
        matched,
        actual,
        expected_decimal,
        f"{actual} {'<=' if operator == 'lte' else '>='} {expected_decimal}",
    )
