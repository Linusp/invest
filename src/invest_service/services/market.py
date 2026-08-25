from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from ..models import (
    Asset,
    AssetCategory,
    AssetSearchIndex,
    MarketBar,
    OpeningPosition,
    Tag,
    Trade,
    asset_identity,
    asset_tags,
)
from ..providers import MarketDataProvider, ProviderAsset
from ..providers.base import infer_currency, infer_default_tags
from ..schemas import (
    AssetCreate,
    AssetMarketSummary,
    BulkSyncResult,
    MarketSyncResult,
    TagGroupRead,
)
from .search_index import AssetSearchIndexService, SearchIndexSyncResult


class AssetNotFound(LookupError):
    pass


class TagNotFound(LookupError):
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

    def get_asset(
        self,
        symbol: str,
        category: AssetCategory | None = None,
    ) -> Asset:
        symbol = self.normalize_symbol(symbol)
        if category is not None:
            asset = self.session.get(Asset, asset_identity(category, symbol))
        else:
            matches = list(
                self.session.scalars(
                    select(Asset).where(Asset.symbol == symbol).limit(2)
                )
            )
            if len(matches) > 1:
                raise ValueError(
                    f"Asset {symbol} is ambiguous; specify stock, etf, or index"
                )
            asset = matches[0] if matches else None
        if asset is None:
            raise AssetNotFound(f"Asset {symbol} was not found")
        return asset

    def register_asset(self, data: AssetCreate) -> Asset:
        symbol = self.normalize_symbol(data.symbol)
        key = asset_identity(data.category, symbol)
        asset = self.session.get(Asset, key)
        if asset is None:
            asset = Asset(
                key=key,
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
            if not asset.is_favorite:
                self._set_favorite(asset, True)
            asset.name = data.name.strip()
            asset.category = data.category
            if data.currency:
                asset.currency = data.currency.upper()
            if data.provider_id:
                asset.provider_id = data.provider_id
        self.session.flush()
        AssetSearchIndexService(self.session).upsert_provider_asset(
            ProviderAsset(
                symbol=asset.symbol,
                code=asset.code,
                name=asset.name,
                category=asset.category,
                provider_id=asset.provider_id or asset.symbol,
                currency=asset.currency,
                default_tags=tuple(tag.name for tag in asset.tags),
            )
        )
        self.session.commit()
        return asset

    def update_tags(
        self,
        symbol: str,
        names: list[str],
        category: AssetCategory | None = None,
    ) -> Asset:
        asset = self.get_asset(symbol, category)
        self._set_tags(asset, names)
        self.session.flush()
        self._capture_tag_prices(asset)
        self.session.commit()
        return asset

    def set_favorite(
        self,
        symbol: str,
        is_favorite: bool,
        category: AssetCategory | None = None,
    ) -> Asset:
        asset = self.get_asset(symbol, category)
        self._set_favorite(asset, is_favorite)
        self.session.commit()
        return asset

    def _set_favorite(self, asset: Asset, is_favorite: bool) -> None:
        was_favorite = asset.is_favorite
        if not is_favorite:
            asset.is_favorite = False
            asset.favorite_since = None
            asset.favorite_price = None
            return
        if not asset.is_favorite or asset.favorite_since is None:
            asset.favorite_since = date.today()
            asset.favorite_price = None
        asset.is_favorite = True
        self._capture_favorite_price(asset)
        if not was_favorite:
            self.session.flush()
            self._reset_tag_snapshots(asset)

    def _capture_favorite_price(self, asset: Asset) -> None:
        if not asset.is_favorite or asset.favorite_price is not None:
            return
        favorite_since = asset.favorite_since or date.today()
        asset.favorite_since = favorite_since
        asset.favorite_price = self._price_on_or_before(
            asset.key,
            favorite_since,
        )

    def _price_on_or_before(
        self,
        asset_key: str,
        snapshot_date: date,
    ) -> Decimal | None:
        price = self.session.scalar(
            select(MarketBar.close)
            .where(
                MarketBar.asset_key == asset_key,
                MarketBar.trade_date <= snapshot_date,
            )
            .order_by(MarketBar.trade_date.desc())
            .limit(1)
        )
        if price is None:
            price = self.session.scalar(
                select(MarketBar.close)
                .where(MarketBar.asset_key == asset_key)
                .order_by(MarketBar.trade_date.asc())
                .limit(1)
            )
        return price

    def _capture_tag_prices(
        self,
        asset: Asset,
        default_since: date | None = None,
    ) -> None:
        memberships = self.session.execute(
            select(
                asset_tags.c.tag_name,
                asset_tags.c.favorite_since,
                asset_tags.c.favorite_price,
            ).where(asset_tags.c.asset_symbol == asset.key)
        ).all()
        fallback_since = (
            default_since
            or asset.favorite_since
            or (asset.created_at.date() if asset.created_at else date.today())
        )
        for tag_name, favorite_since, favorite_price in memberships:
            if favorite_since is not None and favorite_price is not None:
                continue
            snapshot_date = favorite_since or fallback_since
            snapshot_price = favorite_price
            if snapshot_price is None:
                snapshot_price = self._price_on_or_before(
                    asset.key,
                    snapshot_date,
                )
            self.session.execute(
                update(asset_tags)
                .where(
                    asset_tags.c.asset_symbol == asset.key,
                    asset_tags.c.tag_name == tag_name,
                )
                .values(
                    favorite_since=snapshot_date,
                    favorite_price=snapshot_price,
                )
            )

    def _reset_tag_snapshots(self, asset: Asset) -> None:
        snapshot_date = date.today()
        snapshot_price = self._price_on_or_before(asset.key, snapshot_date)
        self.session.execute(
            update(asset_tags)
            .where(asset_tags.c.asset_symbol == asset.key)
            .values(
                favorite_since=snapshot_date,
                favorite_price=snapshot_price,
            )
        )

    def ensure_default_asset(self) -> Asset:
        symbol = "000001.SH"
        key = asset_identity(AssetCategory.INDEX, symbol)
        asset = self.session.get(Asset, key)
        if asset is None:
            asset = Asset(
                key=key,
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

    def backfill_market_metadata(self) -> None:
        tags = list(self.session.scalars(select(Tag).order_by(Tag.position, Tag.name)))
        pinned_seen = False
        for position, tag in enumerate(tags):
            tag.position = position
            if tag.is_pinned:
                if pinned_seen:
                    tag.is_pinned = False
                pinned_seen = True
        assets = list(self.session.scalars(select(Asset)))
        for asset in assets:
            fallback_since = asset.created_at.date() if asset.created_at else date.today()
            if asset.is_favorite:
                if asset.favorite_since is None:
                    asset.favorite_since = fallback_since
                self._capture_favorite_price(asset)
            self.session.flush()
            self._capture_tag_prices(
                asset,
                asset.favorite_since or fallback_since,
            )
        self.session.commit()

    def list_tags(self) -> list[TagGroupRead]:
        tags = list(
            self.session.scalars(select(Tag).order_by(Tag.is_pinned.desc(), Tag.position, Tag.name))
        )
        return [
            TagGroupRead(
                name=tag.name,
                position=tag.position,
                is_pinned=tag.is_pinned,
                asset_count=sum(asset.is_favorite for asset in tag.assets),
            )
            for tag in tags
            if any(asset.is_favorite for asset in tag.assets)
        ]

    def reorder_tags(self, names: list[str]) -> list[TagGroupRead]:
        tags = list(self.session.scalars(select(Tag)))
        by_name = {tag.name: tag for tag in tags}
        unknown = [name for name in names if name not in by_name]
        if unknown:
            raise TagNotFound(f"Tag {unknown[0]} was not found")
        ordered = [by_name[name] for name in names]
        ordered.extend(
            sorted(
                (tag for tag in tags if tag.name not in names),
                key=lambda item: (item.position, item.name),
            )
        )
        for position, tag in enumerate(ordered):
            tag.position = position
        self.session.commit()
        return self.list_tags()

    def set_tag_pinned(self, name: str, is_pinned: bool) -> list[TagGroupRead]:
        tag = self.session.get(Tag, name)
        if tag is None:
            raise TagNotFound(f"Tag {name} was not found")
        if is_pinned:
            for item in self.session.scalars(select(Tag).where(Tag.is_pinned.is_(True))):
                item.is_pinned = False
        tag.is_pinned = is_pinned
        self.session.commit()
        return self.list_tags()

    def assets_for_tag(
        self,
        name: str,
    ) -> list[tuple[Asset, date | None, Decimal | None]]:
        tag = self.session.get(Tag, name)
        if tag is None:
            raise TagNotFound(f"Tag {name} was not found")
        rows = self.session.execute(
            select(
                Asset,
                asset_tags.c.favorite_since,
                asset_tags.c.favorite_price,
            )
            .join(asset_tags, asset_tags.c.asset_symbol == Asset.key)
            .where(
                asset_tags.c.tag_name == name,
                Asset.is_favorite.is_(True),
            )
            .order_by(Asset.name, Asset.symbol)
        ).all()
        return [
            (asset, favorite_since, favorite_price)
            for asset, favorite_since, favorite_price in rows
        ]

    def summarize_assets(
        self,
        assets: list[tuple[Asset, date | None, Decimal | None]],
    ) -> list[AssetMarketSummary]:
        summaries = []
        for asset, favorite_since, favorite_price in assets:
            latest = self.session.scalar(
                select(MarketBar)
                .where(MarketBar.asset_key == asset.key)
                .order_by(MarketBar.trade_date.desc())
                .limit(1)
            )
            favorite_return = None
            change = latest.change if latest else None
            change_percent = latest.change_percent if latest else None
            if latest is not None and latest.previous_close:
                if change is None:
                    change = latest.close - latest.previous_close
                if change_percent is None:
                    change_percent = change / latest.previous_close * 100
            if latest is not None and favorite_price:
                favorite_return = (latest.close - favorite_price) / favorite_price * 100
            summaries.append(
                AssetMarketSummary(
                    symbol=asset.symbol,
                    name=asset.name,
                    category=asset.category,
                    currency=asset.currency,
                    favorite_since=favorite_since,
                    favorite_price=favorite_price,
                    favorite_return_percent=favorite_return,
                    latest_price=latest.close if latest else None,
                    latest_price_date=latest.trade_date if latest else None,
                    change=change,
                    change_percent=change_percent,
                )
            )
        return summaries

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
                next_position = self.session.scalar(
                    select(func.coalesce(func.max(Tag.position), -1) + 1)
                )
                tag = Tag(name=name, position=next_position)
                self.session.add(tag)
            tags.append(tag)
            seen.add(key)
        asset.tags = sorted(tags, key=lambda item: item.name.casefold())

    def search_assets(
        self,
        query: str,
        category: AssetCategory | None = None,
        limit: int = 15,
    ) -> list[Asset]:
        index = AssetSearchIndexService(self.session)
        documents = index.search(query, category, limit)
        assets = [self._materialize_search_document(document) for document in documents]
        if assets:
            self.session.commit()
        return assets

    def sync_search_index(self) -> SearchIndexSyncResult:
        return AssetSearchIndexService(self.session).sync_catalog(self.provider)

    def seed_search_index(self) -> int:
        index = AssetSearchIndexService(self.session)
        count = index.seed_assets()
        self.session.commit()
        return count

    def _materialize_search_document(self, document: AssetSearchIndex) -> Asset:
        asset = self.session.get(Asset, document.key)
        is_new = asset is None
        if asset is None:
            asset = Asset(
                key=document.key,
                symbol=document.symbol,
                is_favorite=False,
                favorite_since=None,
                favorite_price=None,
            )
            self.session.add(asset)
        asset.code = document.code
        asset.name = document.name
        asset.category = document.category
        asset.currency = document.currency
        asset.provider_id = document.provider_id
        if is_new:
            self._set_tags(
                asset,
                AssetSearchIndexService.default_tags(document)
                or infer_default_tags(document.symbol, document.category),
            )
            # The Asset model defaults favorite_since for manually registered assets.
            # Search hits are hidden, so clear that insert default after the first flush.
            self.session.flush()
            asset.favorite_since = None
        return asset

    def _provider_asset(self, asset: Asset) -> ProviderAsset:
        if not asset.provider_id:
            document = self.session.get(AssetSearchIndex, asset.key)
            match = (
                ProviderAsset(
                    symbol=document.symbol,
                    code=document.code,
                    name=document.name,
                    category=document.category,
                    provider_id=document.provider_id or document.symbol,
                    currency=document.currency,
                    default_tags=tuple(AssetSearchIndexService.default_tags(document)),
                    aliases=tuple(AssetSearchIndexService.aliases(document)),
                )
                if document is not None
                else None
            )
            if match is None:
                raise AssetNotFound(f"Search index could not resolve {asset.symbol}")
            asset.name = match.name
            asset.provider_id = match.provider_id
            asset.category = match.category
            asset.currency = match.currency
            if not asset.tags:
                self._set_tags(
                    asset,
                    match.default_tags or infer_default_tags(match.symbol, match.category),
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
        category: AssetCategory | None = None,
    ) -> MarketSyncResult:
        asset = self.get_asset(symbol, category)
        end_date = end_date or date.today()
        if start_date is None:
            latest = self.session.scalar(
                select(MarketBar.trade_date)
                .where(MarketBar.asset_key == asset.key)
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
                    MarketBar.asset_key == asset.key,
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
                row = MarketBar(asset_key=asset.key, trade_date=item.trade_date)
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
        self.session.flush()
        self._capture_favorite_price(asset)
        self._capture_tag_prices(asset)
        self.session.commit()
        return MarketSyncResult(
            symbol=asset.symbol,
            category=asset.category,
            start_date=start_date,
            end_date=end_date,
            created=created,
            updated=updated,
        )

    def sync_all(self, lookback_days: int = 10) -> BulkSyncResult:
        succeeded = []
        failed = {}
        assets = list(
            self.session.scalars(
                select(Asset)
                .where(
                    (Asset.is_favorite.is_(True))
                    | Asset.key.in_(
                        select(Trade.asset_key).where(Trade.asset_key.is_not(None))
                    )
                    | Asset.key.in_(select(OpeningPosition.asset_key))
                )
                .order_by(Asset.symbol)
            )
        )
        for asset in assets:
            try:
                succeeded.append(
                    self.sync_asset(
                        asset.symbol,
                        lookback_days=lookback_days,
                        category=asset.category,
                    )
                )
            except Exception as exc:
                self.session.rollback()
                failed[f"{asset.category.value}:{asset.symbol}"] = str(exc)
        return BulkSyncResult(succeeded=succeeded, failed=failed)

    def history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 1000,
        category: AssetCategory | None = None,
    ) -> list[MarketBar]:
        asset = self.get_asset(symbol, category)
        stmt = select(MarketBar).where(MarketBar.asset_key == asset.key)
        if start_date:
            stmt = stmt.where(MarketBar.trade_date >= start_date)
        if end_date:
            stmt = stmt.where(MarketBar.trade_date <= end_date)
        return list(self.session.scalars(stmt.order_by(MarketBar.trade_date.desc()).limit(limit)))[
            ::-1
        ]
