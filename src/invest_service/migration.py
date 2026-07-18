"""Legacy Oreo market data migration."""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from .database import Base
from .models import Asset, AssetCategory, MarketBar


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def legacy_category(value: str, name: str) -> AssetCategory | None:
    if value == "stock":
        return AssetCategory.STOCK
    if value == "index":
        return AssetCategory.INDEX
    if value == "fund" and "ETF" in name.upper():
        return AssetCategory.ETF
    return None


def migrate_oreo(source_url: str, target_url: str) -> tuple[int, int]:
    """Copy supported assets and bars without modifying the Oreo database."""
    source = create_engine(source_url, pool_pre_ping=True)
    target = create_engine(target_url, pool_pre_ping=True)
    Base.metadata.create_all(target)
    migrated_assets = 0
    migrated_bars = 0

    try:
        with source.connect() as source_connection, Session(target) as target_session:
            legacy_assets = source_connection.execute(
                text("SELECT zs_code, code, name, category FROM assets")
            ).mappings()
            allowed_symbols = set()
            for item in legacy_assets:
                category = legacy_category(item["category"], item["name"])
                if category is None:
                    continue
                symbol = item["zs_code"].upper()
                allowed_symbols.add(symbol)
                asset = target_session.get(Asset, symbol)
                if asset is None:
                    asset = Asset(
                        symbol=symbol,
                        code=item["code"],
                        name=item["name"],
                        category=category,
                    )
                    target_session.add(asset)
                    migrated_assets += 1
                else:
                    asset.code = item["code"]
                    asset.name = item["name"]
                    asset.category = category
            target_session.flush()

            legacy_bars = source_connection.execute(
                text(
                    """
                    SELECT asset_id, date, open_price, high_price, low_price,
                           COALESCE(close_price, nav, auv) AS close_price,
                           pre_close, change, pct_change, vol, amount
                    FROM asset_market_history
                    WHERE COALESCE(close_price, nav, auv) IS NOT NULL
                    """
                )
            ).mappings()
            for item in legacy_bars:
                symbol = item["asset_id"].upper()
                if symbol not in allowed_symbols:
                    continue
                trade_date = _date(item["date"])
                bar = target_session.scalar(
                    select(MarketBar).where(
                        MarketBar.asset_symbol == symbol,
                        MarketBar.trade_date == trade_date,
                    )
                )
                if bar is None:
                    bar = MarketBar(
                        asset_symbol=symbol,
                        trade_date=trade_date,
                        close=Decimal(str(item["close_price"])),
                        source="oreo",
                    )
                    target_session.add(bar)
                    migrated_bars += 1
                bar.open = item["open_price"]
                bar.high = item["high_price"]
                bar.low = item["low_price"]
                bar.close = item["close_price"]
                bar.previous_close = item["pre_close"]
                bar.change = item["change"]
                bar.change_percent = item["pct_change"]
                bar.volume = item["vol"]
                bar.amount = item["amount"]
            target_session.commit()
    finally:
        source.dispose()
        target.dispose()
    return migrated_assets, migrated_bars
