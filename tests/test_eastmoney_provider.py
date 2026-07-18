import httpx

from invest_service.providers.eastmoney import EastMoneyProvider


def test_default_client_does_not_inherit_host_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://broken.invalid:8080")
    provider = EastMoneyProvider("token")
    assert provider.client._mounts == {}
    assert isinstance(provider.client._transport, httpx.HTTPTransport)
    provider.client.close()
