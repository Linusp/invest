from datetime import date
from decimal import Decimal

from invest_service.celery_app import (
    build_beat_schedule,
    run_asset_update,
    run_market_update,
    update_asset_market_data,
    update_exchange_rates,
    update_market_data,
)
from invest_service.config import Settings
from invest_service.models import Asset, AssetCategory, MarketBar, asset_tags
from invest_service.providers.base import infer_default_tags
from invest_service.services import MarketService


def test_search_register_and_query_all_supported_asset_types(client):
    stock = client.get("/api/v1/assets/search", params={"q": "600000"}).json()
    etf = client.get("/api/v1/assets/search", params={"q": "510300"}).json()
    index = client.get("/api/v1/assets/search", params={"q": "000300"}).json()

    assert stock[0]["category"] == "stock"
    assert etf[0]["category"] == "etf"
    assert index[0]["category"] == "index"
    assert stock[0]["tags"] == [{"name": "银行"}]
    assert etf[0]["tags"] == [{"name": "ETF"}]
    assert index[0]["tags"] == [{"name": "指数"}]

    with client.app.state.session_factory() as session:
        result = MarketService(session, client.app.state.market_provider).sync_asset(
            "600000.SH"
        )
    assert result.created == 2

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
    assert response.json()["tags"] == [{"name": "ETF"}]
    assert client.get("/api/v1/assets/MISSING").status_code == 404


def test_asset_supports_multiple_editable_tags(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})

    response = client.put(
        "/api/v1/assets/600000.SH/tags",
        json={"tags": ["银行", "红利", "银行"]},
    )

    assert response.status_code == 200
    assert response.json()["tags"] == [{"name": "红利"}, {"name": "银行"}]
    listed = client.get("/api/v1/assets").json()
    stock = next(item for item in listed if item["symbol"] == "600000.SH")
    assert stock["tags"] == [{"name": "红利"}, {"name": "银行"}]


