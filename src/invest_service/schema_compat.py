from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    Index,
    MetaData,
    String,
    Table,
    delete,
    func,
    insert,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session, selectinload

from .models import (
    AssetCategory,
    OpeningSnapshot,
    Strategy,
    asset_identity,
    utcnow,
)
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
    if "assets" in table_names and "is_favorite" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE assets ADD COLUMN is_favorite BOOLEAN "
                    "NOT NULL DEFAULT TRUE"
                )
            )
    if "assets" in table_names and "favorite_since" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE assets ADD COLUMN favorite_since DATE")
            )
    if "assets" in table_names and "favorite_price" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE assets ADD COLUMN favorite_price NUMERIC(20, 6)")
            )
    if "assets" in table_names and "market_symbol" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE assets ADD COLUMN market_symbol VARCHAR(32)")
            )
    if "asset_search_index" in table_names:
        search_columns = {
            item["name"]
            for item in inspector.get_columns("asset_search_index")
        }
        if "market_symbol" not in search_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE asset_search_index "
                        "ADD COLUMN market_symbol VARCHAR(32)"
                    )
                )
    if "tags" in table_names:
        tag_columns = {item["name"] for item in inspector.get_columns("tags")}
        with engine.begin() as connection:
            if "position" not in tag_columns:
                connection.execute(
                    text(
                        "ALTER TABLE tags ADD COLUMN position INTEGER "
                        "NOT NULL DEFAULT 0"
                    )
                )
            if "is_pinned" not in tag_columns:
                connection.execute(
                    text(
                        "ALTER TABLE tags ADD COLUMN is_pinned BOOLEAN "
                        "NOT NULL DEFAULT FALSE"
                    )
                )
            if "is_visible" not in tag_columns:
                connection.execute(
                    text(
                        "ALTER TABLE tags ADD COLUMN is_visible BOOLEAN "
                        "NOT NULL DEFAULT FALSE"
                    )
                )
                if "asset_tags" in table_names:
                    connection.execute(
                        text(
                            "UPDATE tags SET is_visible = TRUE WHERE EXISTS ("
                            "SELECT 1 FROM asset_tags "
                            "WHERE asset_tags.tag_name = tags.name)"
                        )
                    )
    if "asset_tags" in table_names:
        asset_tag_columns = {
            item["name"] for item in inspector.get_columns("asset_tags")
        }
        with engine.begin() as connection:
            if "favorite_since" not in asset_tag_columns:
                connection.execute(
                    text("ALTER TABLE asset_tags ADD COLUMN favorite_since DATE")
                )
            if "favorite_price" not in asset_tag_columns:
                connection.execute(
                    text(
                        "ALTER TABLE asset_tags ADD COLUMN "
                        "favorite_price NUMERIC(20, 6)"
                    )
                )
    if "strategies" in table_names:
        strategy_columns = {
            item["name"] for item in inspector.get_columns("strategies")
        }
        additions = {
            "investment_style": "VARCHAR(64)",
            "is_owned": "BOOLEAN NOT NULL DEFAULT TRUE",
            "purpose": "TEXT",
            "investment_direction": "TEXT",
            "constraints": "TEXT",
            "notes": "TEXT",
        }
        with engine.begin() as connection:
            for name, sql_type in additions.items():
                if name not in strategy_columns:
                    connection.execute(
                        text(f"ALTER TABLE strategies ADD COLUMN {name} {sql_type}")
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
            if "trade_plan_id" not in trade_columns:
                connection.execute(
                    text("ALTER TABLE trades ADD COLUMN trade_plan_id VARCHAR(36)")
                )
        trades = Table("trades", MetaData(), autoload_with=engine)
        Index("ix_trades_position_id", trades.c.position_id).create(
            bind=engine, checkfirst=True
        )
        Index("ix_trades_trade_plan_id", trades.c.trade_plan_id).create(
            bind=engine, checkfirst=True
        )
    _migrate_asset_identities(engine)
    _create_asset_identity_indexes(engine)
    _normalize_legacy_market_volume(engine)


def _migrate_asset_identities(engine: Engine) -> None:
    table_names = set(inspect(engine).get_table_names())
    if "assets" in table_names:
        asset_columns = {
            item["name"] for item in inspect(engine).get_columns("assets")
        }
        if {"symbol", "market_symbol", "category"} <= asset_columns:
            _migrate_identity_table(
                engine,
                "assets",
                child_tables=(
                    "asset_tags",
                    "market_bars",
                    "strategy_opening_positions",
                    "trades",
                ),
            )
    if "asset_search_index" in table_names:
        _migrate_identity_table(engine, "asset_search_index")


def _migrate_identity_table(
    engine: Engine,
    table_name: str,
    child_tables: tuple[str, ...] = (),
) -> None:
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    available_tables = set(inspect(engine).get_table_names())
    children = [
        Table(name, metadata, autoload_with=engine)
        for name in child_tables
        if name in available_tables
    ]
    with engine.begin() as connection:
        rows = connection.execute(select(table)).mappings().all()
        for row in rows:
            old_key = str(row["symbol"])
            market_symbol = str(row.get("market_symbol") or old_key).strip().upper()
            raw_category = str(row["category"])
            try:
                category = AssetCategory(raw_category.lower())
            except ValueError:
                category = AssetCategory[raw_category.upper()]
            new_key = asset_identity(category, market_symbol)
            if old_key == new_key:
                if not row.get("market_symbol"):
                    connection.execute(
                        update(table)
                        .where(table.c.symbol == old_key)
                        .values(market_symbol=market_symbol)
                    )
                continue
            exists = connection.execute(
                select(table.c.symbol).where(table.c.symbol == new_key)
            ).first()
            if exists is None:
                values = dict(row)
                values["symbol"] = new_key
                values["market_symbol"] = market_symbol
                connection.execute(insert(table).values(**values))
            for child in children:
                if "asset_symbol" in child.c:
                    connection.execute(
                        update(child)
                        .where(child.c.asset_symbol == old_key)
                        .values(asset_symbol=new_key)
                    )
            connection.execute(delete(table).where(table.c.symbol == old_key))


def _create_asset_identity_indexes(engine: Engine) -> None:
    table_names = set(inspect(engine).get_table_names())
    for table_name in ("assets", "asset_search_index"):
        if table_name not in table_names:
            continue
        table = Table(table_name, MetaData(), autoload_with=engine)
        if "market_symbol" not in table.c:
            continue
        Index(
            f"ix_{table_name}_market_symbol",
            table.c.market_symbol,
        ).create(bind=engine, checkfirst=True)


def _normalize_legacy_market_volume(engine: Engine) -> None:
    """Convert historical provider-specific lots to canonical shares/units once."""
    migration_name = "normalize-market-volume-v1"
    metadata = MetaData()
    migrations = Table(
        "service_data_migrations",
        metadata,
        Column("name", String(128), primary_key=True),
        Column("applied_at", DateTime(timezone=True), nullable=False),
    )
    migrations.create(bind=engine, checkfirst=True)

    table_names = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        if connection.execute(
            select(migrations.c.name).where(migrations.c.name == migration_name)
        ).first():
            return

        if {"assets", "market_bars"} <= table_names:
            data = MetaData()
            assets = Table("assets", data, autoload_with=connection)
            bars = Table("market_bars", data, autoload_with=connection)
            required_asset_columns = {"symbol", "market_symbol", "category"}
            required_bar_columns = {
                "asset_symbol",
                "volume",
                "amount",
                "source",
            }
            asset_columns = {column.name for column in assets.c}
            bar_columns = {column.name for column in bars.c}
            if (
                required_asset_columns <= asset_columns
                and required_bar_columns <= bar_columns
            ):
                connection.execute(
                    update(bars)
                    .where(
                        bars.c.source == "tushare",
                        bars.c.volume.is_not(None),
                    )
                    .values(volume=bars.c.volume * 100)
                )
                mainland_assets = select(assets.c.symbol).where(
                    or_(
                        assets.c.market_symbol.endswith(".SH"),
                        assets.c.market_symbol.endswith(".SZ"),
                        assets.c.market_symbol.endswith(".BJ"),
                    )
                )
                connection.execute(
                    update(bars)
                    .where(
                        bars.c.source == "eastmoney",
                        bars.c.volume.is_not(None),
                        bars.c.asset_symbol.in_(mainland_assets),
                    )
                    .values(volume=bars.c.volume * 100)
                )
                index_assets = select(assets.c.symbol).where(
                    func.lower(assets.c.category) == "index"
                )
                connection.execute(
                    update(bars)
                    .where(
                        bars.c.source == "akshare",
                        bars.c.volume.is_(None),
                        bars.c.amount.is_not(None),
                        bars.c.asset_symbol.in_(index_assets),
                    )
                    .values(volume=bars.c.amount * 100, amount=None)
                )
                connection.execute(
                    update(bars)
                    .where(bars.c.volume <= 0)
                    .values(volume=None)
                )

        connection.execute(
            insert(migrations).values(name=migration_name, applied_at=utcnow())
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
