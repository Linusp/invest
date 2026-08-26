import asyncio

from invest_service.mcp_server import build_mcp


def call(mcp, name, args):
    return asyncio.run(mcp._tool_manager.call_tool(name, args, context=None, convert_result=False))


def test_trade_plan_status_history_is_immutable_and_queryable(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    portfolio = client.post("/api/v1/portfolios", json={"name": "审计组合"}).json()
    plan = client.post(
        "/api/v1/trade-plans",
        json={
            "portfolio_id": portfolio["id"], "asset_symbol": "600000.SH", "asset_category": "stock",
            "action": "buy", "conditions": [{"type": "price_lte", "value": 90}],
            "quantity": 10,
        },
    ).json()
    client.post(f"/api/v1/trade-plans/{plan['id']}/status", json={"status": "active"})
    client.post(f"/api/v1/trade-plans/{plan['id']}/status", json={"status": "triggered"})
    history = client.get(f"/api/v1/trade-plans/{plan['id']}/history")
    assert history.status_code == 200
    assert [(item["from_status"], item["to_status"]) for item in history.json()] == [
        ("draft", "active"), ("active", "triggered")
    ]
    assert all(item["created_at"] for item in history.json())


def test_trade_plan_audit_history_is_available_in_mcp(session_factory, provider):
    mcp = build_mcp(session_factory, provider)
    assert "get_trade_plan_history" in mcp._tool_manager._tools
