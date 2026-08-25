import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from invest_service.config import Settings
from invest_service.database import make_engine, make_session_factory
from invest_service.main import create_app
from invest_service.models import Asset, AssetCategory, asset_identity
from invest_service.providers import ProviderAsset


@pytest.mark.parametrize(
    ("configured", "driver"),
    [
        ("sqlite:///./invest.db", "sqlite"),
        ("postgresql://user:pass@localhost/invest", "postgresql+psycopg"),
        ("postgres://user:pass@localhost/invest", "postgresql+psycopg"),
        ("mysql://user:pass@localhost/invest", "mysql+pymysql"),
    ],
)
def test_database_url_selects_supported_driver(configured, driver):
    settings = Settings(database_url=configured)
    engine = make_engine(settings.database_url)
    assert engine.url.drivername == driver
    engine.dispose()


def test_create_app_uses_injected_database_url(tmp_path, provider):
    database_path = tmp_path / "configured.db"
    url = f"sqlite:///{database_path}"
    app = create_app(
        Settings(database_url=url, auto_update_enabled=False),
        provider=provider,
    )

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}

    engine = make_engine(url)
    assert {"assets", "tags", "asset_tags"} <= set(inspect(engine).get_table_names())
    with make_session_factory(engine)() as session:
        default_asset = session.get(
            Asset,
            asset_identity(AssetCategory.INDEX, "000001.SH"),
        )
        assert default_asset is not None
        assert default_asset.name == "上证指数"
        assert default_asset.provider_id == "000001.SH"
        assert default_asset.is_favorite is True
        assert [tag.name for tag in default_asset.tags] == ["指数"]
    engine.dispose()


def test_rejects_unsupported_database_backend():
    with pytest.raises(ValueError, match="Unsupported database backend"):
        make_engine("oracle://user:pass@localhost/invest")


def test_missing_tushare_token_keeps_local_search_available(tmp_path, monkeypatch):
    class FreeProvider:
        name = "free"

        def search(self, query, limit=15, category=None):
            raise AssertionError("interactive search must not call a remote provider")

        def catalog(self):
            return [
                ProviderAsset(
                    symbol="600000.SH",
                    code="600000",
                    name="浦发银行",
                    category=AssetCategory.STOCK,
                    provider_id="1.600000",
                )
            ]

    monkeypatch.setattr(
        "invest_service.main.make_market_provider",
        lambda _: FreeProvider(),
    )
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'missing-token.db'}",
            auto_update_enabled=False,
            market_provider="tushare",
            tushare_token=None,
            mcp_allowed_hosts=["testserver"],
        )
    )
    app.state.enqueue_market_update = lambda _: None

    with TestClient(app) as client:
        with app.state.session_factory() as session:
            from invest_service.services import MarketService

            MarketService(session, app.state.market_provider).sync_search_index()
        page = client.get("/market")
        search = client.get("/api/v1/assets/search", params={"q": "600000"})

    assert "未配置 Tushare Token" in page.text
    assert search.json()[0]["symbol"] == "600000.SH"
    assert "X-Invest-Warning" not in search.headers
