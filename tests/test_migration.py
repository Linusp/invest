from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from invest_service.database import Base
from invest_service.models import (
    Asset,
    AssetCategory,
    OpeningBalance,
    Strategy,
    Trade,
    TradeType,
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
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT is_favorite FROM assets WHERE symbol = '600000.SH'")
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

    assert "position_id" in {
        item["name"] for item in inspect(engine).get_columns("trades")
    }
    assert "ix_trades_position_id" in {
        item["name"] for item in inspect(engine).get_indexes("trades")
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
