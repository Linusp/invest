from datetime import date

from invest_service.models import AssetCategory, AssetSearchIndex, asset_identity
from invest_service.providers import MarketDataProvider, ProviderAsset
from invest_service.services import MarketService


class CatalogProvider(MarketDataProvider):
    name = "catalog"

    def __init__(self, assets):
        self.assets = assets
        self.search_calls = 0

    def catalog(self):
        return self.assets

    def search(self, query, limit=15, category=None):
        self.search_calls += 1
        raise AssertionError("interactive search must not call the provider")

    def history(self, asset, start_date: date, end_date: date):
        return []


def test_search_supports_pinyin_initials_full_name_aliases_and_typos(client):
    for query in ("pfyh", "pufayinhang", "浦发银航"):
        response = client.get("/api/v1/assets/search", params={"q": query})
        assert response.status_code == 200
        assert response.json()[0]["symbol"] == "600000.SH"


def test_index_preserves_former_names_and_provider_aliases(session_factory):
    provider = CatalogProvider(
        [
            ProviderAsset(
                symbol="600000.SH",
                code="600000",
                name="浦发银行旧名",
                category=AssetCategory.STOCK,
                provider_id="600000.SH",
                aliases=("上海浦东发展银行",),
            )
        ]
    )
    with session_factory() as session:
        service = MarketService(session, provider)
        service.sync_search_index()
        provider.assets = [
            ProviderAsset(
                symbol="600000.SH",
                code="600000",
                name="浦发银行",
                category=AssetCategory.STOCK,
                provider_id="600000.SH",
            )
        ]
        service.sync_search_index()

        by_former_name = service.search_assets("浦发银行旧名")
        by_alias = service.search_assets("shanghaipudongfazhanyinhang")
        document = session.get(
            AssetSearchIndex,
            asset_identity(AssetCategory.STOCK, "600000.SH"),
        )

    assert by_former_name[0].name == "浦发银行"
    assert by_alias[0].symbol == "600000.SH"
    assert "pufayinhang" in document.pinyin_full
    assert "pfyh" in document.pinyin_initials
    assert provider.search_calls == 0


def test_search_category_filter_is_applied_to_local_index(client):
    assert (
        client.get(
            "/api/v1/assets/search",
            params={"q": "300", "category": "stock"},
        ).json()
        == []
    )
    matches = client.get(
        "/api/v1/assets/search",
        params={"q": "300", "category": "etf"},
    ).json()
    assert [item["symbol"] for item in matches] == ["510300.SH"]
