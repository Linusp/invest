import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["INVEST_DATABASE_URL"] = "sqlite://"
os.environ["INVEST_AUTO_UPDATE_ENABLED"] = "false"

from invest_service.config import Settings
from invest_service.database import Base, get_db
from invest_service.main import create_app
from invest_service.models import AssetCategory
from invest_service.providers import MarketDataProvider, ProviderAsset, ProviderBar


class FakeMarketProvider(MarketDataProvider):
    name = "fake"

    assets = [
        ProviderAsset(
            "600000.SH",
            "600000",
            "浦发银行",
            AssetCategory.STOCK,
            "1.600000",
            default_tags=("银行",),
        ),
        ProviderAsset("510300.SH", "510300", "沪深300ETF", AssetCategory.ETF, "1.510300"),
        ProviderAsset("000300.SH", "000300", "沪深300", AssetCategory.INDEX, "1.000300"),
    ]

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        normalized = query.lower()
        return [
            asset
            for asset in self.assets
            if normalized in f"{asset.symbol} {asset.code} {asset.name}".lower()
            and (category is None or asset.category == category)
        ][:limit]

    def history(self, asset: ProviderAsset, start_date: date, end_date: date) -> list[ProviderBar]:
        values = [
            (date(2026, 7, 9), "100", "101"),
            (date(2026, 7, 10), "101", "110"),
        ]
        return [
            ProviderBar(
                trade_date=trade_date,
                open=Decimal(open_price),
                high=Decimal(close_price) + 1,
                low=Decimal(open_price) - 1,
                close=Decimal(close_price),
                previous_close=Decimal(open_price),
                change=Decimal(close_price) - Decimal(open_price),
                change_percent=Decimal("1"),
                volume=Decimal("10000"),
                amount=Decimal("1000000"),
            )
            for trade_date, open_price, close_price in values
            if start_date <= trade_date <= end_date
        ]


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def provider():
    return FakeMarketProvider()


@pytest.fixture
def client(session_factory, provider):
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite://",
            auto_update_enabled=False,
            mcp_allowed_hosts=["testserver"],
        ),
        provider,
    )
    app.state.session_factory = session_factory
    app.state.enqueue_market_update = lambda _: None

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
