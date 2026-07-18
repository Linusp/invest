from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from invest_service.database import Base
from invest_service.migration import migrate_oreo
from invest_service.models import (
    Asset,
    AssetCategory,
    MarketBar,
    OpeningBalance,
    Strategy,
    Trade,
    TradeType,
)
from invest_service.schema_compat import migrate_legacy_data, prepare_legacy_schema


def test_migrates_supported_oreo_market_data(tmp_path):
    source_url = f"sqlite:///{tmp_path / 'oreo.db'}"
    target_url = f"sqlite:///{tmp_path / 'invest.db'}"
    source = create_engine(source_url)
    with source.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE assets (
                    zs_code TEXT PRIMARY KEY, code TEXT, name TEXT, category TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE asset_market_history (
                    asset_id TEXT, date DATE, open_price NUMERIC, high_price NUMERIC,
                    low_price NUMERIC, close_price NUMERIC, nav NUMERIC, auv NUMERIC,
                    pre_close NUMERIC, change NUMERIC, pct_change NUMERIC,
                    vol NUMERIC, amount NUMERIC
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO assets VALUES
                  ('600000.SH', '600000', '浦发银行', 'stock'),
                  ('510300.SH', '510300', '沪深300ETF', 'fund'),
                  ('110022.OF', '110022', '普通基金', 'fund')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO asset_market_history VALUES
                  ('600000.SH', '2026-07-10', 9, 11, 8, 10, NULL, NULL,
                   9, 1, 11.11, 100, 1000),
                  ('510300.SH', '2026-07-10', NULL, NULL, NULL, NULL, 4.5, 4.5,
                   NULL, NULL, NULL, NULL, NULL)
                """
            )
        )
    source.dispose()

    assert migrate_oreo(source_url, target_url) == (2, 2)
    # Re-running is idempotent.
    assert migrate_oreo(source_url, target_url) == (0, 0)

    target = create_engine(target_url)
    with Session(target) as session:
        assert {asset.symbol for asset in session.query(Asset)} == {
            "600000.SH",
            "510300.SH",
        }
        etf_bar = session.query(MarketBar).filter_by(asset_symbol="510300.SH").one()
        assert float(etf_bar.close) == 4.5
        assert etf_bar.source == "oreo"
    target.dispose()


def test_upgrades_legacy_currency_and_opening_snapshot_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-invest.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE assets (symbol VARCHAR(32) PRIMARY KEY, name VARCHAR(255))"
            )
        )
        connection.execute(text("INSERT INTO assets VALUES ('600000.SH', '浦发银行')"))
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

    assert "currency" in {item["name"] for item in inspect(engine).get_columns("assets")}
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
