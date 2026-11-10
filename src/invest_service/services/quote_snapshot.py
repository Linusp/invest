"""实时行情快照的落库与读取。

快照只覆盖 A 股与指数（iFinD 的 stock / index 两个板块）。板块内其余类别
（ETF 等）继续走日线，因此 :meth:`QuoteSnapshotService.refresh` 会跳过它们。
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Asset, AssetCategory, QuoteSnapshot
from ..providers.ifind_mcp import IfindMcpClient, snapshot_trade_date

logger = logging.getLogger(__name__)


class QuoteSnapshotService:
    def __init__(self, session: Session):
        self.session = session

    def refresh(self, client: IfindMcpClient, favorites_only: bool = True) -> dict[str, int]:
        """抓取 A 股/指数标的的实时快照并覆盖写入。"""
        stmt = select(Asset).where(
            Asset.category.in_([AssetCategory.STOCK, AssetCategory.INDEX])
        )
        if favorites_only:
            stmt = stmt.where(Asset.is_favorite.is_(True))
        assets = list(self.session.scalars(stmt))
        # assets 表的主键是内部哈希键，行情代码在 market_symbol（ORM 的 ``symbol``）。
        key_by_symbol = {asset.symbol: asset.key for asset in assets}
        targets = [(asset.symbol, asset.category) for asset in assets]
        if not targets:
            return {"requested": 0, "stored": 0, "skipped": 0}

        try:
            quotes = client.quotes(targets)
        except Exception:
            self.session.rollback()
            raise

        stored = 0
        for quote in quotes:
            asset_key = key_by_symbol.get(quote.symbol)
            if asset_key is None:
                continue  # iFinD 可能返回简称匹配到的额外标的，只存库内已知的
            trade_date = snapshot_trade_date(quote.as_of)
            row = self.session.get(QuoteSnapshot, asset_key)
            if row is None:
                row = QuoteSnapshot(asset_key=asset_key, trade_date=trade_date)
                self.session.add(row)
            row.trade_date = trade_date
            row.as_of = quote.as_of
            row.price = quote.price
            row.change_percent = quote.change_percent
            row.volume = quote.volume
            row.amount = quote.amount
            row.turnover_rate = quote.turnover_rate
            row.pe_ttm = quote.pe_ttm
            row.source = "ifind"
            stored += 1

        # 清掉不再在采集范围内的旧快照（例如从全目录切到只抓自选）。
        if key_by_symbol:
            self.session.execute(
                delete(QuoteSnapshot).where(
                    QuoteSnapshot.asset_key.not_in(list(key_by_symbol.values()))
                )
            )
        self.session.commit()
        logger.info(
            "[quote-snapshot] requested=%s stored=%s skipped=%s",
            len(targets),
            stored,
            len(targets) - stored,
        )
        return {"requested": len(targets), "stored": stored, "skipped": len(targets) - stored}

    def latest(self, asset_key: str) -> QuoteSnapshot | None:
        return self.session.get(QuoteSnapshot, asset_key)

    def latest_price(self, asset_key: str, on_or_after: date | None = None) -> QuoteSnapshot | None:
        """返回不早于 ``on_or_after`` 的快照（默认不限制）。"""
        row = self.session.get(QuoteSnapshot, asset_key)
        if row is None:
            return None
        if on_or_after is not None and row.trade_date < on_or_after:
            return None
        return row
