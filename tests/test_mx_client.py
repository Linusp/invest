import json

import httpx
import pytest

from invest_service.providers.base import ProviderError
from invest_service.providers.miaoxiang import MxMcpClient

PAYLOAD = {"data": {"columns": ["证券代码", "最新价"], "rows": [["600519.SH", "1438.92"]]}}


def _client(payload=PAYLOAD, sse=False) -> MxMcpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }
        if sse:
            return httpx.Response(
                200,
                text=f"event: message\ndata: {json.dumps(envelope)}\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=envelope)

    return MxMcpClient("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_call_initializes_once_and_returns_payload():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["method"])
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if body["method"] == "tools/call":
            assert body["params"]["arguments"] == {"query": "贵州茅台"}
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(PAYLOAD)}]},
        }
        return httpx.Response(200, json=envelope)

    client = MxMcpClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.call("mx_ashare_finance_data", "贵州茅台")
    assert result["data"]["rows"][0][1] == "1438.92"
    client.call("mx_ashare_finance_data", "贵州茅台")
    assert calls == ["initialize", "tools/call", "tools/call"]


def test_call_parses_sse_response():
    result = _client(sse=True).call("mx_fund_finance_data", "005827 净值")
    assert result["data"]["columns"][0] == "证券代码"


def test_empty_query_rejected():
    with pytest.raises(ProviderError):
        _client().call("mx_ashare_finance_data", "  ")


def test_401_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = MxMcpClient("bad", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        client.call("mx_ashare_finance_data", "贵州茅台")
    assert "鉴权失败" in str(exc.value)


def test_tool_error_surfaces_message():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"isError": True, "content": [{"type": "text", "text": "积分不足"}]},
        }
        return httpx.Response(200, json=envelope)

    client = MxMcpClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        client.call("mx_ashare_finance_data", "贵州茅台")
    assert "积分不足" in str(exc.value)
