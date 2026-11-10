import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from invest_service.config import Settings
from invest_service.models import AssetCategory
from invest_service.providers import ProviderAsset
from invest_service.providers.base import ProviderError
from invest_service.providers.factory import make_market_provider
from invest_service.providers.fallback import PrioritizedMarketProvider
from invest_service.providers.wind import WindMarketProvider, WindMcpClient, WindMcpError

KLINE = {
    "data": {
        "columns": [
            {"name": "TIME", "type": "string"},
            {"name": "OPEN", "type": "string"},
            {"name": "MATCH", "type": "string"},
            {"name": "HIGH", "type": "string"},
            {"name": "LOW", "type": "string"},
            {"name": "TURNOVER", "type": "string"},
            {"name": "VOLUME", "type": "string"},
        ],
        "rows": [
            ["2026-11-03T00:00:00.000+08:00", "1410.00", "1439.10", "1447.00", "1395.02",
             "11849258015", "8269122"],
            ["2026-11-04T00:00:00.000+08:00", "1430.00", "1450.00", "1460.00", "1420.00",
             "1000", "700"],
        ],
    }
}


def _client(payload=KLINE, status=200) -> WindMcpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps({"jsonrpc": "2.0", "id": 1,
                           "result": {"content": [{"type": "text",
                                                   "text": json.dumps(payload)}]}})
        return httpx.Response(status, text=f"event: message\ndata: {body}")

    return WindMcpClient("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def _asset(category=AssetCategory.STOCK) -> ProviderAsset:
    return ProviderAsset("600519.SH", "600519", "贵州茅台", category, "600519.SH")


def test_history_parses_columns_and_derives_previous_close():
    provider = WindMarketProvider("test-key", client=_client())
    bars = provider.history(_asset(), date(2026, 11, 1), date(2026, 11, 10))

    assert [b.trade_date for b in bars] == [date(2026, 11, 3), date(2026, 11, 4)]
    assert bars[0].close == Decimal("1439.10")
    assert bars[0].previous_close is None
    assert bars[1].previous_close == Decimal("1439.10")
    assert bars[1].change == Decimal("10.90")
    assert bars[1].volume == Decimal("700")
    assert bars[0].source == "wind"


def test_history_filters_out_of_range_dates():
    provider = WindMarketProvider("test-key", client=_client())
    bars = provider.history(_asset(), date(2026, 11, 4), date(2026, 11, 10))
    assert [b.trade_date for b in bars] == [date(2026, 11, 4)]


def test_history_rejects_unknown_category():
    provider = WindMarketProvider("test-key", client=_client())
    asset = ProviderAsset("X", "X", "X", AssetCategory.STOCK, "X")
    object.__setattr__(asset, "category", "unexpected")
    assert provider.history(asset, date(2026, 11, 1), date(2026, 11, 10)) == []


def test_401_raises_provider_error():
    provider = WindMarketProvider("test-key", client=_client(status=401))
    with pytest.raises(ProviderError):
        provider.history(_asset(), date(2026, 11, 1), date(2026, 11, 10))


def test_client_rejects_malformed_sse():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not an sse response")

    client = WindMcpClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(WindMcpError):
        client.call("stock", "get_stock_kline", {})


def test_factory_orders_providers_by_config():
    settings = Settings(
        environment="test",
        database_url="sqlite://",
        auto_update_enabled=False,
        market_provider="tushare",
        market_provider_order="free_first",
        wind_api_key="wind-key",
        iwencai_api_key="iwencai-key",
        provider_priority="wind,akshare,tushare,iwencai",
    )
    provider = make_market_provider(settings)
    assert isinstance(provider, PrioritizedMarketProvider)
    chain = [p.name for p in provider.history_providers[AssetCategory.STOCK]]
    assert chain == ["wind", "akshare", "tushare", "iwencai"]


def test_factory_drops_wind_without_key():
    settings = Settings(
        environment="test",
        database_url="sqlite://",
        auto_update_enabled=False,
        provider_priority="wind,tushare",
    )
    provider = make_market_provider(settings)
    chain = [p.name for p in provider.history_providers[AssetCategory.STOCK]]
    assert "wind" not in chain
