"""同花顺 iFinD 金融数据 MCP 客户端。

invest 侧作为 MCP client 直接调用官方分域服务，目前只用到「实时行情快照」：

    POST https://api-mcp.51ifind.com:8643/ds-mcp-servers/<server>
    Authorization: <MCP 密钥>
    Mcp-Session-Id: <initialize 返回>

返回结构有三种形态，这里只处理行情类工具的 ``data.tables``（表头行 + 数据行），
并保留一个通用的 :meth:`IfindMcpClient.call` 供以后接财务/新闻/板块使用。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..models import AssetCategory

SHANGHAI = ZoneInfo("Asia/Shanghai")


class IfindMcpError(RuntimeError):
    """iFinD MCP 调用失败（鉴权、会话、业务错误）。"""


class IfindRateLimitError(IfindMcpError):
    """被 iFinD 限流（429）。调用方应退避后重试。"""


@dataclass(frozen=True)
class IfindQuote:
    """一条实时行情快照。"""

    symbol: str
    name: str
    as_of: datetime
    price: Decimal | None
    change_percent: Decimal | None
    volume: Decimal | None = None
    amount: Decimal | None = None
    turnover_rate: Decimal | None = None
    pe_ttm: Decimal | None = None


# 各市场板块的实时指标集合（工具单次请求上限 10 个指标）。
INDICATORS = {
    "stock": "最新价,涨跌幅,成交量,成交额,换手率,市盈率TTM",
    "index": "最新价,涨跌幅,成交量,成交额",
}

# 每个板块单次最多 10 个标的。
BATCH_SIZE = 10

# 中文列名 → IfindQuote 字段。
_COLUMN_FIELDS = {
    "最新价": "price",
    "涨跌幅": "change_percent",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover_rate",
    "市盈率TTM": "pe_ttm",
}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "nan"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _parse_tables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """把 ``data.tables`` 展开成字典列表。

    行情类工具返回「一张表 = 行列表」（首行为表头）::

        "tables": [["证券代码", "最新价"], ["600519.SH", "1438.92"]]

    为兼容可能出现的多表嵌套（每张表仍是行列表），这里两种形态都处理。
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    tables = data.get("tables") or []
    if not isinstance(tables, list) or not tables:
        return []

    def expand(rows: list[Any]) -> list[dict[str, Any]]:
        if not rows or not isinstance(rows[0], list):
            return []
        header = [str(cell).strip() for cell in rows[0]]
        out = []
        for raw in rows[1:]:
            if isinstance(raw, list) and len(raw) == len(header):
                out.append(dict(zip(header, raw)))
        return out

    first = tables[0]
    if isinstance(first, list) and first and not isinstance(first[0], list):
        return expand(tables)  # 单表：tables 本身就是行列表

    rows: list[dict[str, Any]] = []
    for table in tables:
        if isinstance(table, list):
            rows.extend(expand(table))
    return rows


