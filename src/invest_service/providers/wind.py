"""Wind（万得）行情 provider。

直连 Wind 的 MCP 数据服务（``mcp.wind.com.cn/vserver_*_data/mcp/``）。这些服务
无会话状态，一次 POST 拿到 SSE/JSON 响应；K 线返回 ``data.columns`` + ``data.rows``
的列式结构。

覆盖范围：股票、指数、ETF（分别走 stock / index / fund 三个域）。
搜索与目录仍由本地索引负责，这里只提供历史日线。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ..models import AssetCategory
from .base import MarketDataProvider, ProviderAsset, ProviderBar, ProviderError


class WindMcpError(ProviderError):
    """Wind MCP 调用失败。"""


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "nan", "None"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _sse_payload(text: str) -> dict[str, Any]:
    """Wind 以 SSE 返回，取第一条 data: 的 JSON；也兼容纯 JSON。"""
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    for line in stripped.splitlines():
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        return json.loads(chunk)
    raise WindMcpError(f"Wind 返回无法解析: {stripped[:160]}")


class WindMcpClient:
    BASE = "https://mcp.wind.com.cn"
    SERVERS = {
        "stock": "vserver_stock_data",
        "index": "vserver_index_data",
        "fund": "vserver_fund_data",
        "bond": "vserver_bond_data",
        "econ": "vserver_economic_data",
        "docs": "vserver_financial_docs",
        "analytics": "vserver_analytics_data",
    }

    def __init__(self, api_key: str, client: httpx.Client | None = None, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)
        self._next_id = 0

    def _url(self, server: str) -> str:
        try:
            path = self.SERVERS[server]
        except KeyError as exc:
            raise WindMcpError(f"未知的 Wind 数据域: {server}") from exc
        return f"{self.BASE}/{path}/mcp/"

    def ping(self) -> None:
        """最轻量的一次 initialize，用于探测账号/余额是否恢复。"""
        self._next_id += 1
        self.client.post(
            self._url("stock"),
            json={
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "invest-probe", "version": "0.1.0"},
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=self.timeout,
        )

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "InvestService/0.1",
        }
        try:
            response = self.client.post(
                self._url(server), json=payload, headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise WindMcpError(f"Wind 请求失败: {exc}") from exc
        if response.status_code == 401:
            raise WindMcpError("Wind 鉴权失败（401），请检查 WIND_API_KEY")
        if response.status_code == 429:
            raise WindMcpError("Wind 触发限流（429）")
        response.raise_for_status()

        envelope = _sse_payload(response.text)
        if "error" in envelope:
            raise WindMcpError(f"Wind 调用失败: {envelope['error']}")
        result = envelope.get("result") or {}
        texts = [
            block.get("text", "")
            for block in (result.get("content") or [])
            if isinstance(block, dict)
        ]
        raw = "\n".join(texts)
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise WindMcpError(f"Wind 返回非 JSON 内容: {raw[:160]}") from exc
        if isinstance(body, dict) and body.get("error"):
            raise WindMcpError(f"Wind 业务错误: {body['error']}")
        return body if isinstance(body, dict) else {"data": body}


@dataclass(frozen=True)
class _WindTool:
    server: str
    tool: str


class WindMarketProvider(MarketDataProvider):
    """按 Wind 的 K 线接口取历史日线。"""

    name = "wind"
    TOOLS = {
        AssetCategory.STOCK: _WindTool("stock", "get_stock_kline"),
        AssetCategory.INDEX: _WindTool("index", "get_index_kline"),
        AssetCategory.ETF: _WindTool("fund", "get_fund_kline"),
    }

    def __init__(self, api_key: str | None, client: WindMcpClient | None = None):
        self.api_key = api_key
        self._client = client

    @property
    def client(self) -> WindMcpClient:
        if self._client is None:
            if not self.api_key:
                raise WindMcpError("WIND_API_KEY 未配置")
            self._client = WindMcpClient(self.api_key)
        return self._client

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        # 资产搜索统一走本地索引。
        return []

    def history(
        self, asset: ProviderAsset, start_date: date, end_date: date
    ) -> list[ProviderBar]:
        target = self.TOOLS.get(asset.category)
        if target is None:
            return []
        payload = self.client.call(
            target.server,
            target.tool,
            {
                "windcode": asset.provider_id or asset.symbol,
                "begin_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "period": "10",  # 日 K
            },
        )
        return self._parse_bars(payload, start_date, end_date)

    @staticmethod
    def _parse_bars(
        payload: dict[str, Any], start_date: date, end_date: date
    ) -> list[ProviderBar]:
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        columns = [str(col.get("name") or "") for col in data.get("columns") or []]
        rows = data.get("rows") or []
        if not columns or not rows:
            return []

        position = {name.upper(): index for index, name in enumerate(columns)}

        def cell(row: list[Any], key: str) -> Any:
            index = position.get(key)
            if index is None or index >= len(row):
                return None
            return row[index]

        bars: list[ProviderBar] = []
        previous: Decimal | None = None
        for row in sorted(rows, key=lambda r: str(cell(r, "TIME") or "")):
            if not isinstance(row, list):
                continue
            trade_date = _iso_date(cell(row, "TIME"))
            close = _decimal(cell(row, "MATCH"))
            if trade_date is None or close is None:
                continue
            if not start_date <= trade_date <= end_date:
                continue
            open_price = _decimal(cell(row, "OPEN"))
            change = close - previous if previous is not None else None
            change_percent = (
                (change / previous * 100).quantize(Decimal("0.000001"))
                if change is not None and previous
                else None
            )
            bars.append(
                ProviderBar(
                    trade_date=trade_date,
                    open=open_price,
                    high=_decimal(cell(row, "HIGH")),
                    low=_decimal(cell(row, "LOW")),
                    close=close,
                    previous_close=previous,
                    change=change,
                    change_percent=change_percent,
                    volume=_decimal(cell(row, "VOLUME")),
                    amount=_decimal(cell(row, "TURNOVER")),
                    source="wind",
                )
            )
            previous = close
        return bars
