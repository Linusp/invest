import json

import httpx
import pytest

from invest_service.providers.base import ProviderError
from invest_service.providers.yingmi import YingmiMcpClient, _parse_payload

SEARCH = {"funds": [{"fundCode": "005827", "fundName": "易方达蓝筹精选混合"}], "total": 1}


def _client(payload=SEARCH, sse=True) -> YingmiMcpClient:
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
            text = f"event: message\ndata: {json.dumps(envelope)}\n\n"
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=envelope)

    return YingmiMcpClient("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_payload_accepts_json_and_sse():
    assert _parse_payload('{"a": 1}') == {"a": 1}
    assert _parse_payload('event: message\ndata: {"a": 2}\n\n') == {"a": 2}
    with pytest.raises(Exception):
        _parse_payload("not json")


def test_call_initializes_then_returns_payload():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["method"])
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(SEARCH)}]},
        }
        return httpx.Response(200, json=envelope)

    client = YingmiMcpClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.call("SearchFunds", {"keyword": "易方达"})
    assert result["total"] == 1
    assert calls == ["initialize", "tools/call"]
    # 第二次调用不应重复 initialize
    client.call("SearchFunds", {"keyword": "易方达"})
    assert calls == ["initialize", "tools/call", "tools/call"]


def test_call_parses_sse_response():
    result = _client(sse=True).call("SearchFunds", {"keyword": "x"})
    assert result["funds"][0]["fundCode"] == "005827"


def test_401_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = YingmiMcpClient("bad", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        client.call("SearchFunds", {})
    assert "鉴权失败" in str(exc.value)


def test_tool_error_surfaces_message():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "基金代码不存在"}],
            },
        }
        return httpx.Response(200, json=envelope)

    client = YingmiMcpClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        client.call("GetFundDiagnosis", {"fundCode": "000000"})
    assert "不存在" in str(exc.value)
