import asyncio

from invest_service.mcp_server import build_mcp


def _call_tool(mcp, name, arguments):
    return asyncio.run(
        mcp._tool_manager.call_tool(name, arguments, context=None, convert_result=False)
    )


def _prepare_plan(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    return client.post("/api/v1/portfolios", json={"name": "银行组合"}).json()


def _payload(portfolio_id, **changes):
    payload = {
        "portfolio_id": portfolio_id,
        "asset_symbol": "600000.SH",
        "asset_category": "stock",
        "action": "buy",
        "logic": "and",
        "conditions": [
            {"type": "price_lte", "value": "95", "label": "跌到 95 以下"},
            {"type": "change_percent_lte", "value": "-3", "label": "日跌幅超过 3%"},
        ],
        "quantity": "100",
        "valid_from": "2026-08-26",
        "valid_until": "2026-12-31",
        "reason": "分批配置",
        "risk_note": "跌破基本面假设则取消",
        "status": "draft",
    }
    payload.update(changes)
    return payload


def test_trade_plan_crud_allows_multiple_plans_and_safe_status_flow(client):
    portfolio = _prepare_plan(client)
    created = client.post("/api/v1/trade-plans", json=_payload(portfolio["id"]))
    assert created.status_code == 201
    plan = created.json()
    assert plan["status"] == "draft"
    assert plan["asset_name"] == "浦发银行"
    assert plan["conditions"][0]["type"] == "price_lte"
    assert plan["quantity"] == "100.000000"

    second = client.post(
        "/api/v1/trade-plans",
        json=_payload(portfolio["id"], action="sell", amount="5000", quantity=None),
    )
    assert second.status_code == 201
    assert second.json()["id"] != plan["id"]

    activated = client.post(
        f"/api/v1/trade-plans/{plan['id']}/status", json={"status": "active"}
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    triggered = client.post(
        f"/api/v1/trade-plans/{plan['id']}/status", json={"status": "triggered"}
    )
    assert triggered.status_code == 200
    cancelled = client.post(
        f"/api/v1/trade-plans/{plan['id']}/status", json={"status": "cancelled"}
    )
    assert cancelled.status_code == 200
    rejected = client.post(
        f"/api/v1/trade-plans/{plan['id']}/status", json={"status": "active"}
    )
    assert rejected.status_code == 409

    listed = client.get(
        "/api/v1/trade-plans", params={"portfolio_id": portfolio["id"], "status": "cancelled"}
    )
    assert [item["id"] for item in listed.json()] == [plan["id"]]


def test_trade_plan_requires_size_and_valid_condition_shape(client):
    portfolio = _prepare_plan(client)
    no_size = client.post(
        "/api/v1/trade-plans", json=_payload(portfolio["id"], quantity=None)
    )
    assert no_size.status_code == 422
    bad_days = client.post(
        "/api/v1/trade-plans",
        json=_payload(portfolio["id"], confirm_days=0),
    )
    assert bad_days.status_code == 422
    bad_logic = client.post(
        "/api/v1/trade-plans",
        json=_payload(portfolio["id"], logic="xor"),
    )
    assert bad_logic.status_code == 422


def test_trade_plan_mcp_uses_same_contract(session_factory, provider):
    mcp = build_mcp(session_factory, provider)
    assert {
        "create_trade_plan",
        "list_trade_plans",
        "get_trade_plan",
        "update_trade_plan",
        "change_trade_plan_status",
    }.issubset(mcp._tool_manager._tools)
    with session_factory() as session:
        from invest_service.services import MarketService

        MarketService(session, provider).sync_search_index()
    _call_tool(mcp, "search_assets", {"query": "600000"})
    portfolio = _call_tool(mcp, "create_portfolio", {"name": "计划组合"})
    created = _call_tool(
        mcp,
        "create_trade_plan",
        {
            "portfolio_id": portfolio["id"],
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "action": "buy",
            "conditions": [{"type": "price_lte", "value": 90}],
            "quantity": 10,
            "status": "active",
        },
    )
    assert created["status"] == "active"
    assert _call_tool(
        mcp,
        "change_trade_plan_status",
        {"plan_id": created["id"], "status": "triggered"},
    )["status"] == "triggered"
    assert _call_tool(mcp, "get_trade_plan", {"plan_id": created["id"]})["id"] == created["id"]
