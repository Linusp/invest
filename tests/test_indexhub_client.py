import json

import httpx
import pytest

from invest_service.providers.base import ProviderError
from invest_service.providers.indexhub import IndexHubClient

OK = {"success": True, "code": 0, "message": "success", "data": {"data": [{"trdCode": "510300"}]}}


def _client(payload=OK, status=200) -> IndexHubClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return IndexHubClient("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_get_sends_auth_headers_and_unwraps_data():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["caller"] = request.headers.get("x-caller-type")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=OK)

    client = IndexHubClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    data = client.get("/skill/v3/etf/detail", {"fundCodes": "510300,159915"})
    assert data["data"][0]["trdCode"] == "510300"
    assert seen["auth"] == "Bearer k"
    assert seen["caller"] == "external"
    assert "fundCodes=510300%2C159915" in seen["url"]


def test_post_sends_json_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK)

    client = IndexHubClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.post("/skill/v1/search/etf", {"keyword": "沪深300"})
    assert captured["body"] == {"keyword": "沪深300"}


def test_business_error_raises():
    payload = {"success": False, "code": 500, "message": "系统异常！"}
    with pytest.raises(ProviderError) as exc:
        _client(payload).get("/skill/v1/x", {})
    assert "系统异常" in str(exc.value)


def test_401_raises():
    with pytest.raises(ProviderError) as exc:
        _client(status=401).get("/skill/v1/x", {})
    assert "鉴权失败" in str(exc.value)


def test_429_mentions_quota():
    with pytest.raises(ProviderError) as exc:
        _client(status=429).get("/skill/v1/x", {})
    assert "额度" in str(exc.value)
