import asyncio

from invest_service.mcp_server import build_mcp


def _call_tool(mcp, name, arguments):
    return asyncio.run(
        mcp._tool_manager.call_tool(name, arguments, context=None, convert_result=False)
    )


def test_market_scope_api_manages_extensible_hierarchy(client):
    market = client.post(
        "/api/v1/market-scopes",
        json={
            "code": "CN.ASHARE",
            "name": "A 股",
            "scope_type": "market",
            "description": "中国内地股票市场",
        },
    )
    assert market.status_code == 201
    assert market.json()["parent_code"] is None

    sector = client.post(
        "/api/v1/market-scopes",
        json={
            "code": "CN.ASHARE.BANK",
            "name": "银行",
            "scope_type": "sector",
            "parent_code": "CN.ASHARE",
        },
    )
    assert sector.status_code == 201
    assert sector.json()["parent_code"] == "CN.ASHARE"

    theme = client.post(
        "/api/v1/market-scopes",
        json={
            "code": "CN.ASHARE.BANK.HIGH_DIVIDEND",
            "name": "银行高股息",
            "scope_type": "theme",
            "parent_code": "CN.ASHARE.BANK",
        },
    )
    assert theme.status_code == 201

    scopes = client.get("/api/v1/market-scopes").json()
    assert [item["code"] for item in scopes] == [
        "CN.ASHARE",
        "CN.ASHARE.BANK",
        "CN.ASHARE.BANK.HIGH_DIVIDEND",
    ]
    sectors = client.get(
        "/api/v1/market-scopes", params={"scope_type": "sector"}
    ).json()
    assert [item["code"] for item in sectors] == ["CN.ASHARE.BANK"]

    updated = client.patch(
        "/api/v1/market-scopes/CN.ASHARE.BANK",
        json={"name": "银行业", "description": "申万银行行业"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "银行业"

    assert client.delete("/api/v1/market-scopes/CN.ASHARE.BANK").status_code == 409
    assert (
        client.delete(
            "/api/v1/market-scopes/CN.ASHARE.BANK.HIGH_DIVIDEND"
        ).status_code
        == 204
    )


def test_market_scope_rejects_missing_parent_and_cycles(client):
    missing = client.post(
        "/api/v1/market-scopes",
        json={
            "code": "CN.UNKNOWN.BANK",
            "name": "银行",
            "scope_type": "sector",
            "parent_code": "CN.UNKNOWN",
        },
    )
    assert missing.status_code == 422

    client.post(
        "/api/v1/market-scopes",
        json={"code": "CN", "name": "中国", "scope_type": "market"},
    )
    client.post(
        "/api/v1/market-scopes",
        json={
            "code": "CN.STOCK",
            "name": "股票",
            "scope_type": "market",
            "parent_code": "CN",
        },
    )
    cycle = client.patch(
        "/api/v1/market-scopes/CN",
        json={"parent_code": "CN.STOCK"},
    )
    assert cycle.status_code == 422


def test_market_scope_mcp_tools_share_the_same_registry(session_factory, provider):
    mcp = build_mcp(session_factory, provider)
    assert {
        "create_market_scope",
        "list_market_scopes",
        "get_market_scope",
        "update_market_scope",
        "delete_market_scope",
    }.issubset(mcp._tool_manager._tools)

    created = _call_tool(
        mcp,
        "create_market_scope",
        {"code": "GLOBAL.GOLD", "name": "黄金", "scope_type": "commodity"},
    )
    assert created["code"] == "GLOBAL.GOLD"
    assert _call_tool(mcp, "get_market_scope", {"code": "GLOBAL.GOLD"})[
        "scope_type"
    ] == "commodity"
    assert _call_tool(
        mcp,
        "update_market_scope",
        {"code": "GLOBAL.GOLD", "description": "全球黄金市场"},
    )["description"] == "全球黄金市场"
    assert len(_call_tool(mcp, "list_market_scopes", {})) == 1
    _call_tool(mcp, "delete_market_scope", {"code": "GLOBAL.GOLD"})
    assert _call_tool(mcp, "list_market_scopes", {}) == []
