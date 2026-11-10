"""盈米基金 MCP 客户端。

直连 ``https://stargate.yingmi.com/mcp/v2``（Streamable HTTP，静态 ``x-api-key``）。
服务无状态，不需要维护 Mcp-Session-Id；响应可能是纯 JSON，也可能是 SSE。

能力面很宽（71 个工具），invest 只暴露只读且与投研相关的子集，见
``mcp_external`` 里的工具注册。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .base import ProviderError


class YingmiMcpError(ProviderError):
    """盈米 MCP 调用失败。"""


def _parse_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise YingmiMcpError("盈米返回空响应")
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    for line in stripped.splitlines():
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            return json.loads(chunk)
        except ValueError:
            continue
    raise YingmiMcpError(f"盈米返回无法解析: {stripped[:160]}")


class YingmiMcpClient:
    ENDPOINT = "https://stargate.yingmi.com/mcp/v2"

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
            "x-api-key": self.api_key,
            "User-Agent": "InvestService/0.1",
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(
                self.ENDPOINT, json=payload, headers=self._headers(), timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise YingmiMcpError(f"盈米请求失败: {exc}") from exc
        if response.status_code == 401:
            raise YingmiMcpError("盈米鉴权失败（401），请检查 API Key")
        if response.status_code == 429:
            raise YingmiMcpError("盈米触发限流（429）")
        response.raise_for_status()
        data = _parse_payload(response.text)
        if "error" in data:
            raise YingmiMcpError(f"盈米调用失败: {data['error']}")
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

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用一个工具，返回解析后的 JSON（盈米直接返回业务 JSON）。"""
        self._ensure_initialized()
        self._next_id += 1
        envelope = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )
        result = envelope.get("result") or {}
        if result.get("isError") is True:
            message = "\n".join(
                block.get("text", "")
                for block in result.get("content") or []
                if isinstance(block, dict)
            )
            raise YingmiMcpError(message or "盈米工具返回错误")
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
            raise YingmiMcpError(f"盈米返回非 JSON: {raw[:160]}") from exc
