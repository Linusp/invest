"""通达信 MCP 客户端（SkillHub 提供的 tdx-finance MCP）。

端点 ``https://testmcp.tdx.com.cn:3001/qclawmcp``，鉴权是普通
``Authorization: Bearer <KEY>``（不是 TdxAiData 的数据服务 key）。

服务有会话：initialize 返回 ``mcp-session-id``，后续请求必须带上。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .base import ProviderError
from .mcp_wire import parse_json_or_sse


class TdxMcpError(ProviderError):
    """通达信 MCP 调用失败。"""


# 标的代码后缀 → 通达信 setcode（1=沪，0=深/北）。
SETCODE = {"SH": "1", "SZ": "0", "BJ": "0"}


def to_setcode(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else "SH"
    return SETCODE.get(suffix, "1")


class TdxMcpClient:
    ENDPOINT = "https://testmcp.tdx.com.cn:3001/qclawmcp"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 90.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)
        self._next_id = 0
        self._session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "InvestService/0.1",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            response = self.client.post(
                self.ENDPOINT, json=payload, headers=self._headers(), timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise TdxMcpError(f"通达信请求失败: {exc}") from exc
        if response.status_code == 401:
            raise TdxMcpError("通达信鉴权失败（401），请检查 TDX API Key")
        if response.status_code == 400 and self._session_id is None:
            raise TdxMcpError(f"通达信会话缺失: {response.text[:160]}")
        return response

    def _ensure_session(self) -> None:
        if self._session_id:
            return
        self._next_id += 1
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "invest-service", "version": "0.1.0"},
                },
            }
        )
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id") or response.headers.get(
            "Mcp-Session-Id"
        )
        if not session_id:
            raise TdxMcpError("通达信 initialize 未返回 mcp-session-id")
        self._session_id = session_id
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_session()
        self._next_id += 1
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )
        response.raise_for_status()
        try:
            envelope = parse_json_or_sse(response.text)
        except ValueError as exc:
            raise TdxMcpError(f"通达信返回无法解析: {response.text[:160]}") from exc
        if "error" in envelope:
            raise TdxMcpError(f"通达信调用失败: {envelope['error']}")
        result = envelope.get("result") or {}
        if result.get("isError") is True:
            message = "\n".join(
                block.get("text", "")
                for block in result.get("content") or []
                if isinstance(block, dict)
            )
            raise TdxMcpError(message or "通达信工具返回错误")
        texts = [
            block.get("text", "")
            for block in result.get("content") or []
            if isinstance(block, dict)
        ]
        raw = "\n".join(texts).strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {"text": raw}
