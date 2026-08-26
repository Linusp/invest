import asyncio

from invest_service.mcp_server import build_mcp
from invest_service.services import MarketService


def call_tool(mcp, name, arguments):
    return asyncio.run(
        mcp._tool_manager.call_tool(name, arguments, context=None, convert_result=False)
    )


def test_mcp_tools_execute_market_and_strategy_workflows(session_factory, provider):
    with session_factory() as session:
        MarketService(session, provider).sync_search_index()
    mcp = build_mcp(session_factory, provider)
    assert {
        "search_assets",
        "list_assets",
        "get_asset",
        "register_asset",
        "refresh_asset_market_data",
        "get_market_history",
        "set_asset_favorite",
        "list_asset_tags",
        "update_asset_tags",
        "add_asset_tag",
        "remove_asset_tag",
        "list_tags",
        "create_tag",
        "delete_tag",
        "reorder_tags",
        "pin_tag",
        "list_tag_assets",
        "get_exchange_rate",
        "create_portfolio",
        "list_portfolios",
        "get_portfolio",
        "update_portfolio",
        "set_portfolio_opening_snapshot",
        "get_portfolio_opening_snapshot",
        "delete_portfolio_opening_snapshot",
        "get_portfolio_trades",
        "get_portfolio_positions",
        "add_portfolio_trade",
        "create_strategy",
        "list_strategies",
        "get_strategy",
        "update_strategy",
        "set_strategy_opening_snapshot",
        "get_strategy_opening_snapshot",
        "delete_strategy_opening_snapshot",
        "get_strategy_trades",
        "get_strategy_positions",
        "add_strategy_trade",
    }.issubset(mcp._tool_manager._tools)

    assets = call_tool(mcp, "search_assets", {"query": "600000"})
    assert assets[0]["symbol"] == "600000.SH"
    strategy = call_tool(
        mcp,
        "create_portfolio",
        {
            "name": "MCP portfolio",
            "initial_capital": 100000,
            "investment_style": "稳健",
            "is_owned": True,
            "purpose": "养老",
            "investment_direction": "红利",
            "constraints": "不加杠杆",
            "notes": "年度复盘",
        },
    )
    assert strategy["initial_capital"] == "100000.000000"
    assert strategy["investment_style"] == "稳健"
    assert call_tool(mcp, "list_portfolios", {})[0]["id"] == strategy["id"]
    updated = call_tool(
        mcp,
        "update_portfolio",
        {"portfolio_id": strategy["id"], "investment_style": "均衡"},
    )
    assert updated["investment_style"] == "均衡"
    assert call_tool(mcp, "get_portfolio", {"portfolio_id": strategy["id"]})[
        "id"
    ] == strategy["id"]
    snapshot = call_tool(
        mcp,
        "set_portfolio_opening_snapshot",
        {
            "portfolio_id": strategy["id"],
            "snapshot_date": "2026-07-01",
            "balances": [
                {
                    "currency": "CNY",
                    "cash": 1000,
                    "historical_realized_profit": 25,
                }
            ],
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
        "add_portfolio_trade",
        {
            "portfolio_id": strategy["id"],
            "trade_type": "buy",
            "trade_date": "2026-07-02",
            "price": 100,
            "asset_symbol": "600000.SH",
            "quantity": 2,
        },
    )
    assert trade["position_id"]
    detail = call_tool(mcp, "get_portfolio", {"portfolio_id": strategy["id"]})
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
    assert "update_asset_market_data" not in names
