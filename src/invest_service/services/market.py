from datetime import date, timedelta

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from ..models import Asset, AssetCategory, MarketBar, Tag
from ..providers import MarketDataProvider, ProviderAsset
from ..providers.base import infer_currency, infer_default_tags
from ..schemas import AssetCreate, BulkSyncResult, MarketSyncResult


class AssetNotFound(LookupError):
    pass


class MarketService:
    def __init__(self, session: Session, provider: MarketDataProvider):
        self.session = session
        self.provider = provider

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.strip().upper()

    def list_assets(
        self,
        category: AssetCategory | None = None,
        limit: int = 100,
        offset: int = 0,
        include_hidden: bool = False,
    ) -> list[Asset]:
        stmt: Select[tuple[Asset]] = (
            select(Asset).order_by(Asset.symbol).offset(offset).limit(limit)
        )
        if category:
            stmt = stmt.where(Asset.category == category)
        if not include_hidden:
            stmt = stmt.where(Asset.is_favorite.is_(True))
        return list(self.session.scalars(stmt))

    def get_asset(self, symbol: str) -> Asset:
        asset = self.session.get(Asset, self.normalize_symbol(symbol))
        if asset is None:
            raise AssetNotFound(f"Asset {symbol} was not found")
        return asset

    def register_asset(self, data: AssetCreate) -> Asset:
        symbol = self.normalize_symbol(data.symbol)
        asset = self.session.get(Asset, symbol)
        if asset is None:
            asset = Asset(
                symbol=symbol,
                code=symbol.split(".", 1)[0],
                name=data.name.strip(),
                category=data.category,
                currency=(data.currency or infer_currency(symbol)).upper(),
                provider_id=data.provider_id,
            )
            self.session.add(asset)
            self._set_tags(
                asset,
                data.tags or infer_default_tags(symbol, data.category),
            )
        else:
            asset.is_favorite = True
            asset.name = data.name.strip()
            asset.category = data.category
            if data.currency:
                asset.currency = data.currency.upper()
            if data.provider_id:
                asset.provider_id = data.provider_id
        self.session.commit()
        return asset

    def update_tags(self, symbol: str, names: list[str]) -> Asset:
        asset = self.get_asset(symbol)
        self._set_tags(asset, names)
        self.session.commit()
        return asset

    def set_favorite(self, symbol: str, is_favorite: bool) -> Asset:
        asset = self.get_asset(symbol)
        asset.is_favorite = is_favorite
        self.session.commit()
        return asset

    def ensure_default_asset(self) -> Asset:
        symbol = "000001.SH"
        asset = self.session.get(Asset, symbol)
        if asset is None:
            asset = Asset(
                symbol=symbol,
                code="000001",
                name="上证指数",
                category=AssetCategory.INDEX,
                currency="CNY",
                provider_id=symbol,
            )
            self.session.add(asset)
            self._set_tags(asset, infer_default_tags(symbol, AssetCategory.INDEX))
        elif not asset.provider_id:
            asset.provider_id = symbol
        self.session.commit()
        return asset

    def backfill_default_tags(self) -> None:
        assets = list(self.session.scalars(select(Asset)))
        for asset in assets:
            if not asset.tags:
                self._set_tags(
                    asset,
                    infer_default_tags(asset.symbol, asset.category),
                )
        self.session.commit()

    def _set_tags(self, asset: Asset, names: list[str] | tuple[str, ...]) -> None:
        tags: list[Tag] = []
        seen: set[str] = set()
        for raw_name in names:
            name = " ".join(raw_name.split())
            key = name.casefold()
            if not name or key in seen:
                continue
            if len(name) > 64:
                raise ValueError("tag must not exceed 64 characters")
            tag = self.session.get(Tag, name)
            if tag is None:
                tag = Tag(name=name)
                self.session.add(tag)
            tags.append(tag)
            seen.add(key)
        asset.tags = sorted(tags, key=lambda item: item.name.casefold())

    def search_assets(
        self,
        query: str,
        category: AssetCategory | None = None,
        limit: int = 15,
        discover: bool = True,
    ) -> list[Asset]:
        pattern = f"%{query.strip()}%"
        stmt = select(Asset).where(
            or_(Asset.symbol.ilike(pattern), Asset.code.ilike(pattern), Asset.name.ilike(pattern))
        )
        if category:
            stmt = stmt.where(Asset.category == category)
        local = list(self.session.scalars(stmt.order_by(Asset.symbol).limit(limit)))
        by_symbol = {item.symbol: item for item in local}

        if discover and len(local) < limit:
            for item in self.provider.search(query, limit=limit, category=category):
                if category and item.category != category:
                    continue
                asset = self._upsert_provider_asset(item)
                by_symbol[asset.symbol] = asset
                if len(by_symbol) >= limit:
                    break
            self.session.commit()
        return list(by_symbol.values())[:limit]

    def _upsert_provider_asset(self, item: ProviderAsset) -> Asset:
        asset = self.session.get(Asset, item.symbol)
        if asset is None:
            asset = Asset(
                symbol=item.symbol,
                code=item.code,
                name=item.name,
                category=item.category,
                currency=item.currency,
                provider_id=item.provider_id,
            )
            self.session.add(asset)
            self._set_tags(
                asset,
                item.default_tags or infer_default_tags(item.symbol, item.category),
            )
        else:
            asset.name = item.name
            asset.category = item.category
            asset.currency = item.currency
            asset.provider_id = item.provider_id
        return asset

    def _provider_asset(self, asset: Asset) -> ProviderAsset:
        if not asset.provider_id:
            matches = self.provider.search(asset.symbol, limit=15, category=asset.category)
            match = next(
                (
                    candidate
                    for candidate in matches
                    if candidate.symbol == asset.symbol or candidate.code == asset.code
                ),
                None,
            )
            if match is None:
                raise AssetNotFound(f"Provider could not resolve {asset.symbol}")
            asset.name = match.name
            asset.provider_id = match.provider_id
            asset.category = match.category
            asset.currency = match.currency
            if not asset.tags:
                self._set_tags(
                    asset,
                    match.default_tags
                    or infer_default_tags(match.symbol, match.category),
                )
        return ProviderAsset(
            symbol=asset.symbol,
            code=asset.code,
            name=asset.name,
            category=asset.category,
            provider_id=asset.provider_id,
            currency=asset.currency,
        )

    def sync_asset(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
        lookback_days: int = 10,
    ) -> MarketSyncResult:
        asset = self.get_asset(symbol)
        end_date = end_date or date.today()
        if start_date is None:
            latest = self.session.scalar(
                select(MarketBar.trade_date)
                .where(MarketBar.asset_symbol == asset.symbol)
                .order_by(MarketBar.trade_date.desc())
                .limit(1)
            )
            start_date = (
                latest - timedelta(days=lookback_days)
                if latest
                else end_date - timedelta(days=365 * 10)
            )
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        bars = self.provider.history(self._provider_asset(asset), start_date, end_date)
        existing = {
            bar.trade_date: bar
            for bar in self.session.scalars(
                select(MarketBar).where(
                    MarketBar.asset_symbol == asset.symbol,
                    MarketBar.trade_date >= start_date,
                    MarketBar.trade_date <= end_date,
                )
            )
        }
        created = 0
        updated = 0
        for item in bars:
            row = existing.get(item.trade_date)
            if row is None:
                row = MarketBar(asset_symbol=asset.symbol, trade_date=item.trade_date)
                self.session.add(row)
                created += 1
            elif not overwrite and item.trade_date < date.today() - timedelta(days=3):
                continue
            else:
                updated += 1
            row.open = item.open
            row.high = item.high
            row.low = item.low
            row.close = item.close
            row.previous_close = item.previous_close
            row.change = item.change
            row.change_percent = item.change_percent
            row.volume = item.volume
            row.amount = item.amount
            row.source = item.source or self.provider.name
        self.session.commit()
        return MarketSyncResult(
            symbol=asset.symbol,
            start_date=start_date,
            end_date=end_date,
            created=created,
            updated=updated,
        )

    def sync_all(self, lookback_days: int = 10) -> BulkSyncResult:
        succeeded = []
        failed = {}
        for asset in self.list_assets(limit=10_000, include_hidden=True):
            try:
                succeeded.append(self.sync_asset(asset.symbol, lookback_days=lookback_days))
            except Exception as exc:
                self.session.rollback()
                failed[asset.symbol] = str(exc)
        return BulkSyncResult(succeeded=succeeded, failed=failed)

    def history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 1000,
    ) -> list[MarketBar]:
        asset = self.get_asset(symbol)
        stmt = select(MarketBar).where(MarketBar.asset_symbol == asset.symbol)
        if start_date:
            stmt = stmt.where(MarketBar.trade_date >= start_date)
        if end_date:
            stmt = stmt.where(MarketBar.trade_date <= end_date)
        return list(self.session.scalars(stmt.order_by(MarketBar.trade_date.desc()).limit(limit)))[
            ::-1
        ]
