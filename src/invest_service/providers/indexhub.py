"""易方达指数直通车（Index Hub）REST 客户端。

官方 skill 包把 base URL 封装在 ``config.py``，实测为::

    https://www.etf.com.cn/api/etf-api-service
    Authorization: Bearer <API_KEY>
    X-Caller-Type: external

它不是 MCP，而是普通 REST；ETF 相关走 ``/skill/v1/*``（POST），
指数详情/估值走 ``/skill/v3/*``（GET）。返回统一包在
``{"success": bool, "code": ..., "message": ..., "data": ...}`` 里。
"""

from __future__ import annotations

from typing import Any

import httpx

from .base import ProviderError


class IndexHubError(ProviderError):
    """指数直通车调用失败。"""


class IndexHubClient:
    BASE = "https://www.etf.com.cn/api/etf-api-service"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Caller-Type": "external",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "InvestService/0.1",
        }

    def _unwrap(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            raise IndexHubError("指数直通车鉴权失败（401），请检查 API Key")
        if response.status_code == 429:
            raise IndexHubError("指数直通车触发限流（429），当日额度可能已用完")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise IndexHubError(f"指数直通车返回非 JSON: {response.text[:160]}") from exc
        if not isinstance(payload, dict):
            raise IndexHubError("指数直通车返回结构异常")
        if payload.get("success") is not True:
            message = payload.get("message") or payload.get("code") or "未知错误"
            raise IndexHubError(f"指数直通车调用失败: {message}")
        return payload.get("data") or {}

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.get(
                f"{self.BASE}{path}", params=params, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise IndexHubError(f"指数直通车请求失败: {exc}") from exc
        return self._unwrap(response)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(
                f"{self.BASE}{path}", json=body, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise IndexHubError(f"指数直通车请求失败: {exc}") from exc
        return self._unwrap(response)
