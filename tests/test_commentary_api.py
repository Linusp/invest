import asyncio

from invest_service.mcp_server import build_mcp


def _call_tool(mcp, name, arguments):
    return asyncio.run(
        mcp._tool_manager.call_tool(name, arguments, context=None, convert_result=False)
    )


def _prepare_subjects(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    portfolio = client.post(
        "/api/v1/portfolios", json={"name": "银行组合"}
    ).json()
    scope = client.post(
        "/api/v1/market-scopes",
        json={"code": "CN.ASHARE", "name": "A 股", "scope_type": "market"},
    ).json()
    return portfolio, scope


def test_commentaries_normalize_content_and_filter_three_subject_types(client):
    portfolio, scope = _prepare_subjects(client)
    market = client.post(
        "/api/v1/commentaries",
        json={
            "subject_type": "market",
            "market_scope_code": scope["code"],
            "session": "pre_market",
            "trading_date": "2026-08-26",
            "title": "A 股盘前",
            "summary": "观察指数能否放量",
            "content": {
                "version": 1,
                "blocks": [
                    {"type": "metric", "label": "上证指数", "value": 3880, "unit": "点"}
                ],
            },
            "source": "ai",
            "has_outlook": True,
        },
    )
    assert market.status_code == 201
    assert "**上证指数**: 3880 点" in market.json()["content_markdown"]

    portfolio_comment = client.post(
        "/api/v1/commentaries",
        json={
            "subject_type": "portfolio",
            "portfolio_id": portfolio["id"],
            "session": "post_market",
            "trading_date": "2026-08-26",
            "title": "银行组合盘后",
            "content_format": "markdown",
            "content": "## 风险\n- 净息差下行\n- 地产风险",
            "source": "human",
            "has_risk": True,
        },
    )
    assert portfolio_comment.status_code == 201
    blocks = portfolio_comment.json()["content"]["blocks"]
    assert [block["type"] for block in blocks] == ["heading", "list"]
    assert portfolio_comment.json()["portfolio_id"] == portfolio["id"]

    asset = client.post(
        "/api/v1/commentaries",
        json={
            "subject_type": "asset",
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "session": "intraday",
            "trading_date": "2026-08-26",
            "title": "浦发银行盘中",
            "content_format": "html",
            "content": "<h2>盘面</h2><p>价格走强</p><script>alert('x')</script>",
            "source": "import",
        },
    )
    assert asset.status_code == 201
    assert asset.json()["asset_symbol"] == "600000.SH"
    assert asset.json()["asset_category"] == "stock"
    assert "<script" not in asset.json()["content_html"]
    assert "alert" not in asset.json()["content_html"]

    filtered = client.get(
        "/api/v1/commentaries",
        params={
            "subject_type": "asset",
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "session": "intraday",
            "start_date": "2026-08-26",
            "end_date": "2026-08-26",
        },
    )
    assert filtered.status_code == 200
    assert [item["title"] for item in filtered.json()] == ["浦发银行盘中"]


def test_commentary_revision_preserves_original_and_subject(client):
    portfolio, _ = _prepare_subjects(client)
    original = client.post(
        "/api/v1/commentaries",
        json={
            "subject_type": "portfolio",
            "portfolio_id": portfolio["id"],
            "session": "daily",
            "trading_date": "2026-08-26",
            "title": "初版复盘",
            "content": {"version": 1, "blocks": [{"type": "paragraph", "text": "初版"}]},
            "source": "human",
        },
    ).json()

    revised = client.post(
        f"/api/v1/commentaries/{original['id']}/revisions",
        json={
            "title": "修订复盘",
            "content_format": "markdown",
            "content": "修正后的判断",
            "source": "human",
        },
    )
    assert revised.status_code == 201
    assert revised.json()["revises_id"] == original["id"]
    assert revised.json()["portfolio_id"] == portfolio["id"]
    assert client.get(f"/api/v1/commentaries/{original['id']}").json()["title"] == "初版复盘"
    assert client.patch(f"/api/v1/commentaries/{original['id']}", json={}).status_code == 405


def test_commentary_requires_exactly_one_matching_subject(client):
    portfolio, scope = _prepare_subjects(client)
    invalid = client.post(
        "/api/v1/commentaries",
        json={
            "subject_type": "portfolio",
            "portfolio_id": portfolio["id"],
            "market_scope_code": scope["code"],
            "session": "daily",
            "trading_date": "2026-08-26",
            "title": "错误对象",
            "content": {"version": 1, "blocks": []},
        },
    )
    assert invalid.status_code == 422


def test_commentary_mcp_defaults_to_markdown_and_can_return_structured(
    session_factory, provider
):
    mcp = build_mcp(session_factory, provider)
    assert {
        "create_commentary",
        "list_commentaries",
        "get_commentary",
        "revise_commentary",
    }.issubset(mcp._tool_manager._tools)
    _call_tool(
        mcp,
        "create_market_scope",
        {"code": "CN.ASHARE", "name": "A 股", "scope_type": "market"},
    )
    created = _call_tool(
        mcp,
        "create_commentary",
        {
            "subject_type": "market",
            "market_scope_code": "CN.ASHARE",
            "session": "pre_market",
            "trading_date": "2026-08-26",
            "title": "盘前观察",
            "content": "## 重点\n关注成交量",
            "content_format": "markdown",
            "source": "ai",
        },
    )
    assert created["content"] == "## 重点\n\n关注成交量"
    structured = _call_tool(
        mcp,
        "get_commentary",
        {"commentary_id": created["id"], "output_format": "structured"},
    )
    assert structured["content"]["blocks"][0]["type"] == "heading"
    assert _call_tool(
        mcp,
        "list_commentaries",
        {"market_scope_code": "CN.ASHARE", "query": "成交量"},
    )[0]["id"] == created["id"]
