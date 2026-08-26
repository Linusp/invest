from __future__ import annotations

import hashlib
import json
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..commentary_content import (
    content_to_html,
    content_to_markdown,
    normalize_content,
)
from ..models import (
    Asset,
    AssetCategory,
    Commentary,
    Information,
    InformationType,
    MarketScope,
    asset_identity,
    utcnow,
)
from ..schemas import InformationAssetRef, InformationCreate, InformationRead
from .commentary import CommentaryNotFound


class InformationNotFound(LookupError):
    pass


class InformationService:
    def __init__(self, session: Session):
        self.session = session

    def submit(self, data: InformationCreate) -> InformationRead:
        fingerprint = data.content_fingerprint or self._fingerprint(data.url)
        existing = self.session.scalar(
            select(Information)
            .options(*self._loads())
            .where(Information.content_fingerprint == fingerprint)
        )
        scopes, assets = self._resolve_associations(data)
        normalized = normalize_content(data.content, data.content_format)
        full_content = (
            normalize_content(data.full_content, data.full_content_format)
            if data.full_content is not None
            else None
        )
        if existing is not None:
            existing.fetched_at = utcnow()
            existing.summary = data.summary or existing.summary
            existing.content = normalized
            existing.full_content = full_content or existing.full_content
            existing.search_context = data.search_context or existing.search_context
            existing.importance = max(existing.importance, data.importance)
            existing.confidence = (
                data.confidence
                if data.confidence is not None
                else existing.confidence
            )
            existing.market_scopes = sorted(
                {*existing.market_scopes, *scopes}, key=lambda item: item.code
            )
            existing.assets = sorted(
                {*existing.assets, *assets}, key=lambda item: (item.category.value, item.symbol)
            )
            self.session.commit()
            return self._read(existing)
        information = Information(
            title=data.title.strip(),
            source_name=data.source_name.strip(),
            url=self._normalize_url(data.url),
            published_at=data.published_at,
            summary=data.summary,
            content=normalized,
            full_content=full_content,
            language=data.language,
            information_type=data.information_type,
            search_context=data.search_context,
            content_fingerprint=fingerprint,
            importance=data.importance,
            confidence=data.confidence,
            market_scopes=scopes,
            assets=assets,
        )
        self.session.add(information)
        self.session.commit()
        return self._read(information)

    def list(
        self,
        market_scope_code: str | None = None,
        asset_symbol: str | None = None,
        asset_category: AssetCategory | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
        source_name: str | None = None,
        information_type: InformationType | None = None,
        query: str | None = None,
        min_importance: int | None = None,
        referenced: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[InformationRead]:
        statement = select(Information).options(*self._loads())
        if market_scope_code:
            statement = statement.where(
                Information.market_scopes.any(
                    MarketScope.code == market_scope_code.strip().upper()
                )
            )
        if bool(asset_symbol) != bool(asset_category):
            raise ValueError("asset_symbol and asset_category must be provided together")
        if asset_symbol and asset_category:
            statement = statement.where(
                Information.assets.any(
                    Asset.key == asset_identity(asset_category, asset_symbol)
                )
            )
        if published_from:
            statement = statement.where(Information.published_at >= published_from)
        if published_to:
            statement = statement.where(Information.published_at <= published_to)
        if source_name:
            statement = statement.where(Information.source_name == source_name)
        if information_type:
            statement = statement.where(
                Information.information_type == information_type
            )
        if min_importance is not None:
            statement = statement.where(Information.importance >= min_importance)
        if referenced is not None:
            condition = Information.commentaries.any()
            statement = statement.where(condition if referenced else ~condition)
        statement = statement.order_by(
            Information.published_at.desc(), Information.created_at.desc()
        )
        items = list(self.session.scalars(statement).unique())
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in self._search_text(item)]
        return [self._read(item) for item in items[offset : offset + limit]]

    def get(self, information_id: str) -> InformationRead:
        return self._read(self._get_model(information_id))

    def link_commentary(self, commentary_id: str, information_id: str) -> None:
        commentary = self._get_commentary(commentary_id)
        information = self._get_model(information_id)
        if commentary not in information.commentaries:
            information.commentaries.append(commentary)
            self.session.commit()

    def unlink_commentary(self, commentary_id: str, information_id: str) -> None:
        commentary = self._get_commentary(commentary_id)
        information = self._get_model(information_id)
        if commentary in information.commentaries:
            information.commentaries.remove(commentary)
            self.session.commit()

    def for_commentary(self, commentary_id: str) -> list[InformationRead]:
        commentary = self._get_commentary(commentary_id)
        items = self.session.scalars(
            select(Information)
            .join(Information.commentaries)
            .options(*self._loads())
            .where(Commentary.id == commentary.id)
            .order_by(Information.published_at.desc())
        ).unique()
        return [self._read(item) for item in items]

    def _get_model(self, information_id: str) -> Information:
        information = self.session.scalar(
            select(Information)
            .options(*self._loads())
            .where(Information.id == information_id)
        )
        if information is None:
            raise InformationNotFound(f"Information {information_id} was not found")
        return information

    def _get_commentary(self, commentary_id: str) -> Commentary:
        commentary = self.session.get(Commentary, commentary_id)
        if commentary is None:
            raise CommentaryNotFound(f"Commentary {commentary_id} was not found")
        return commentary

    def _resolve_associations(
        self, data: InformationCreate
    ) -> tuple[list[MarketScope], list[Asset]]:
        scopes = []
        for code in data.market_scope_codes:
            scope = self.session.get(MarketScope, code)
            if scope is None:
                raise ValueError(f"Market scope {code} was not found")
            scopes.append(scope)
        assets = []
        for reference in data.assets:
            key = asset_identity(reference.category, reference.symbol)
            asset = self.session.get(Asset, key)
            if asset is None:
                raise ValueError(
                    f"Asset {reference.category.value}:{reference.symbol} was not found"
                )
            assets.append(asset)
        return scopes, assets

    @staticmethod
    def _read(information: Information) -> InformationRead:
        return InformationRead(
            id=information.id,
            title=information.title,
            source_name=information.source_name,
            url=information.url,
            published_at=information.published_at,
            fetched_at=information.fetched_at,
            summary=information.summary,
            content=information.content,
            content_markdown=content_to_markdown(information.content),
            content_html=content_to_html(information.content),
            full_content=information.full_content,
            language=information.language,
            information_type=information.information_type,
            search_context=information.search_context,
            content_fingerprint=information.content_fingerprint,
            importance=information.importance,
            confidence=information.confidence,
            market_scope_codes=sorted(
                scope.code for scope in information.market_scopes
            ),
            assets=[
                InformationAssetRef(symbol=asset.symbol, category=asset.category)
                for asset in sorted(
                    information.assets,
                    key=lambda item: (item.category.value, item.symbol),
                )
            ],
            is_referenced=bool(information.commentaries),
            created_at=information.created_at,
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        parts = urlsplit(url.strip())
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
        )

    @classmethod
    def _fingerprint(cls, url: str) -> str:
        return hashlib.sha256(cls._normalize_url(url).encode()).hexdigest()

    @staticmethod
    def _search_text(information: Information) -> str:
        return " ".join(
            (
                information.title,
                information.summary or "",
                information.search_context or "",
                json.dumps(information.content, ensure_ascii=False, default=str),
            )
        ).casefold()

    @staticmethod
    def _loads():
        return (
            selectinload(Information.market_scopes),
            selectinload(Information.assets),
            selectinload(Information.commentaries),
        )