def test_asset_can_be_hidden_and_restored_without_deleting_data(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    with client.app.state.session_factory() as session:
        MarketService(session, client.app.state.market_provider).sync_asset("600000.SH")

    hidden = client.put(
        "/api/v1/assets/600000.SH/favorite",
        json={"is_favorite": False},
    )

    assert hidden.status_code == 200
    assert hidden.json()["is_favorite"] is False
    assert hidden.json()["favorite_since"] is None
    assert hidden.json()["favorite_price"] is None
    assert all(
        item["symbol"] != "600000.SH"
        for item in client.get("/api/v1/assets").json()
    )
    assert any(
        item["symbol"] == "600000.SH" and item["is_favorite"] is False
        for item in client.get("/api/v1/assets/search", params={"q": "600000"}).json()
    )
    assert len(client.get("/api/v1/assets/600000.SH/history").json()) == 2

    restored = client.put(
        "/api/v1/assets/600000.SH/favorite",
        json={"is_favorite": True},
    )

    assert restored.status_code == 200
    assert restored.json()["is_favorite"] is True
    assert restored.json()["favorite_since"] is not None
    assert restored.json()["favorite_price"] == "110.000000"
    assert any(
        item["symbol"] == "600000.SH"
        for item in client.get("/api/v1/assets").json()
    )


def test_manual_stock_uses_market_as_default_tag(client):
    response = client.post(
        "/api/v1/assets",
        json={"symbol": "00700.HK", "name": "腾讯控股", "category": "stock"},
    )

    assert response.status_code == 201
    assert response.json()["tags"] == [{"name": "港股"}]


def test_default_tag_inference():
    assert infer_default_tags("600000.SH", AssetCategory.STOCK) == ("A股",)
    assert infer_default_tags("AAPL.US", AssetCategory.STOCK) == ("美股",)
    assert infer_default_tags("600000.SH", AssetCategory.STOCK, "银行") == ("银行",)
    assert infer_default_tags("510300.SH", AssetCategory.ETF) == ("ETF",)


def test_new_asset_queues_background_market_update(client):
    queued = []
    client.app.state.enqueue_market_update = queued.append

    response = client.get("/api/v1/assets/search", params={"q": "600000"})

    assert response.status_code == 200
    assert queued == ["600000.SH"]


def test_celery_update_job_syncs_registered_assets(session_factory, provider):
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

    schedule = build_beat_schedule(
        Settings(
            database_url="sqlite://",
            auto_update_enabled=True,
            auto_update_interval_minutes=60,
        )
    )
    assert schedule["update-market-data"]["schedule"] == 3600
    result = run_market_update(session_factory, provider, lookback_days=10)
    assert len(result["succeeded"]) == 1

    with session_factory() as session:
        assert session.query(MarketBar).count() == 2


def test_celery_network_jobs_have_soft_and_hard_time_limits():
    assert (update_market_data.soft_time_limit, update_market_data.time_limit) == (900, 960)
    assert (update_asset_market_data.soft_time_limit, update_asset_market_data.time_limit) == (
        180,
        240,
    )
    assert (update_exchange_rates.soft_time_limit, update_exchange_rates.time_limit) == (
        120,
        180,
    )


def test_celery_single_asset_job(session_factory, provider):
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

    result = run_asset_update(session_factory, provider, "600000.SH", lookback_days=10)

    assert result["symbol"] == "600000.SH"
    assert result["created"] == 2


def test_tag_groups_can_be_reordered_pinned_and_summarized(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    client.get("/api/v1/assets/search", params={"q": "510300"})
    client.get("/api/v1/assets/search", params={"q": "000300"})

    tags = client.get("/api/v1/tags").json()
    names = [tag["name"] for tag in tags]
    assert {"指数", "银行", "ETF"} <= set(names)
    assert next(tag for tag in tags if tag["name"] == "银行")["asset_count"] == 1

    reordered = client.put(
        "/api/v1/tags/order",
        json={"names": list(reversed(names))},
    )
    assert reordered.status_code == 200
    assert [tag["name"] for tag in reordered.json()] == list(reversed(names))

    pinned = client.put(
        "/api/v1/tags/%E9%93%B6%E8%A1%8C/pin",
        json={"is_pinned": True},
    )
    assert pinned.status_code == 200
    assert pinned.json()[0]["name"] == "银行"
    assert pinned.json()[0]["is_pinned"] is True

    with client.app.state.session_factory() as session:
        service = MarketService(session, client.app.state.market_provider)
        service.sync_asset("600000.SH")
        session.execute(
            asset_tags.update()
            .where(
                asset_tags.c.asset_symbol == "600000.SH",
                asset_tags.c.tag_name == "银行",
            )
            .values(favorite_since=date(2026, 7, 1), favorite_price=100)
        )
        session.commit()

    updated_tags = client.put(
        "/api/v1/assets/600000.SH/tags",
        json={"tags": ["银行", "红利"]},
    )
    assert updated_tags.status_code == 200

    rows = client.get("/api/v1/tags/%E9%93%B6%E8%A1%8C/assets").json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "600000.SH"
    assert rows[0]["favorite_since"] == "2026-07-01"
    assert rows[0]["favorite_price"] == "100.000000"
    assert Decimal(rows[0]["favorite_return_percent"]) == Decimal("10")
    assert rows[0]["latest_price"] == "110.000000"
    assert rows[0]["latest_price_date"] == "2026-07-10"
    assert rows[0]["change_percent"] == "1.000000"

    later_group = client.get("/api/v1/tags/%E7%BA%A2%E5%88%A9/assets").json()
    assert later_group[0]["favorite_since"] != rows[0]["favorite_since"]
    assert later_group[0]["favorite_price"] == "110.000000"
    assert Decimal(later_group[0]["favorite_return_percent"]) == Decimal("0")


def test_web_market_group_and_asset_pages(client):
    page = client.get("/market")
    assert page.status_code == 200
    assert "自选行情" in page.text
    assert "标签分组" in page.text
    assert 'data-sort="favorite_since"' in page.text
    assert 'data-sort="favorite_return_percent"' in page.text
    assert 'id="global-market-query"' in page.text
    assert "/api/v1" in page.text
    assert "https://unpkg.com" not in page.text
    assert "https://cdn.bootcdn.net" not in page.text

    client.get("/api/v1/assets/search", params={"q": "600000"})
    detail = client.get("/market/600000.SH")
    assert detail.status_code == 200
    assert "行情首页" in detail.text
    assert "返回标签分组" not in detail.text
    assert "管理标的标签" in detail.text
    for label in (
        "本周", "本月", "近一月", "近三月", "近半年",
        "今年以来", "近一年", "近三年", "近五年",
    ):
        assert label in detail.text
    assert 'id="global-market-query"' in detail.text
    assert 'id="market-query"' not in detail.text

    legacy = client.get("/market?symbol=600000.SH", follow_redirects=False)
    assert legacy.status_code in (302, 307)
    assert legacy.headers["location"] == "/market/600000.SH"

    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/vendor/lucide-0.468.0.min.js").status_code == 200
    echarts = client.get(
        "/static/vendor/echarts-5.4.3.min.js",
        headers={"Accept-Encoding": "gzip"},
    )
    assert echarts.status_code == 200
    assert echarts.headers["Content-Encoding"] == "gzip"



def test_manual_sync_endpoints_are_not_exposed(client):
    assert client.post("/api/v1/assets/sync").status_code == 405
    assert client.post("/api/v1/assets/600000.SH/sync").status_code == 404
    assert client.post("/api/v1/exchange-rates/sync").status_code == 405
