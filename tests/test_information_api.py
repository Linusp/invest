import asyncio

from invest_service.mcp_server import build_mcp


def _call_tool(mcp, name, arguments):
    return asyncio.run(
        mcp._tool_manager.call_tool(name, arguments, context=None, convert_result=False)
    )


def _prepare_information_subjects(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    client.post(
        "/api/v1/market-scopes",
        json={"code": "CN.ASHARE", "name": "A 股", "scope_type": "market"},
    )
    client.post(
        "/api/v1/market-scopes",
        json={
            "code": "CN.ASHARE.BANK",
            "name": "银行",
            "scope_type": "sector",
            "parent_code": "CN.ASHARE",
        },
    )


def test_information_submission_deduplicates_and_filters_associations(client):
    _prepare_information_subjects(client)
    payload = {
        "title": "银行净息差出现企稳迹象",
        "source_name": "示例财经",
        "url": "https://example.com/news/bank-margin",
        "published_at": "2026-08-26T08:30:00+08:00",
        "summary": "多家银行披露净息差边际改善。",
        "content": "## 关键事实\n- 净息差环比企稳",
        "content_format": "markdown",
        "language": "zh-CN",
        "information_type": "news",
        "search_context": "银行 净息差",
        "importance": 4,
        "confidence": "0.85",
        "market_scope_codes": ["CN.ASHARE.BANK"],
        "assets": [{"symbol": "600000.SH", "category": "stock"}],
    }
    created = client.post("/api/v1/information", json=payload)
    assert created.status_code == 201
    item = created.json()
    assert item["content"]["blocks"][0]["type"] == "heading"
    assert item["market_scope_codes"] == ["CN.ASHARE.BANK"]
    assert item["assets"][0]["symbol"] == "600000.SH"

    duplicate_payload = {
        **payload,
        "summary": "更新后的摘要",
        "market_scope_codes": ["CN.ASHARE", "CN.ASHARE.BANK"],
    }
    duplicate = client.post("/api/v1/information", json=duplicate_payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == item["id"]
    assert duplicate.json()["summary"] == "更新后的摘要"
    assert duplicate.json()["market_scope_codes"] == ["CN.ASHARE", "CN.ASHARE.BANK"]

    filtered = client.get(
        "/api/v1/information",
        params={
            "market_scope_code": "CN.ASHARE.BANK",
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "source_name": "示例财经",
            "information_type": "news",
            "query": "净息差",
            "min_importance": 4,
        },
    )
    assert filtered.status_code == 200
    assert [entry["id"] for entry in filtered.json()] == [item["id"]]


def test_information_can_be_unassociated_and_linked_to_commentary(client):
    _prepare_information_subjects(client)
    information = client.post(
        "/api/v1/information",
        json={
            "title": "宏观流动性观察",
            "source_name": "公开资料",
            "url": "https://example.com/macro/liquidity",
            "published_at": "2026-08-26T07:00:00Z",
            "content": {"version": 1, "blocks": [{"type": "paragraph", "text": "流动性平稳"}]},
            "information_type": "macro",
        },
    ).json()
    assert information["market_scope_codes"] == []
    assert information["assets"] == []

    commentary = client.post(
        "/api/v1/commentaries",
        json={
            "subject_type": "market",
            "market_scope_code": "CN.ASHARE",
            "session": "pre_market",
            "trading_date": "2026-08-26",
            "title": "盘前流动性",
            "content": {"version": 1, "blocks": []},
        },
    ).json()
    linked = client.post(
        f"/api/v1/commentaries/{commentary['id']}/information/{information['id']}"
    )
    assert linked.status_code == 204
    assert client.get(
        f"/api/v1/commentaries/{commentary['id']}/information"
    ).json()[0]["id"] == information["id"]
    assert client.get("/api/v1/information", params={"referenced": True}).json()[0][
        "id"
    ] == information["id"]
    assert client.delete(
        f"/api/v1/commentaries/{commentary['id']}/information/{information['id']}"
    ).status_code == 204

    unsafe = client.post(
        "/api/v1/information",
        json={
            "title": "不安全链接",
            "source_name": "未知",
            "url": "javascript:alert(1)",
            "published_at": "2026-08-26T07:00:00Z",
            "content": {"version": 1, "blocks": []},
            "information_type": "news",
        },
    )
    assert unsafe.status_code == 422


def test_information_mcp_submission_and_queries(session_factory, provider):
    mcp = build_mcp(session_factory, provider)
    assert {
        "submit_information",
        "list_information",
        "get_information",
        "link_information_to_commentary",
        "unlink_information_from_commentary",
        "list_commentary_information",
    }.issubset(mcp._tool_manager._tools)
    created = _call_tool(
        mcp,
        "submit_information",
        {
            "title": "外部资讯",
            "source_name": "OpenCLI",
            "url": "https://example.com/opencli/1",
            "published_at": "2026-08-26T09:00:00+08:00",
            "content": "采集到的摘要",
            "content_format": "markdown",
            "information_type": "news",
        },
    )
    assert created["content"] == "采集到的摘要"
    assert _call_tool(mcp, "get_information", {"information_id": created["id"]})[
        "id"
    ] == created["id"]
    assert _call_tool(mcp, "list_information", {"query": "外部资讯"})[0][
        "id"
    ] == created["id"]


def test_information_page_renders_and_filters_server_records(client):
    page = client.get("/information")
    assert page.status_code == 200
    assert "资讯中心" in page.text
    assert 'api("/information' in page.text
    assert "关联市场代码" in page.text
    assert "content_html" in page.text
