def _setup(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    portfolio = client.post("/api/v1/portfolios", json={"name": "复盘组合"}).json()
    plan = client.post(
        "/api/v1/trade-plans",
        json={
            "portfolio_id": portfolio["id"],
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "action": "buy",
            "conditions": [{"type": "price_lte", "value": 95}],
            "quantity": 10,
            "status": "active",
        },
    ).json()
    return portfolio, plan


def test_trade_can_be_linked_to_plan_and_plan_review_is_structured(client):
    portfolio, plan = _setup(client)
    trade = client.post(
        f"/api/v1/portfolios/{portfolio['id']}/trades",
        json={
            "type": "buy",
            "trade_date": "2026-08-26",
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "price": 95,
            "quantity": 10,
            "trade_plan_id": plan["id"],
        },
    )
    assert trade.status_code == 201
    assert trade.json()["trade_plan_id"] == plan["id"]

    review = client.post(
        f"/api/v1/trade-plans/{plan['id']}/review",
        json={
            "outcome": "profitable",
            "summary": "按计划执行，成交纪律良好",
            "content": {
                "version": 1,
                "blocks": [{"type": "paragraph", "text": "复盘记录"}],
            },
            "realized_profit": 120,
        },
    )
    assert review.status_code == 201
    assert review.json()["outcome"] == "profitable"
    assert (
        client.get(f"/api/v1/trade-plans/{plan['id']}/review").json()["summary"]
        == "按计划执行，成交纪律良好"
    )


def test_trade_plan_must_belong_to_same_portfolio(client):
    portfolio, plan = _setup(client)
    other = client.post("/api/v1/portfolios", json={"name": "另一个组合"}).json()
    response = client.post(
        f"/api/v1/portfolios/{other['id']}/trades",
        json={
            "type": "buy",
            "trade_date": "2026-08-26",
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "price": 95,
            "quantity": 10,
            "trade_plan_id": plan["id"],
        },
    )
    assert response.status_code == 409
