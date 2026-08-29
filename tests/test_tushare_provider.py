import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from invest_service.config import Settings
from invest_service.models import AssetCategory
from invest_service.providers import (
    AkshareFallbackProvider,
    EastMoneyProvider,
    IndexFallbackProvider,
    IwencaiProvider,
    PrioritizedMarketProvider,
    ProviderAsset,
    ProviderError,
    TushareProvider,
    make_market_provider,
)


def _response(fields: str, items: list[list[object]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"code": 0, "msg": None, "data": {"fields": fields.split(","), "items": items}},
    )


def test_searches_tushare_catalogs_and_caches_them():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        api_name = body["api_name"]
        calls.append(api_name)
        if api_name == "stock_basic":
            return _response(
                body["fields"],
                [["600000.SH", "600000", "浦发银行", "银行", "主板"]],
            )
        if api_name == "namechange":
            return _response(
                body["fields"],
                [["600000.SH", "浦东发展银行", "19991110", "20101231"]],
            )
        if api_name == "etf_basic":
            return _response(
                body["fields"],
                [["510300.SH", "沪深300ETF", "300ETF"]],
            )
        market = body["params"]["market"]
        items = (
            [["000300.SH", "沪深300", market]]
            if market == "CSI"
            else []
        )
        return _response(body["fields"], items)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TushareProvider("token", client=client)

    matches = provider.search("300")
    assert [(item.symbol, item.category) for item in matches] == [
        ("510300.SH", AssetCategory.ETF),
        ("000300.SH", AssetCategory.INDEX),
    ]
    assert calls == [
        "stock_basic",
        "namechange",
        "etf_basic",
        "index_basic",
        "index_basic",
        "index_basic",
    ]

    stock = provider.search("浦发", category=AssetCategory.STOCK)[0]
    assert stock.symbol == "600000.SH"
    assert stock.default_tags == ("银行",)
    assert stock.aliases == ("浦东发展银行",)
    assert calls.count("stock_basic") == 1


@pytest.mark.parametrize(
    ("category", "expected_api"),
    [
        (AssetCategory.STOCK, "daily"),
        (AssetCategory.ETF, "fund_daily"),
        (AssetCategory.INDEX, "index_daily"),
    ],
)
def test_history_uses_category_api_and_normalizes_rows(category, expected_api):
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return _response(
            body["fields"],
            [
                [
                    "600000.SH",
                    "20260710",
                    10,
                    12,
                    9,
                    11,
                    10,
                    1,
                    10,
                    100,
                    123.456,
                ],
                [
                    "600000.SH",
                    "20260709",
                    9,
                    11,
                    8,
                    10,
                    9,
                    1,
                    11.11,
                    90,
                    100,
                ],
            ],
        )

    provider = TushareProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    asset = ProviderAsset(
        symbol="600000.SH",
        code="600000",
        name="测试标的",
        category=category,
        provider_id="1.600000",
    )

    bars = provider.history(asset, date(2026, 7, 1), date(2026, 7, 10))

    assert requests[0]["api_name"] == expected_api
    assert requests[0]["params"] == {
        "ts_code": "600000.SH",
        "start_date": "20260701",
        "end_date": "20260710",
    }
    assert [bar.trade_date for bar in bars] == [date(2026, 7, 9), date(2026, 7, 10)]
    assert bars[-1].close == Decimal("11")
    assert bars[-1].volume == Decimal("10000")
    assert bars[-1].amount == Decimal("123456.000")


def test_missing_token_has_actionable_error():
    provider = TushareProvider(None)

    with pytest.raises(ProviderError, match="INVEST_TUSHARE_TOKEN"):
        provider.search("600000", category=AssetCategory.STOCK)


def test_etf_search_falls_back_to_fund_basic_when_specialized_catalog_is_denied():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["api_name"])
        if body["api_name"] == "etf_basic":
            return httpx.Response(
                200,
                json={"code": 2002, "msg": "抱歉，您没有接口(etf_basic)访问权限", "data": None},
            )
        return _response(
            body["fields"],
            [
                ["510300.SH", "沪深300ETF", "股票型", "契约型开放式", "E"],
                ["501050.SH", "50AH优选LOF", "股票型", "契约型开放式", "E"],
            ],
        )

    provider = TushareProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    matches = provider.search("300", category=AssetCategory.ETF)

    assert [item.symbol for item in matches] == ["510300.SH"]
    assert calls == ["etf_basic", "fund_basic"]


def test_all_category_search_keeps_results_from_available_catalogs():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["api_name"] in {"etf_basic", "fund_basic"}:
            return httpx.Response(
                200,
                json={"code": 2002, "msg": "没有接口访问权限", "data": None},
            )
        if body["api_name"] == "stock_basic":
            return _response(body["fields"], [["600000.SH", "600000", "浦发银行"]])
        return _response(body["fields"], [])

    provider = TushareProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    matches = provider.search("浦发")

    assert [item.symbol for item in matches] == ["600000.SH"]


def test_factory_defaults_to_free_first_with_tushare_last():
    settings = Settings(
        market_provider="tushare",
        tushare_token="token",
        iwencai_api_key=None,
        auto_update_enabled=False,
    )

    provider = make_market_provider(settings)

    assert isinstance(provider, PrioritizedMarketProvider)
    assert [type(item) for item in provider.search_providers] == [
        EastMoneyProvider,
        AkshareFallbackProvider,
        TushareProvider,
    ]
    assert [type(item) for item in provider.history_providers[AssetCategory.STOCK]] == [
        AkshareFallbackProvider,
        EastMoneyProvider,
        TushareProvider,
    ]
    assert [type(item) for item in provider.history_providers[AssetCategory.INDEX]] == [
        AkshareFallbackProvider,
        TushareProvider,
    ]
    assert [type(item) for item in provider.history_providers[AssetCategory.ETF]] == [
        AkshareFallbackProvider,
        TushareProvider,
    ]
    assert provider.history_providers[AssetCategory.STOCK][-1].token == "token"


def test_factory_can_keep_configured_provider_first_order():
    settings = Settings(
        market_provider="tushare",
        market_provider_order="configured_first",
        tushare_token="token",
        iwencai_api_key=None,
        auto_update_enabled=False,
    )

    provider = make_market_provider(settings)

    assert isinstance(provider, IndexFallbackProvider)
    assert isinstance(provider.primary, TushareProvider)


def test_factory_places_iwencai_before_paid_tushare_history():
    provider = make_market_provider(
        Settings(
            market_provider="tushare",
            tushare_token="token",
            iwencai_api_key="key",
            auto_update_enabled=False,
        )
    )

    assert isinstance(provider, PrioritizedMarketProvider)
    assert [type(item) for item in provider.search_providers][-2:] == [
        IwencaiProvider,
        TushareProvider,
    ]
    for category in AssetCategory:
        history_types = [type(item) for item in provider.history_providers[category]]
        assert history_types[-2:] == [IwencaiProvider, TushareProvider]
