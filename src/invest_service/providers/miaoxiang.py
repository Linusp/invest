"""东方财富妙想（MX）MCP 客户端。

直连 ``https://mxapi.eastmoney.com/mxds/mcp``（Streamable HTTP，静态 ``em_api_key``）。
服务无状态；11 个工具全部只接收自然语言 ``query``，底层是 Choice 数据库。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .base import ProviderError
from .mcp_wire import parse_json_or_sse


class MxMcpError(ProviderError):
    """妙想 MCP 调用失败。"""


class MxMcpClient:
    ENDPOINT = "https://mxapi.eastmoney.com/mxds/mcp"

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
        self._initialized = False

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "em_api_key": self.api_key,
            "User-Agent": "InvestService/0.1",
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(
                self.ENDPOINT, json=payload, headers=self._headers(), timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise MxMcpError(f"妙想请求失败: {exc}") from exc
        if response.status_code == 401:
            raise MxMcpError("妙想鉴权失败（401），请检查 em_api_key")
        if response.status_code == 429:
            raise MxMcpError("妙想触发限流（429），积分或频率超限")
        response.raise_for_status()
        try:
            data = parse_json_or_sse(response.text)
        except ValueError as exc:
            raise MxMcpError(str(exc)) from exc
        if "error" in data:
            raise MxMcpError(f"妙想调用失败: {data['error']}")
        return data

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._next_id += 1
        self._post(
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
        self._initialized = True

    def ping(self) -> None:
        self._ensure_initialized()

    def call(self, tool: str, query: str) -> dict[str, Any]:
        """调用一个工具；所有妙想工具都只接受 ``query``。"""
        if not query.strip():
            raise MxMcpError("query 不能为空")
        self._ensure_initialized()
        self._next_id += 1
        envelope = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": {"query": query}},
            }
        )
        result = envelope.get("result") or {}
        if result.get("isError") is True:
            message = "\n".join(
                block.get("text", "")
                for block in result.get("content") or []
                if isinstance(block, dict)
            )
            raise MxMcpError(message or "妙想工具返回错误")
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
        except ValueError as exc:
            raise MxMcpError(f"妙想返回非 JSON: {raw[:160]}") from exc
