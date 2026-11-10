from datetime import date
from decimal import Decimal

from invest_service.config import Settings
from invest_service.models import AssetCategory
from invest_service.providers.akshare_fund import AkshareFundProvider
from invest_service.providers.base import ProviderAsset
from invest_service.providers.factory import make_market_provider


class FakeAkshare:
    def __init__(self):
        self.calls = []

    def fund_name_em(self):
        self.calls.append("fund_name_em")
        return [
            {"基金代码": "005827", "基金简称": "易方达蓝筹精选混合", "基金类型": "混合型"},
            {"基金代码": "110011", "基金简称": "易方达中小盘混合", "基金类型": "混合型"},
        ]

    def fund_open_fund_info_em(self, symbol, indicator):
        self.calls.append((symbol, indicator))
        assert indicator == "单位净值走势"
        return [
            {"净值日期": "2026-11-05", "单位净值": "1.4164", "日增长率": "1.11"},
            {"净值日期": "2026-11-06", "单位净值": "1.4023", "日增长率": "-1.00"},
            {"净值日期": "2026-11-09", "单位净值": "1.3993", "日增长率": "-0.21"},
        ]


def _provider() -> AkshareFundProvider:
    return AkshareFundProvider(api=FakeAkshare())


def test_catalog_maps_funds_to_of_symbols():
    assets = _provider().catalog()
    assert [a.symbol for a in assets] == ["005827.OF", "110011.OF"]
    assert all(a.category is AssetCategory.FUND for a in assets)
    assert assets[0].default_tags == ("场外基金",)


def test_search_matches_code_and_name():
    provider = _provider()
    assert [a.code for a in provider.search("0058")] == ["005827"]
    assert [a.code for a in provider.search("蓝筹")] == ["005827"]
    assert provider.search("查询", category=AssetCategory.STOCK) == []


def test_history_parses_nav_and_derives_previous_close():
    provider = _provider()
    asset = ProviderAsset("005827.OF", "005827", "易方达蓝筹精选混合", AssetCategory.FUND, "005827")
    bars = provider.history(asset, date(2026, 11, 1), date(2026, 11, 10))

    assert [bar.trade_date for bar in bars] == [
        date(2026, 11, 5),
        date(2026, 11, 6),
        date(2026, 11, 9),
    ]
    assert bars[0].close == Decimal("1.4164")
    assert bars[0].previous_close is None
    assert bars[1].previous_close == Decimal("1.4164")
    assert bars[1].change == Decimal("-0.0141")
    assert bars[1].change_percent == Decimal("-1.00")
    assert bars[2].volume is None and bars[2].amount is None
    assert bars[0].source == "akshare"


def test_history_filters_out_of_range():
    provider = _provider()
    asset = ProviderAsset("005827.OF", "005827", "x", AssetCategory.FUND, "005827")
    bars = provider.history(asset, date(2026, 11, 6), date(2026, 11, 10))
    assert [bar.trade_date for bar in bars] == [date(2026, 11, 6), date(2026, 11, 9)]


def test_factory_puts_fund_provider_first_in_fund_chain():
    provider = make_market_provider(
        Settings(
            environment="test",
            database_url="sqlite://",
            auto_update_enabled=False,
        )
    )
    chain = provider.history_providers[AssetCategory.FUND]
    assert chain[0].name == "akshare-fund"
