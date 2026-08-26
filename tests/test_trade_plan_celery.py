from datetime import date

from invest_service.celery_app import run_trade_plan_evaluation
from invest_service.services import MarketService


def test_celery_plan_scan_marks_matching_active_plan_triggered(
    client, session_factory, provider
):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    with session_factory() as session:
        MarketService(session, provider).sync_asset(
            "600000.SH", start_date=date(2026, 7, 1), end_date=date(2026, 7, 13)
        )
    portfolio = client.post("/api/v1/portfolios", json={"name": "扫描组合"}).json()
    plan = client.post(
        "/api/v1/trade-plans",
        json={
            "portfolio_id": portfolio["id"],
            "asset_symbol": "600000.SH",
            "asset_category": "stock",
            "action": "buy",
            "conditions": [{"type": "price_gte", "value": 100}],
            "quantity": 10,
            "valid_from": "2026-07-01",
            "valid_until": "2026-07-31",
            "status": "active",
        },
    ).json()
    result = run_trade_plan_evaluation(session_factory, date(2026, 7, 10))
    assert result["triggered"] == 1
    assert client.get(f"/api/v1/trade-plans/{plan['id']}").json()["status"] == "triggered"
