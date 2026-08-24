from datetime import date

import httpx

from invest_service.models import AssetCategory
from invest_service.providers import ProviderAsset
from invest_service.providers.eastmoney import EastMoneyProvider


def test_default_client_does_not_inherit_host_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://broken.invalid:8080")
    provider = EastMoneyProvider("token")
    assert provider.client._mounts == {}
    assert isinstance(provider.client._transport, httpx.HTTPTransport)
    provider.client.close()


def test_history_infers_eastmoney_id_for_existing_tushare_asset():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"klines": []}})

    provider = EastMoneyProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    asset = ProviderAsset(
        symbol="600000.SH",
        code="600000",
        name="浦发银行",
        category=AssetCategory.STOCK,
        provider_id="600000.SH",
    )

    assert provider.history(asset, date(2026, 8, 1), date(2026, 8, 24)) == []
    assert requests[0].url.params["secid"] == "1.600000"
