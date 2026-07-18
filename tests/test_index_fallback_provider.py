from datetime import date
from decimal import Decimal

from invest_service.models import AssetCategory
from invest_service.providers import (
    AkshareFallbackProvider,
    AkshareIndexProvider,
    IndexFallbackProvider,
    ProviderAsset,
    ProviderBar,
    ProviderError,
)

INDEX = ProviderAsset(
    symbol="000300.SH",
    code="000300",
    name="沪深300",
    category=AssetCategory.INDEX,
    provider_id="000300.SH",
)
ETF = ProviderAsset(
    symbol="510300.SH",
    code="510300",
    name="沪深300ETF",
    category=AssetCategory.ETF,
    provider_id="510300.SH",
)


class FakeFrame:
    empty = False

    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


class FakeAkshare:
    def __init__(self):
        self.calls = []

    def stock_zh_index_daily_tx(self, symbol):
        self.calls.append(("tencent", symbol))
        raise RuntimeError("Tencent unavailable")

    def stock_zh_index_daily(self, symbol):
        self.calls.append(("sina", symbol))
        return FakeFrame(
            [
                {
                    "date": "2026-07-10",
                    "open": 4010,
                    "high": 4030,
                    "low": 4000,
                    "close": 4020,
                    "volume": 200,
                },
                {
                    "date": "2026-07-09",
                    "open": 3990,
                    "high": 4010,
                    "low": 3980,
                    "close": 4000,
                    "volume": 100,
                },
            ]
        )


def test_akshare_index_tries_tencent_then_sina_and_normalizes_rows():
    api = FakeAkshare()
    provider = AkshareIndexProvider(api)

    bars = provider.history(INDEX, date(2026, 7, 9), date(2026, 7, 10))

    assert api.calls == [("tencent", "sh000300"), ("sina", "sh000300")]
    assert [bar.trade_date for bar in bars] == [date(2026, 7, 9), date(2026, 7, 10)]
    assert bars[-1].previous_close == Decimal("4000")
    assert bars[-1].change == Decimal("20")
    assert bars[-1].change_percent == Decimal("0.500")
    assert bars[-1].source == "akshare"


class FakeEtfAkshare:
    def __init__(self):
        self.spot_calls = 0

    def fund_etf_category_sina(self, symbol):
        assert symbol == "ETF基金"
        self.spot_calls += 1
        return FakeFrame(
            [
                {"代码": "sh510300", "名称": "沪深300ETF"},
                {"代码": "sz159915", "名称": "创业板ETF"},
            ]
        )

    def fund_etf_spot_em(self):
        raise AssertionError("EastMoney catalog should not run when Sina succeeds")

    def fund_etf_hist_sina(self, symbol):
        assert symbol == "sh510300"
        return FakeFrame(
            [
                {
                    "date": "2026-07-10",
                    "open": 4.1,
                    "high": 4.2,
                    "low": 4.0,
                    "close": 4.15,
                    "volume": 200,
                    "amount": 830000,
                }
            ]
        )

class FakeEtfHistoryProvider:
    def __init__(self):
        self.calls = []

    def history(self, asset, start_date, end_date):
        self.calls.append((asset, start_date, end_date))
        return [
            ProviderBar(
                trade_date=date(2026, 7, 10),
                open=Decimal("4.1"),
                high=Decimal("4.2"),
                low=Decimal("4.0"),
                close=Decimal("4.15"),
                previous_close=Decimal("4.10"),
                change=Decimal("0.05"),
                change_percent=Decimal("1.22"),
                volume=Decimal("200"),
                amount=Decimal("830000"),
                source="eastmoney",
            )
        ]


class FailingEtfHistoryProvider:
    def history(self, asset, start_date, end_date):
        raise ProviderError("EastMoney disconnected")


def test_akshare_etf_search_and_history():
    api = FakeEtfAkshare()
    history_provider = FakeEtfHistoryProvider()
    provider = AkshareFallbackProvider(api, etf_history_provider=history_provider)

    first = provider.search("300", category=AssetCategory.ETF)
    second = provider.search("510300", category=AssetCategory.ETF)
    bars = provider.history(ETF, date(2026, 7, 1), date(2026, 7, 10))

    assert [asset.symbol for asset in first] == ["510300.SH"]
    assert [asset.symbol for asset in second] == ["510300.SH"]
    assert api.spot_calls == 1
    history_asset, history_start, history_end = history_provider.calls[0]
    assert history_asset.provider_id == "1.510300"
    assert history_start == date(2026, 7, 1)
    assert history_end == date(2026, 7, 10)
    assert bars[0].previous_close == Decimal("4.10")
    assert bars[0].change == Decimal("0.05")
    assert bars[0].change_percent == Decimal("1.22")
    assert bars[0].amount == Decimal("830000")
    assert bars[0].source == "eastmoney"


def test_akshare_etf_history_falls_back_from_eastmoney_to_sina():
    provider = AkshareFallbackProvider(
        FakeEtfAkshare(),
        etf_history_provider=FailingEtfHistoryProvider(),
    )

    bars = provider.history(ETF, date(2026, 7, 1), date(2026, 7, 10))

    assert len(bars) == 1
    assert bars[0].trade_date == date(2026, 7, 10)
    assert bars[0].amount == Decimal("830000")
    assert bars[0].source == "akshare"


class PrimaryProvider:
    name = "tushare"

    def search(self, query, limit=15, category=None):
        return [INDEX]

    def history(self, asset, start_date, end_date):
        raise ProviderError("Tushare index_daily rate limited")


class FallbackProvider:
    name = "akshare"

    def __init__(self):
        self.calls = 0

    def history(self, asset, start_date, end_date):
        self.calls += 1
        return [
            ProviderBar(
                trade_date=date(2026, 7, 10),
                open=Decimal("4000"),
                high=Decimal("4030"),
                low=Decimal("3990"),
                close=Decimal("4020"),
                previous_close=Decimal("4000"),
                change=Decimal("20"),
                change_percent=Decimal("0.5"),
                volume=Decimal("100"),
                amount=None,
                source="akshare",
            )
        ]


def test_index_fallback_runs_when_tushare_fails():
    fallback = FallbackProvider()
    provider = IndexFallbackProvider(PrimaryProvider(), fallback)

    bars = provider.history(INDEX, date(2026, 7, 1), date(2026, 7, 10))

    assert fallback.calls == 1
    assert bars[0].source == "akshare"
    assert provider.name == "tushare"


class EtfPrimaryProvider(PrimaryProvider):
    def search(self, query, limit=15, category=None):
        raise ProviderError("Tushare fund_basic denied")


class EtfFallbackProvider(FallbackProvider):
    def search(self, query, limit=15, category=None):
        return [ETF]


def test_etf_fallback_handles_search_and_history():
    fallback = EtfFallbackProvider()
    provider = IndexFallbackProvider(EtfPrimaryProvider(), fallback)

    assets = provider.search("510300", category=AssetCategory.ETF)
    bars = provider.history(ETF, date(2026, 7, 1), date(2026, 7, 10))

    assert assets == [ETF]
    assert bars[0].source == "akshare"
