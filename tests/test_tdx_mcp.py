import json

import httpx
import pytest

from invest_service.providers.base import ProviderError
from invest_service.providers.tdx_mcp import TdxMcpClient, to_setcode


def _client(payload=None, status=200, calls=None) -> TdxMcpClient:
    payload = payload or {"data": {"Close": [1439.0]}}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append((body.get("method"), request.headers.get("mcp-session-id")))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {}},
                headers={"mcp-session-id": "sess-1"},
            )
        if body.get("method") == "notifications/initialized":
            return httpx.Response(200, json={})
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }
        return httpx.Response(
            200,
            text=f"event: message\ndata: {json.dumps(envelope)}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    return TdxMcpClient("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_setcode_inference():
    assert to_setcode("600519.SH") == "1"
    assert to_setcode("000001.SZ") == "0"
    assert to_setcode("430047.BJ") == "0"


def test_call_initializes_session_and_reuses_it():
    calls = []
    client = _client(calls=calls)
    data = client.call("tdx_quotes", {"code": "600519", "setcode": "1"})
    assert data["data"]["Close"] == [1439.0]
    client.call("tdx_quotes", {"code": "600519", "setcode": "1"})
    assert calls[0][0] == "initialize"
    # 后续两次调用都应带同一个 session
    assert calls[1] == ("notifications/initialized", "sess-1")
    assert calls[2] == ("tools/call", "sess-1")
    assert calls[3] == ("tools/call", "sess-1")


def test_401_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = TdxMcpClient("bad", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        client.call("tdx_quotes", {})
    assert "鉴权失败" in str(exc.value)


def test_tool_error_surfaces_message():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return httpx.Response(200, json={}, headers={"mcp-session-id": "s"})
        if body.get("method") == "notifications/initialized":
            return httpx.Response(200, json={})
        envelope = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"isError": True, "content": [{"type": "text", "text": "积分不足"}]},
        }
        return httpx.Response(200, json=envelope)

    client = TdxMcpClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        client.call("tdx_quotes", {})
    assert "积分不足" in str(exc.value)
