from datetime import date
from decimal import Decimal

from invest_service.models import AssetCategory
from invest_service.providers import (
    PrioritizedMarketProvider,
    ProviderAsset,
    ProviderBar,
    ProviderError,
)

ASSET = ProviderAsset(
    symbol="600000.SH",
    code="600000",
    name="浦发银行",
    category=AssetCategory.STOCK,
    provider_id="600000.SH",
)
BAR = ProviderBar(
    trade_date=date(2026, 8, 24),
    open=Decimal("10"),
    high=Decimal("11"),
    low=Decimal("9"),
    close=Decimal("10.5"),
    previous_close=Decimal("10"),
    change=Decimal("0.5"),
    change_percent=Decimal("5"),
    volume=Decimal("100"),
    amount=Decimal("1000"),
)


class RecordingProvider:
    def __init__(self, name, *, search_result=None, history_result=None, error=None):
        self.name = name
        self.search_result = search_result
        self.history_result = history_result
        self.error = error
        self.calls = []

    def search(self, query, limit=15, category=None):
        self.calls.append(("search", query, category))
        if self.error:
            raise ProviderError(self.error)
        return self.search_result or []

    def history(self, asset, start_date, end_date):
        self.calls.append(("history", asset.symbol))
        if self.error:
            raise ProviderError(self.error)
        return self.history_result or []


def _chain(free, paid):
    return PrioritizedMarketProvider(
        [free, paid],
        {AssetCategory.STOCK: [free, paid]},
    )


def test_free_history_result_does_not_call_paid_fallback():
    free = RecordingProvider("free", history_result=[BAR])
    paid = RecordingProvider("tushare", history_result=[BAR])

    bars = _chain(free, paid).history(ASSET, date(2026, 8, 1), date(2026, 8, 24))

    assert bars == [BAR]
    assert free.calls == [("history", "600000.SH")]
    assert paid.calls == []


def test_empty_or_failed_free_history_uses_paid_fallback():
    for free in (
        RecordingProvider("free", history_result=[]),
        RecordingProvider("free", error="unavailable"),
    ):
        paid = RecordingProvider("tushare", history_result=[BAR])

        bars = _chain(free, paid).history(
            ASSET,
            date(2026, 8, 1),
            date(2026, 8, 24),
        )

        assert bars == [BAR]
        assert paid.calls == [("history", "600000.SH")]


def test_search_stops_at_first_free_result_and_falls_back_on_empty():
    free = RecordingProvider("free", search_result=[ASSET])
    paid = RecordingProvider("tushare", search_result=[ASSET])
    provider = _chain(free, paid)

    assert provider.search("600000") == [ASSET]
    assert paid.calls == []

    free.search_result = []
    assert provider.search("浦发") == [ASSET]
    assert paid.calls == [("search", "浦发", None)]
