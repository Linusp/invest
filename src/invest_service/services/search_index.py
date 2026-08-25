import json
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from pypinyin import Style, lazy_pinyin
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, AssetCategory, AssetSearchIndex, asset_identity
from ..providers import MarketDataProvider, ProviderAsset


def normalize_search_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(str(raw).split())
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _decode_values(payload: str | None) -> list[str]:
    try:
        values = json.loads(payload or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return _unique(str(value) for value in values) if isinstance(values, list) else []


def _encode_values(values: Iterable[str]) -> str:
    return json.dumps(_unique(values), ensure_ascii=False, separators=(",", ":"))


def _pinyin(value: str, style: Style) -> str:
    parts = lazy_pinyin(
        value,
        style=style,
        errors=lambda characters: list(characters),
    )
    return normalize_search_term("".join(parts))


def _refresh_search_fields(document: AssetSearchIndex) -> None:
    names = _unique([document.name, *_decode_values(document.aliases)])
    full = _unique(_pinyin(name, Style.NORMAL) for name in names)
    initials = _unique(_pinyin(name, Style.FIRST_LETTER) for name in names)
    document.pinyin_full = "\n".join(full)
    document.pinyin_initials = "\n".join(initials)
    terms = _unique(
        normalize_search_term(value)
        for value in (
            document.symbol,
            document.code,
            *names,
            *full,
            *initials,
        )
    )
    document.search_text = "\n".join(terms)


@dataclass(frozen=True)
class SearchIndexSyncResult:
    discovered: int
    indexed: int


class AssetSearchIndexService:
    def __init__(self, session: Session):
        self.session = session

    def sync_catalog(self, provider: MarketDataProvider) -> SearchIndexSyncResult:
        catalog = provider.catalog()
        indexed = 0
        for item in catalog:
            self.upsert_provider_asset(item)
            indexed += 1
        self.seed_assets()
        self.session.commit()
        return SearchIndexSyncResult(discovered=len(catalog), indexed=indexed)

    def seed_assets(self) -> int:
        count = 0
        for asset in self.session.scalars(select(Asset)):
            if self.session.get(AssetSearchIndex, asset.key) is not None:
                continue
            self.upsert_provider_asset(
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
            count += 1
        return count

    def upsert_provider_asset(self, item: ProviderAsset) -> AssetSearchIndex:
        symbol = item.symbol.strip().upper()
        key = asset_identity(item.category, symbol)
        document = self.session.get(AssetSearchIndex, key)
        existing_aliases = _decode_values(document.aliases) if document else []
        aliases = [*existing_aliases, *item.aliases]
        if document is None:
            document = AssetSearchIndex(key=key, symbol=symbol)
            self.session.add(document)
        elif document.name and document.name.casefold() != item.name.strip().casefold():
            aliases.append(document.name)

        name = item.name.strip()
        aliases = [alias for alias in _unique(aliases) if alias.casefold() != name.casefold()]
        document.code = item.code.strip().upper()
        document.name = name
        document.category = item.category
        document.currency = item.currency.strip().upper()
        document.provider_id = item.provider_id.strip() or document.provider_id
        document.aliases = _encode_values(aliases)
        document.default_tags = _encode_values(item.default_tags)
        _refresh_search_fields(document)
        return document

    def search(
        self,
        query: str,
        category: AssetCategory | None = None,
        limit: int = 15,
    ) -> list[AssetSearchIndex]:
        needle = normalize_search_term(query)
        if not needle:
            return []
        stmt = select(AssetSearchIndex)
        if category is not None:
            stmt = stmt.where(AssetSearchIndex.category == category)
        documents = list(self.session.scalars(stmt))
        ranked: list[tuple[float, int, str, AssetSearchIndex]] = []
        for document in documents:
            terms = [term for term in document.search_text.splitlines() if term]
            score = self._score(needle, terms)
            if score is None:
                continue
            shortest = min((len(term) for term in terms if needle in term), default=10_000)
            ranked.append((score, -shortest, document.symbol, document))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [item[3] for item in ranked[:limit]]

    @staticmethod
    def _score(needle: str, terms: list[str]) -> float | None:
        if needle in terms:
            return 1000
        if any(term.startswith(needle) for term in terms):
            return 900
        if any(needle in term for term in terms):
            return 800
        if len(needle) <= 1 or needle.isdigit():
            return None
        fuzzy_score = max(
            (max(fuzz.ratio(needle, term), fuzz.WRatio(needle, term)) for term in terms),
            default=0,
        )
        threshold = 72 if len(needle) == 2 else 65
        return fuzzy_score if fuzzy_score >= threshold else None

    @staticmethod
    def aliases(document: AssetSearchIndex) -> list[str]:
        return _decode_values(document.aliases)

    @staticmethod
    def default_tags(document: AssetSearchIndex) -> list[str]:
        return _decode_values(document.default_tags)
