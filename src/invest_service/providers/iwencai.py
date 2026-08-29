import logging
import re
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ..models import AssetCategory
from .base import (
    MarketDataProvider,
    ProviderAsset,
    ProviderBar,
    ProviderError,
    infer_currency,
    infer_default_tags,
)

logger = logging.getLogger(__name__)

_DATED_FIELD = re.compile(
    r"^(开盘价|最高价|最低价|收盘价|前收盘价|涨跌|涨跌幅|成交量|成交额)"
    r"\[(\d{8})\]$"
)
_CODE_FIELDS = ("股票代码", "基金代码", "指数代码")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value).replace(",", "").removesuffix("%"))
    except (InvalidOperation, ValueError):
        return None


class IwencaiProvider(MarketDataProvider):
    """Daily market bars from the official iWencai natural-language API."""

    name = "iwencai"
    API_URL = "https://openapi.iwencai.com/v1/query2data"
    SKILL_ID = "hithink-market-query"
    SKILL_VERSION = "1.0.0"

    def __init__(
        self,
        api_key: str | None,
        client: httpx.Client | None = None,
        catalog_page_size: int = 5000,
    ):
        self.api_key = (api_key or "").strip()
        self.catalog_page_size = catalog_page_size
        self.client = client or httpx.Client(
            timeout=45,
            headers={"User-Agent": "InvestService/0.1"},
            trust_env=False,
        )

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        # Asset search is served exclusively from the local scheduled index.
        return []

    def catalog(self) -> list[ProviderAsset]:
        if not self.api_key:
            raise ProviderError(
                "iWencai API key is not configured; set IWENCAI_API_KEY "
                "or INVEST_IWENCAI_API_KEY"
            )
        assets: list[ProviderAsset] = []
        errors: list[ProviderError] = []
        for market in ("hk", "us"):
            try:
                assets.extend(self._catalog_market(market))
            except ProviderError as exc:
                errors.append(exc)
                logger.warning("iWencai %s catalog failed: %s", market, exc)
        if not assets and errors:
            raise errors[0]
        return assets

    def history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        if not self.api_key:
            raise ProviderError(
                "iWencai API key is not configured; set IWENCAI_API_KEY "
                "or INVEST_IWENCAI_API_KEY"
            )
        if end_date < start_date:
            return []

        bars: dict[date, ProviderBar] = {}
        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(end_date, date(chunk_start.year, 12, 31))
            for bar in self._history_chunk(asset, chunk_start, chunk_end):
                bars[bar.trade_date] = bar
            chunk_start = date(chunk_start.year + 1, 1, 1)
        return [bars[trade_date] for trade_date in sorted(bars)]

    def _history_chunk(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        query = self._history_query(asset, start_date, end_date)
        payload = self._query_api(query, page=1, limit=1)
        rows = payload.get("datas") or []
        if not isinstance(rows, list):
            raise ProviderError("iWencai history returned malformed data")
        if not rows:
            return []

        row = next(
            (
                item
                for item in rows
                if isinstance(item, dict) and self._matches_asset(item, asset)
            ),
            None,
        )
        if row is None:
            raise ProviderError(
                f"iWencai history returned an unexpected asset for {asset.symbol}"
            )
        return self._parse_bars(row, start_date, end_date)

    def _query_api(self, query: str, page: int, limit: int) -> dict[str, Any]:
        trace_id = secrets.token_hex(32)
        try:
            response = self.client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-Claw-Call-Type": "normal",
                    "X-Claw-Skill-Id": self.SKILL_ID,
                    "X-Claw-Skill-Version": self.SKILL_VERSION,
                    "X-Claw-Plugin-Id": "none",
                    "X-Claw-Plugin-Version": "none",
                    "X-Claw-Trace-Id": trace_id,
                },
                json={
                    "query": query,
                    "page": str(page),
                    "limit": str(limit),
                    "is_cache": "1",
                    "expand_index": "true",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"iWencai request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError("iWencai returned malformed data")
        status_code = payload.get("status_code")
        if status_code not in (None, 0):
            message = payload.get("status_msg") or payload.get("error") or status_code
            raise ProviderError(f"iWencai query failed: {message}")
        return payload

    def _catalog_market(self, market: str) -> list[ProviderAsset]:
        query = {
            "hk": "全部港股普通股，排除ETF，返回股票代码、股票简称",
            "us": "全部美股普通股，排除ETF，返回股票代码、股票简称",
        }[market]
        page = 1
        assets: list[ProviderAsset] = []
        while True:
            payload = self._query_api(query, page=page, limit=self.catalog_page_size)
            rows = payload.get("datas") or []
            if not isinstance(rows, list):
                raise ProviderError(f"iWencai {market} catalog returned malformed data")
            assets.extend(
                asset
                for row in rows
                if isinstance(row, dict)
                and (asset := self._catalog_asset(row, market)) is not None
            )
            total = int(payload.get("code_count") or len(assets))
            if not rows or page * self.catalog_page_size >= total:
                return assets
            page += 1

    @staticmethod
    def _catalog_asset(row: dict[str, Any], market: str) -> ProviderAsset | None:
        raw_symbol = str(row.get("股票代码") or "").strip().upper()
        name = str(row.get("股票简称") or "").strip()
        if not raw_symbol or not name:
            return None
        if market == "hk":
            raw_code = raw_symbol.removesuffix(".HK")
            if not raw_code.isdigit():
                return None
            code = raw_code.zfill(5)
            symbol = f"{code}.HK"
        else:
            code, separator, _ = raw_symbol.rpartition(".")
            if not separator or not code:
                return None
            symbol = f"{code}.US"
        aliases = (raw_symbol,) if raw_symbol != symbol else ()
        return ProviderAsset(
            symbol=symbol,
            code=code,
            name=name,
            category=AssetCategory.STOCK,
            provider_id=raw_symbol,
            currency=infer_currency(symbol),
            default_tags=infer_default_tags(symbol, AssetCategory.STOCK),
            aliases=aliases,
        )

    @staticmethod
    def _history_query(
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> str:
        category = {
            AssetCategory.STOCK: "股票",
            AssetCategory.ETF: "ETF",
            AssetCategory.INDEX: "指数",
        }[asset.category]
        return (
            f"{asset.provider_id or asset.symbol} {category}从{start_date:%Y年%m月%d日}到"
            f"{end_date:%Y年%m月%d日}的日线行情，返回开盘价、最高价、最低价、"
            "收盘价、前收盘价、涨跌额、涨跌幅、成交量、成交额"
        )

    @staticmethod
    def _matches_asset(row: dict[str, Any], asset: ProviderAsset) -> bool:
        codes = {
            str(row[field]).strip().upper()
            for field in _CODE_FIELDS
            if row.get(field) not in (None, "")
        }
        expected = {asset.symbol.upper(), asset.code.upper()}
        return bool(codes & expected)

    @staticmethod
    def _parse_bars(
        row: dict[str, Any],
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        values: dict[date, dict[str, Decimal | None]] = {}
        for key, raw_value in row.items():
            match = _DATED_FIELD.fullmatch(key)
            if not match:
                continue
            trade_date = date.fromisoformat(
                f"{match[2][0:4]}-{match[2][4:6]}-{match[2][6:8]}"
            )
            if start_date <= trade_date <= end_date:
                values.setdefault(trade_date, {})[match[1]] = _decimal(raw_value)

        bars: list[ProviderBar] = []
        for trade_date, fields in sorted(values.items()):
            close = fields.get("收盘价")
            if close is None:
                continue
            bars.append(
                ProviderBar(
                    trade_date=trade_date,
                    open=fields.get("开盘价"),
                    high=fields.get("最高价"),
                    low=fields.get("最低价"),
                    close=close,
                    previous_close=fields.get("前收盘价"),
                    change=fields.get("涨跌"),
                    change_percent=fields.get("涨跌幅"),
                    volume=fields.get("成交量"),
                    amount=fields.get("成交额"),
                    source="iwencai",
                )
            )
        return bars
