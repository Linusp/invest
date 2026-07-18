from invest_service.models import Asset, AssetCategory, MarketBar
from invest_service.scheduler import make_scheduler


def test_search_register_sync_and_query_all_supported_asset_types(client):
    stock = client.get("/api/v1/assets/search", params={"q": "600000"}).json()
    etf = client.get("/api/v1/assets/search", params={"q": "510300"}).json()
    index = client.get("/api/v1/assets/search", params={"q": "000300"}).json()

    assert stock[0]["category"] == "stock"
    assert etf[0]["category"] == "etf"
    assert index[0]["category"] == "index"

    response = client.post(
        "/api/v1/assets/600000.SH/sync",
        params={"start_date": "2026-07-01", "end_date": "2026-07-13"},
    )
    assert response.status_code == 200
    assert response.json()["created"] == 2

    history = client.get("/api/v1/assets/600000.SH/history").json()
    assert [item["trade_date"] for item in history] == ["2026-07-09", "2026-07-10"]
    assert history[-1]["close"] == "110.000000"
    assert history[-1]["source"] == "fake"


def test_manual_asset_registration_and_missing_asset(client):
    response = client.post(
        "/api/v1/assets",
        json={
            "symbol": "159915.SZ",
            "name": "创业板ETF",
            "category": "etf",
            "provider_id": "0.159915",
        },
    )
    assert response.status_code == 201
    assert response.json()["code"] == "159915"
    assert client.get("/api/v1/assets/MISSING").status_code == 404


def test_automatic_update_job_syncs_registered_assets(session_factory, provider):
    with session_factory() as session:
        session.add(
            Asset(
                symbol="600000.SH",
                code="600000",
                name="浦发银行",
                category=AssetCategory.STOCK,
                provider_id="1.600000",
            )
        )
        session.commit()

    scheduler = make_scheduler(session_factory, provider, interval_minutes=60, lookback_days=10)
    job = scheduler.get_job("market-data-update")
    assert str(job.trigger) == "interval[1:00:00]"
    job.func()

    with session_factory() as session:
        assert session.query(MarketBar).count() == 2


def test_web_market_page_and_legacy_redirect(client):
    page = client.get("/market")
    assert page.status_code == 200
    assert "市场行情" in page.text
    assert "/api/v1" in page.text
    assert client.get("/static/app.css").status_code == 200

    legacy = client.get("/invest/chart?code=600000.SH", follow_redirects=False)
    assert legacy.status_code in (302, 307)
    assert legacy.headers["location"] == "/market?code=600000.SH"
