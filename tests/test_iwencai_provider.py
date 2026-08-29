import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from invest_service.models import AssetCategory
from invest_service.providers import IwencaiProvider, ProviderAsset, ProviderError


def _asset(category: AssetCategory = AssetCategory.STOCK) -> ProviderAsset:
    return ProviderAsset(
        symbol="600000.SH",
        code="600000",
        name="浦发银行",
        category=category,
        provider_id="600000.SH",
    )


def test_history_queries_openapi_and_parses_dated_columns():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "code_count": 1,
                "datas": [
                    {
                        "股票代码": "600000.SH",
                        "股票简称": "浦发银行",
                        "开盘价[20260827]": 9.18,
                        "最高价[20260827]": "9.20",
                        "最低价[20260827]": 8.98,
                        "收盘价[20260827]": "9.07",
                        "前收盘价[20260827]": "9.21",
                        "涨跌[20260827]": -0.14,
                        "涨跌幅[20260827]": -1.520087,
                        "成交量[20260827]": "9.581009E7",
                        "成交额[20260827]": 868496688,
                        "收盘价[20260830]": 9.10,
                    }
                ],
            },
        )

    provider = IwencaiProvider(
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    bars = provider.history(_asset(), date(2026, 8, 1), date(2026, 8, 29))

    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer secret"
    assert requests[0].headers["x-claw-skill-id"] == "hithink-market-query"
    assert len(requests[0].headers["x-claw-trace-id"]) == 64
    payload = json.loads(requests[0].content)
    assert "600000.SH" in payload["query"]
    assert payload["limit"] == "1"
    assert [bar.trade_date for bar in bars] == [date(2026, 8, 27)]
    assert bars[0].close == Decimal("9.07")
    assert bars[0].volume == Decimal("9.581009E7")
    assert bars[0].amount == Decimal("868496688")
    assert bars[0].source == "iwencai"


def test_index_history_allows_missing_volume():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "datas": [{
                    "指数代码": "600000.SH",
                    "开盘价[20260828]": 3950.2,
                    "最高价[20260828]": 3970.3,
                    "最低价[20260828]": 3947.8,
                    "收盘价[20260828]": 3952.18,
                    "前收盘价[20260828]": 3956.57,
                    "涨跌[20260828]": -4.39,
                    "涨跌幅[20260828]": -0.111,
                    "成交额[20260828]": 970365152113,
                }],
            },
        )

    provider = IwencaiProvider(
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    bars = provider.history(
        _asset(AssetCategory.INDEX), date(2026, 8, 28), date(2026, 8, 28)
    )

    assert bars[0].volume is None
    assert bars[0].amount == Decimal("970365152113")


def test_search_is_intentionally_local_only_and_missing_key_is_actionable():
    provider = IwencaiProvider(None)

    assert provider.search("浦发") == []
    with pytest.raises(ProviderError, match="IWENCAI_API_KEY"):
        provider.history(_asset(), date(2026, 8, 1), date(2026, 8, 2))


def test_history_rejects_a_response_for_another_asset():
    provider = IwencaiProvider(
        "secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={"status_code": 0, "datas": [{"股票代码": "000001.SZ"}]},
                )
            )
        ),
    )

    with pytest.raises(ProviderError, match="unexpected asset"):
        provider.history(_asset(), date(2026, 8, 1), date(2026, 8, 2))


def test_catalog_paginates_hk_and_us_stocks_and_normalizes_symbols():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        is_hk = "港股" in payload["query"]
        page = int(payload["page"])
        if is_hk:
            rows = [{"股票代码": "0700.HK", "股票简称": "腾讯控股"}]
            count = 1
        elif page == 1:
            rows = [{"股票代码": "AAPL.O", "股票简称": "苹果"}]
            count = 2
        else:
            rows = [{"股票代码": "BRK.B.N", "股票简称": "伯克希尔B"}]
            count = 2
        return httpx.Response(
            200,
            json={"status_code": 0, "code_count": count, "datas": rows},
        )

    provider = IwencaiProvider(
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        catalog_page_size=1,
    )

    assets = provider.catalog()

    assert [(item.symbol, item.currency) for item in assets] == [
        ("00700.HK", "HKD"),
        ("AAPL.US", "USD"),
        ("BRK.B.US", "USD"),
    ]
    assert assets[0].provider_id == "0700.HK"
    assert assets[0].aliases == ("0700.HK",)
    assert assets[0].default_tags == ("港股",)
    assert assets[1].default_tags == ("美股",)
    assert [(item["page"], item["limit"]) for item in requests] == [
        ("1", "1"),
        ("1", "1"),
        ("2", "1"),
    ]
