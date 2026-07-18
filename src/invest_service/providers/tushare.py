from datetime import date
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

import httpx

from ..models import AssetCategory
from .base import MarketDataProvider, ProviderAsset, ProviderBar, ProviderError


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class TushareProvider(MarketDataProvider):
    name = "tushare"
    API_URL = "https://api.tushare.pro"
    HISTORY_APIS = {
        AssetCategory.STOCK: "daily",
        AssetCategory.ETF: "fund_daily",
        AssetCategory.INDEX: "index_daily",
    }
    HISTORY_FIELDS = (
        "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
    )

    def __init__(
        self,
        token: str | None,
        client: httpx.Client | None = None,
        catalog_ttl_seconds: int = 3600,
    ):
        self.token = (token or "").strip()
        self.client = client or httpx.Client(
            timeout=30,
            headers={"User-Agent": "InvestService/0.1"},
            trust_env=False,
        )
        self.catalog_ttl_seconds = catalog_ttl_seconds
        self._catalog_cache: dict[AssetCategory, tuple[float, list[ProviderAsset]]] = {}

    def _query(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str,
    ) -> list[dict[str, Any]]:
        if not self.token:
            raise ProviderError(
                "Tushare token is not configured; set INVEST_TUSHARE_TOKEN"
            )
        try:
            response = self.client.post(
                self.API_URL,
                json={
                    "api_name": api_name,
                    "token": self.token,
                    "params": params,
                    "fields": fields,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"Tushare {api_name} request failed: {exc}") from exc

        if payload.get("code") != 0:
            message = str(payload.get("msg") or "unknown provider error")
            raise ProviderError(f"Tushare {api_name} failed: {message}")

        data = payload.get("data") or {}
        response_fields = data.get("fields") or []
        items = data.get("items") or []
        if not isinstance(response_fields, list) or not isinstance(items, list):
            raise ProviderError(f"Tushare {api_name} returned malformed data")
        return [
            dict(zip(response_fields, row, strict=False))
            for row in items
            if isinstance(row, list)
        ]

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        categories = (
            (category,)
            if category is not None
            else (AssetCategory.STOCK, AssetCategory.ETF, AssetCategory.INDEX)
        )
        candidates: list[ProviderAsset] = []
        errors: list[ProviderError] = []
        for selected_category in categories:
            try:
                candidates.extend(self._catalog(selected_category))
            except ProviderError as exc:
                if category is not None:
                    raise
                errors.append(exc)
        if not candidates and errors:
            raise errors[0]
        needle = query.strip().lower()
        if needle:
            candidates = [
                asset
                for asset in candidates
                if needle in f"{asset.symbol} {asset.code} {asset.name}".lower()
            ]

        def rank(asset: ProviderAsset) -> tuple[int, str]:
            symbol = asset.symbol.lower()
            code = asset.code.lower()
            name = asset.name.lower()
            if needle in {symbol, code, name}:
                score = 0
            elif symbol.startswith(needle) or code.startswith(needle) or name.startswith(needle):
                score = 1
            else:
                score = 2
            return score, asset.symbol

        return sorted(candidates, key=rank)[:limit]

    def _catalog(self, category: AssetCategory) -> list[ProviderAsset]:
        cached = self._catalog_cache.get(category)
        now = monotonic()
        if cached and now - cached[0] < self.catalog_ttl_seconds:
            return cached[1]

        if category == AssetCategory.STOCK:
            assets = self._stock_catalog()
        elif category == AssetCategory.ETF:
            assets = self._etf_catalog()
        else:
            assets = self._index_catalog()
        self._catalog_cache[category] = (now, assets)
        return assets

    def _stock_catalog(self) -> list[ProviderAsset]:
        rows = self._query(
            "stock_basic",
            {"exchange": "", "list_status": "L"},
            "ts_code,symbol,name",
        )
        return self._assets_from_rows(rows, AssetCategory.STOCK, "name")

    def _etf_catalog(self) -> list[ProviderAsset]:
        name_fields = ("extname", "csname")
        try:
            rows = self._query(
                "etf_basic",
                {"list_status": "L"},
                "ts_code,csname,extname",
            )
        except ProviderError as exc:
            if "etf_basic" not in str(exc) or "访问权限" not in str(exc):
                raise
            rows = self._query(
                "fund_basic",
                {"market": "E", "status": "L"},
                "ts_code,name,fund_type,type,market",
            )
            rows = [row for row in rows if self._is_etf_fund(row)]
            name_fields = ("name",)
        assets: list[ProviderAsset] = []
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            name = next(
                (
                    str(row.get(field) or "").strip()
                    for field in name_fields
                    if row.get(field)
                ),
                "",
            )
            if ts_code and name:
                assets.append(
                    ProviderAsset(
                        symbol=ts_code,
                        code=ts_code.split(".", 1)[0],
                        name=name,
                        category=AssetCategory.ETF,
                        provider_id=ts_code,
                    )
                )
        return assets

    @staticmethod
    def _is_etf_fund(row: dict[str, Any]) -> bool:
        ts_code = str(row.get("ts_code") or "").upper()
        code = ts_code.split(".", 1)[0]
        name = str(row.get("name") or "").upper()
        return (
            "ETF" in name
            or code.startswith("159")
            or code.startswith(("510", "511", "512", "513", "515", "516", "517", "518"))
            or code.startswith(("560", "561", "562", "563", "588", "589"))
        )

    def _index_catalog(self) -> list[ProviderAsset]:
        by_symbol: dict[str, ProviderAsset] = {}
        for market in ("SSE", "SZSE", "CSI"):
            rows = self._query(
                "index_basic",
                {"market": market},
                "ts_code,name,market",
            )
            for asset in self._assets_from_rows(rows, AssetCategory.INDEX, "name"):
                by_symbol[asset.symbol] = asset
        return list(by_symbol.values())

    @staticmethod
    def _assets_from_rows(
        rows: list[dict[str, Any]],
        category: AssetCategory,
        name_field: str,
    ) -> list[ProviderAsset]:
        assets: list[ProviderAsset] = []
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            code = str(row.get("symbol") or "").strip() or ts_code.split(".", 1)[0]
            name = str(row.get(name_field) or "").strip()
            if ts_code and code and name:
                assets.append(
                    ProviderAsset(
                        symbol=ts_code,
                        code=code,
                        name=name,
                        category=category,
                        provider_id=ts_code,
                    )
                )
        return assets

    def history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        api_name = self.HISTORY_APIS[asset.category]
        ts_code = self._ts_code(asset)
        rows = self._query(
            api_name,
            {
                "ts_code": ts_code,
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            },
            self.HISTORY_FIELDS,
        )
        bars: list[ProviderBar] = []
        for row in rows:
            close = _decimal(row.get("close"))
            trade_date = str(row.get("trade_date") or "")
            if close is None or len(trade_date) != 8:
                continue
            amount = _decimal(row.get("amount"))
            bars.append(
                ProviderBar(
                    trade_date=date(
                        int(trade_date[:4]),
                        int(trade_date[4:6]),
                        int(trade_date[6:8]),
                    ),
                    open=_decimal(row.get("open")),
                    high=_decimal(row.get("high")),
                    low=_decimal(row.get("low")),
                    close=close,
                    previous_close=_decimal(row.get("pre_close")),
                    change=_decimal(row.get("change")),
                    change_percent=_decimal(row.get("pct_chg")),
                    volume=_decimal(row.get("vol")),
                    amount=amount * 1000 if amount is not None else None,
                    source="tushare",
                )
            )
        return sorted(bars, key=lambda item: item.trade_date)

    @staticmethod
    def _ts_code(asset: ProviderAsset) -> str:
        provider_id = asset.provider_id.strip().upper()
        if "." in provider_id and provider_id.rsplit(".", 1)[1] in {
            "SH",
            "SZ",
            "BJ",
            "CSI",
            "SI",
        }:
            return provider_id
        return asset.symbol.strip().upper()
