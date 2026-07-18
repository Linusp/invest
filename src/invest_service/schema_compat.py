from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session, selectinload

from .models import OpeningSnapshot, Strategy
from .position_cycles import assign_position_ids


def prepare_legacy_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "assets" in table_names:
        columns = {item["name"] for item in inspector.get_columns("assets")}
    else:
        columns = set()
    if "assets" in table_names and "currency" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE assets ADD COLUMN currency VARCHAR(3) "
                    "NOT NULL DEFAULT 'CNY'"
                )
            )
    if "trades" in table_names:
        trade_columns = {
            item["name"] for item in inspector.get_columns("trades")
        }
        with engine.begin() as connection:
            if "position_id" not in trade_columns:
                connection.execute(
                    text("ALTER TABLE trades ADD COLUMN position_id VARCHAR(36)")
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_trades_position_id "
                    "ON trades (position_id)"
                )
            )


def migrate_legacy_data(engine: Engine) -> None:
    inspector = inspect(engine)
    required = {
        "strategies",
        "strategy_opening_snapshots",
        "strategy_opening_balances",
    }
    if not required.issubset(inspector.get_table_names()):
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO strategy_opening_balances (
                    strategy_id,
                    currency,
                    cash,
                    historical_net_contribution,
                    historical_realized_profit
                )
                SELECT
                    snapshots.strategy_id,
                    strategies.currency,
                    snapshots.cash,
                    snapshots.historical_net_contribution,
                    snapshots.historical_realized_profit
                FROM strategy_opening_snapshots AS snapshots
                JOIN strategies ON strategies.id = snapshots.strategy_id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM strategy_opening_balances AS balances
                    WHERE balances.strategy_id = snapshots.strategy_id
                )
                """
            )
        )
        if "trades" in inspector.get_table_names():
            connection.execute(
                text(
                    """
                    UPDATE trades
                    SET currency = (
                        SELECT assets.currency
                        FROM assets
                        WHERE assets.symbol = trades.asset_symbol
                    )
                    WHERE asset_symbol IS NOT NULL
                    """
                )
            )

    with engine.connect() as connection:
        has_trades = connection.execute(
            text("SELECT 1 FROM trades LIMIT 1")
        ).first() is not None
    if not has_trades:
        return

    with Session(engine) as session:
        strategies = session.scalars(
            select(Strategy).options(
                selectinload(Strategy.trades),
                selectinload(Strategy.opening_snapshot).selectinload(
                    OpeningSnapshot.positions
                ),
            )
        )
        changed = False
        for strategy in strategies:
            changed = (
                assign_position_ids(strategy.trades, strategy.opening_snapshot)
                or changed
            )
        if changed:
            session.commit()
