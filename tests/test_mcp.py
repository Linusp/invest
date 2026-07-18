import asyncio

from invest_service.mcp_server import build_mcp


def call_tool(mcp, name, arguments):
    return asyncio.run(
        mcp._tool_manager.call_tool(name, arguments, context=None, convert_result=False)
    )


def test_mcp_tools_execute_market_and_strategy_workflows(session_factory, provider):
    mcp = build_mcp(session_factory, provider)
    assert {
        "search_assets",
        "update_asset_market_data",
        "get_market_history",
        "create_strategy",
        "get_strategy",
        "set_strategy_opening_snapshot",
        "get_strategy_trades",
        "get_strategy_positions",
        "add_strategy_trade",
    }.issubset(mcp._tool_manager._tools)

    assets = call_tool(mcp, "search_assets", {"query": "600000"})
    assert assets[0]["symbol"] == "600000.SH"
    sync = call_tool(
        mcp,
        "update_asset_market_data",
        {
            "symbol": "600000.SH",
            "start_date": "2026-07-01",
            "end_date": "2026-07-13",
        },
    )
    assert sync["created"] == 2

    strategy = call_tool(mcp, "create_strategy", {"name": "MCP strategy"})
    snapshot = call_tool(
        mcp,
        "set_strategy_opening_snapshot",
        {
            "strategy_id": strategy["id"],
            "snapshot_date": "2026-07-01",
            "balances": [{
                "currency": "CNY",
                "cash": 1000,
                "historical_realized_profit": 25,
            }],
            "positions": [
                {
                    "asset_symbol": "600000.SH",
                    "quantity": 1,
                    "average_cost": 90,
                }
            ],
        },
    )
    assert snapshot["balances"][0]["historical_net_contribution"] is None
    assert snapshot["balances"][0]["historical_realized_profit"] == "25.000000"
    trade = call_tool(
        mcp,
        "add_strategy_trade",
        {
            "strategy_id": strategy["id"],
            "trade_type": "buy",
            "trade_date": "2026-07-02",
            "price": 100,
            "asset_symbol": "600000.SH",
            "quantity": 2,
        },
    )
    assert trade["position_id"]
    detail = call_tool(mcp, "get_strategy", {"strategy_id": strategy["id"]})
    assert detail["positions"][0]["quantity"] == "3.000000"
    assert detail["summary"]["net_contribution"] is None


def test_mcp_streamable_http_endpoint(client):
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    initialized = client.post(
        "/mcp/",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        },
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "invest"

    tools = client.post(
        "/mcp/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert tools.status_code == 200
    names = {item["name"] for item in tools.json()["result"]["tools"]}
    assert "get_strategy_positions" in names
    assert "update_asset_market_data" in names