def _parse_as_of(text: Any) -> datetime:
    raw = str(text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
    return datetime.now(tz=SHANGHAI)


class IfindMcpClient:
    """极简 MCP over HTTP 客户端，按板块惰性建立会话并缓存 session id。"""

    BASE = "https://api-mcp.51ifind.com:8643/ds-mcp-servers"
    SERVERS = {
        "stock": "hexin-ifind-ds-stock-mcp",
        "index": "hexin-ifind-ds-index-mcp",
        "news": "hexin-ifind-ds-news-mcp",
    }
    TOOLS = {
        AssetCategory.STOCK: ("stock", "stock_highfreq_quotes"),
        AssetCategory.INDEX: ("index", "index_highfreq_quotes"),
    }

    def __init__(
        self,
        token: str,
        client: httpx.Client | None = None,
        timeout: float = 45.0,
        batch_pause: float = 0.8,
        max_attempts: int = 3,
    ):
        self.token = token
        self.timeout = timeout
        self.batch_pause = batch_pause
        self.max_attempts = max_attempts
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)
        self._sessions: dict[str, str] = {}
        self._next_id = 0

    # -- 传输层 ---------------------------------------------------------

    def _url(self, server: str) -> str:
        try:
            path = self.SERVERS[server]
        except KeyError as exc:
            raise IfindMcpError(f"未知的 iFinD 板块: {server}") from exc
        return f"{self.BASE}/{path}"

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": self.token,
            "User-Agent": "InvestService/0.1",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
            headers["MCP-Protocol-Version"] = "2025-03-26"
        return headers

    def _rpc(self, server: str, payload: dict[str, Any], session_id: str | None) -> httpx.Response:
        return self.client.post(
            self._url(server),
            json=payload,
            headers=self._headers(session_id),
            timeout=self.timeout,
        )

    def _open(self, server: str) -> str:
        """initialize + notifications/initialized，返回 session id。"""
        self._next_id += 1
        resp = self._rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "invest-service", "version": "0.1.0"},
                },
            },
            None,
        )
        if resp.status_code == 401:
            raise IfindMcpError("iFinD MCP 鉴权失败（401），请检查 MCP 密钥")
        resp.raise_for_status()
        session_id = resp.headers.get("Mcp-Session-Id")
        if not session_id:
            raise IfindMcpError("iFinD MCP initialize 未返回 Mcp-Session-Id")
        self._rpc(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
        self._sessions[server] = session_id
        return session_id

    def _session(self, server: str) -> str:
        return self._sessions.get(server) or self._open(server)

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用一个工具，返回内层 JSON（``{code, msg, data}``）。"""
        for attempt in (1, 2):
            session_id = self._session(server)
            self._next_id += 1
            resp = self._rpc(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                },
                session_id,
            )
            if resp.status_code in {400, 404, 410} and attempt == 1:
                # 会话过期：丢掉缓存重开一次。
                self._sessions.pop(server, None)
                continue
            if resp.status_code == 401:
                raise IfindMcpError("iFinD MCP 鉴权失败（401），请检查 MCP 密钥")
            if resp.status_code == 429:
                raise IfindRateLimitError("iFinD MCP 429 Too Many Requests")
            resp.raise_for_status()
            envelope = resp.json()
            if "error" in envelope:
                raise IfindMcpError(f"iFinD MCP 调用失败: {envelope['error']}")
            result = envelope.get("result") or {}
            text = "\n".join(
                block.get("text", "")
                for block in (result.get("content") or [])
                if isinstance(block, dict)
            )
            try:
                payload = json.loads(text)
            except ValueError as exc:
                if "429" in text or "请求过于频繁" in text:
                    raise IfindRateLimitError(text[:200]) from exc
                raise IfindMcpError(f"iFinD 返回非 JSON 内容: {text[:200]}") from exc
            if isinstance(payload, dict) and payload.get("code") not in (None, 1):
                raise IfindMcpError(f"iFinD 业务错误: {payload.get('msg') or payload}")
            return payload if isinstance(payload, dict) else {"data": payload}
        raise IfindMcpError("iFinD MCP 调用失败：会话无法建立")

    # -- 业务层 ---------------------------------------------------------

    def quotes(self, assets: list[tuple[str, AssetCategory]]) -> list[IfindQuote]:
        """批量取实时快照；不支持的类别（ETF 等）会被跳过。"""
        grouped: dict[AssetCategory, list[str]] = {}
        for symbol, category in assets:
            if category in self.TOOLS:
                grouped.setdefault(category, []).append(symbol)

        quotes: list[IfindQuote] = []
        for category, symbols in grouped.items():
            server, tool = self.TOOLS[category]
            for start in range(0, len(symbols), BATCH_SIZE):
                chunk = symbols[start : start + BATCH_SIZE]
                payload = self._call_with_backoff(
                    server,
                    tool,
                    {
                        "data_mode": "real_time",
                        "symbols": ",".join(chunk),
                        "indicators": INDICATORS[server],
                    },
                )
                if self.batch_pause:
                    time.sleep(self.batch_pause)
                # 服务端可能因简称匹配返回额外标的，只保留本次请求的。
                wanted = set(chunk)
                quotes.extend(
                    quote
                    for quote in self._quotes_from_payload(payload)
                    if quote.symbol in wanted
                )
        return quotes

    def _call_with_backoff(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """限流时按 1.5s / 3s 退避重试；其他错误直接抛出。"""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.call(server, tool, arguments)
            except IfindRateLimitError:
                if attempt == self.max_attempts:
                    raise
                time.sleep(1.5 * attempt)
        raise IfindMcpError("iFinD MCP 调用失败")  # pragma: no cover

    @staticmethod
    def _quotes_from_payload(payload: dict[str, Any]) -> list[IfindQuote]:
        quotes: list[IfindQuote] = []
        for row in _parse_tables(payload):
            symbol = str(row.get("证券代码") or "").strip()
            if not symbol:
                continue
            values = {
                field: _decimal(row.get(column))
                for column, field in _COLUMN_FIELDS.items()
            }
            quotes.append(
                IfindQuote(
                    symbol=symbol,
                    name=str(row.get("证券简称") or "").strip(),
                    as_of=_parse_as_of(row.get("time")),
                    price=values["price"],
                    change_percent=values["change_percent"],
                    volume=values["volume"],
                    amount=values["amount"],
                    turnover_rate=values["turnover_rate"],
                    pe_ttm=values["pe_ttm"],
                )
            )
        return quotes


def snapshot_trade_date(as_of: datetime) -> date:
    return as_of.astimezone(SHANGHAI).date()
