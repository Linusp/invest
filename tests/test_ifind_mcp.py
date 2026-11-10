import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from invest_service.models import Asset, AssetCategory, QuoteSnapshot
from invest_service.providers.ifind_mcp import IfindMcpClient, IfindMcpError, _parse_tables
from invest_service.services.quote_snapshot import QuoteSnapshotService

QUOTE_PAYLOAD = {
    "code": 1,
    "msg": "success",
    "data": {
        "tables": [
            [
                "证券代码",
                "证券简称",
                "time",
                "最新价",
                "涨跌幅",
                "成交量",
                "成交额",
                "换手率",
                "市盈率TTM",
            ],
            [
                "600000.SH",
                "浦发银行",
                "2026-11-10 11:48:23",
                "1438.92",
                "-0.42007",
                "12740",
                "1800000000",
                "0.10191",
                "21.89327",
            ],
            [
                "000300.SH",
                "沪深300",
                "2026-11-10 11:49:21",
                "4058.95",
                "0.07001",
                "86022366",
                "298000000000",
                "",
                "",
            ],
        ],
    },
}


def _envelope(text: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def _mock_client(payload=None, calls=None) -> IfindMcpClient:
    payload = payload or QUOTE_PAYLOAD

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(json.loads(request.content))
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"Mcp-Session-Id": "sid-1"})
        if body.get("method") == "notifications/initialized":
            return httpx.Response(200, json={})
        return httpx.Response(200, json=_envelope(json.dumps(payload, ensure_ascii=False)))

    return IfindMcpClient(
        "test-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        batch_pause=0,
    )


def test_parse_tables_expands_header_rows():
    rows = _parse_tables(QUOTE_PAYLOAD)
    assert len(rows) == 2
    assert rows[0]["证券代码"] == "600000.SH"


def test_quotes_parses_decimal_fields():
    quotes = _mock_client().quotes(
        [("600000.SH", AssetCategory.STOCK), ("000300.SH", AssetCategory.INDEX)]
    )

    assert [q.symbol for q in quotes] == ["600000.SH", "000300.SH"]
    first = quotes[0]
    assert first.price == Decimal("1438.92")
    assert first.change_percent == Decimal("-0.42007")
    assert first.pe_ttm == Decimal("21.89327")
    assert first.as_of.year == 2026 and first.as_of.hour == 11
    # 缺失值保持为空，不填充为 0。
    assert quotes[1].turnover_rate is None


def test_quotes_batches_every_ten_symbols():
    calls = []
    symbols = [(f"60000{i}.SH", AssetCategory.STOCK) for i in range(11)]
    _mock_client(calls=calls).quotes(symbols)

    tool_calls = [c for c in calls if c.get("method") == "tools/call"]
    assert len(tool_calls) == 2
    assert len(tool_calls[0]["params"]["arguments"]["symbols"].split(",")) == 10
    assert len(tool_calls[1]["params"]["arguments"]["symbols"].split(",")) == 1


def test_quotes_skips_unsupported_categories():
    calls = []
    _mock_client(calls=calls).quotes([("510300.SH", AssetCategory.ETF)])
    assert not [c for c in calls if c.get("method") == "tools/call"]


def test_business_error_raises():
    with pytest.raises(IfindMcpError):
        client = _mock_client({"code": 0, "msg": "quota exceeded"})
        client.quotes([("600000.SH", AssetCategory.STOCK)])


def test_refresh_persists_stock_and_index_snapshots(session_factory, provider):
    with session_factory() as session:
        session.add_all(
            [
                Asset(key="600000.SH", symbol="600000.SH", code="600000", name="浦发银行",
                      category=AssetCategory.STOCK, currency="CNY", provider_id="600000.SH"),
                Asset(key="000300.SH", symbol="000300.SH", code="000300", name="沪深300",
                      category=AssetCategory.INDEX, currency="CNY", provider_id="000300.SH"),
            ]
        )
        session.commit()
        result = QuoteSnapshotService(session).refresh(_mock_client())

    assert result["stored"] == 2  # ETF 不在快照范围内
    with session_factory() as session:
        row = session.get(QuoteSnapshot, "600000.SH")
        assert row is not None
        assert row.trade_date == date(2026, 11, 10)
        assert row.source == "ifind"
        assert row.price == Decimal("1438.92")
        assert QuoteSnapshotService(session).latest_price(
            "600000.SH", on_or_after=date(2026, 11, 11)
        ) is None
