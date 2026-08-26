from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from invest_service.database import Base
from invest_service.models import (
    Asset,
    AssetCategory,
    MarketBar,
    OpeningBalance,
    Strategy,
    Trade,
    TradeType,
    asset_identity,
)
from invest_service.schema_compat import migrate_legacy_data, prepare_legacy_schema


def test_upgrades_legacy_currency_and_opening_snapshot_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-invest.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE assets (symbol VARCHAR(32) PRIMARY KEY, name VARCHAR(255))"
            )
        )
        connection.execute(text("INSERT INTO assets VALUES ('600000.SH', '浦发银行')"))
        connection.execute(text("CREATE TABLE tags (name VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO tags VALUES ('银行')"))
        connection.execute(
            text(
                "CREATE TABLE asset_tags ("
                "asset_symbol VARCHAR(32), tag_name VARCHAR(64), "
                "PRIMARY KEY (asset_symbol, tag_name))"
            )
        )
        connection.execute(
            text("INSERT INTO asset_tags VALUES ('600000.SH', '银行')")
        )
        connection.execute(
            text(
                "CREATE TABLE strategies (id VARCHAR(36) PRIMARY KEY, currency VARCHAR(3))"
            )
        )
        connection.execute(text("INSERT INTO strategies VALUES ('s1', 'HKD')"))
        connection.execute(
            text(
                """
                CREATE TABLE strategy_opening_snapshots (
                    strategy_id VARCHAR(36) PRIMARY KEY,
                    snapshot_date DATE,
                    cash NUMERIC,
                    historical_net_contribution NUMERIC,
                    historical_realized_profit NUMERIC
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO strategy_opening_snapshots VALUES "
                "('s1', '2026-07-10', 1000, 800, 50)"
            )
        )

    prepare_legacy_schema(engine)
    Base.metadata.create_all(engine)
    migrate_legacy_data(engine)

    asset_columns = {item["name"] for item in inspect(engine).get_columns("assets")}
    assert {
        "currency",
        "is_favorite",
        "favorite_since",
        "favorite_price",
    } <= asset_columns
    tag_columns = {item["name"] for item in inspect(engine).get_columns("tags")}
    assert {"position", "is_pinned"} <= tag_columns
    asset_tag_columns = {
        item["name"] for item in inspect(engine).get_columns("asset_tags")
    }
    assert {"favorite_since", "favorite_price"} <= asset_tag_columns
    strategy_columns = {
        item["name"] for item in inspect(engine).get_columns("strategies")
    }
    assert {
        "initial_capital",
        "investment_style",
        "is_owned",
        "purpose",
        "investment_direction",
        "constraints",
        "notes",
    } <= strategy_columns
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT is_favorite FROM assets WHERE symbol = '600000.SH'")
        ).scalar_one() in (True, 1)
        assert connection.execute(
            text("SELECT is_owned FROM strategies WHERE id = 's1'")
        ).scalar_one() in (True, 1)
    with Session(engine) as session:
        balance = session.query(OpeningBalance).one()
        assert balance.currency == "HKD"
        assert float(balance.cash) == 1000
        assert float(balance.historical_realized_profit) == 50
    engine.dispose()


def test_adds_position_id_column_to_legacy_trades_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-trades.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE trades (id VARCHAR(36) PRIMARY KEY)"))

    prepare_legacy_schema(engine)

    assert {"position_id", "trade_plan_id"} <= {
        item["name"] for item in inspect(engine).get_columns("trades")
    }
    assert {"ix_trades_position_id", "ix_trades_trade_plan_id"} <= {
        item["name"] for item in inspect(engine).get_indexes("trades")
    }
    engine.dispose()


def test_migrates_symbol_primary_keys_to_category_aware_asset_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'asset-identities.db'}")
    child_tables = (
        "asset_tags",
        "market_bars",
        "strategy_opening_positions",
        "trades",
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE assets ("
                "symbol VARCHAR(32) PRIMARY KEY, category VARCHAR(16) NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO assets VALUES ('000001.SH', 'INDEX')")
        )
        for table_name in child_tables:
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    "id INTEGER PRIMARY KEY, asset_symbol VARCHAR(32))"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {table_name} (id, asset_symbol) "
                    "VALUES (1, '000001.SH')"
                )
            )
        connection.execute(
            text(
                "CREATE TABLE asset_search_index ("
                "symbol VARCHAR(32) PRIMARY KEY, category VARCHAR(16) NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO asset_search_index VALUES ('000001.SH', 'INDEX')")
        )

    prepare_legacy_schema(engine)
    prepare_legacy_schema(engine)

    expected_key = asset_identity(AssetCategory.INDEX, "000001.SH")
    with engine.connect() as connection:
        asset = connection.execute(
            text("SELECT symbol, market_symbol FROM assets")
        ).one()
        indexed = connection.execute(
            text("SELECT symbol, market_symbol FROM asset_search_index")
        ).one()
        assert tuple(asset) == (expected_key, "000001.SH")
        assert tuple(indexed) == (expected_key, "000001.SH")
        for table_name in child_tables:
            assert connection.execute(
                text(f"SELECT asset_symbol FROM {table_name}")
            ).scalar_one() == expected_key
    assert "ix_assets_market_symbol" in {
        item["name"] for item in inspect(engine).get_indexes("assets")
    }
    engine.dispose()


def test_backfills_position_ids_for_existing_trades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'position-backfill.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        asset = Asset(
            symbol="600000.SH",
            code="600000",
            name="浦发银行",
            category=AssetCategory.STOCK,
            currency="CNY",
        )
        strategy = Strategy(name="历史账户")
        session.add_all([asset, strategy])
        session.flush()
        session.add_all(
            [
                Trade(
                    strategy=strategy,
                    asset=asset,
                    type=TradeType.BUY,
                    trade_date=date(2026, 7, 1),
                    price=100,
                    quantity=1,
                    fee=0,
                    currency="CNY",
                ),
                Trade(
                    strategy=strategy,
                    asset=asset,
                    type=TradeType.SELL,
                    trade_date=date(2026, 7, 2),
                    price=110,
                    quantity=1,
                    fee=0,
                    currency="CNY",
                ),
                Trade(
                    strategy=strategy,
                    asset=asset,
                    type=TradeType.BUY,
                    trade_date=date(2026, 7, 3),
                    price=100,
                    quantity=1,
                    fee=0,
                    currency="CNY",
                ),
            ]
        )
        session.commit()

    migrate_legacy_data(engine)

    with Session(engine) as session:
        trades = list(session.query(Trade).order_by(Trade.trade_date))
        assert trades[0].position_id == trades[1].position_id
        assert trades[2].position_id != trades[1].position_id
    engine.dispose()


def test_normalizes_legacy_provider_volume_units_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'volume-normalization.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        index = Asset(
            symbol="000001.SH",
            code="000001",
            name="上证指数",
            category=AssetCategory.INDEX,
        )
        etf = Asset(
            symbol="512800.SH",
            code="512800",
            name="银行ETF",
            category=AssetCategory.ETF,
        )
        hong_kong = Asset(
            symbol="00700.HK",
            code="00700",
            name="腾讯控股",
            category=AssetCategory.STOCK,
        )
        session.add_all([index, etf, hong_kong])
        session.flush()
        session.add_all(
            [
                MarketBar(
                    asset=index,
                    trade_date=date(2026, 8, 18),
                    close=1,
                    volume=100,
                    amount=1000,
                    source="tushare",
                ),
                MarketBar(
                    asset=etf,
                    trade_date=date(2026, 8, 19),
                    close=1,
                    volume=200,
                    amount=2000,
                    source="eastmoney",
                ),
                MarketBar(
                    asset=hong_kong,
                    trade_date=date(2026, 8, 20),
                    close=1,
                    volume=300,
                    amount=3000,
                    source="eastmoney",
                ),
                MarketBar(
                    asset=index,
                    trade_date=date(2026, 8, 21),
                    close=1,
                    volume=None,
                    amount=400,
                    source="akshare",
                ),
                MarketBar(
                    asset=etf,
                    trade_date=date(2026, 8, 22),
                    close=1,
                    volume=500,
                    amount=5000,
                    source="akshare",
                ),
                MarketBar(
                    asset=etf,
                    trade_date=date(2026, 8, 23),
                    close=1,
                    volume=0,
                    amount=0,
                    source="akshare",
                ),
            ]
        )
        session.commit()

    prepare_legacy_schema(engine)
    prepare_legacy_schema(engine)

    with Session(engine) as session:
        bars = list(session.query(MarketBar).order_by(MarketBar.trade_date))
        assert [bar.volume for bar in bars] == [
            10000,
            20000,
            300,
            40000,
            500,
            None,
        ]
        assert bars[3].amount is None
        assert bars[4].amount == 5000
    engine.dispose()
