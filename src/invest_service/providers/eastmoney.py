from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ..models import AssetCategory
from .base import MarketDataProvider, ProviderAsset, ProviderBar, ProviderError, infer_currency


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class EastMoneyProvider(MarketDataProvider):
    name = "eastmoney"
    SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
    HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, token: str, client: httpx.Client | None = None):
        self.token = token
        self.client = client or httpx.Client(
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 InvestService/0.1"},
            trust_env=False,
        )

    @staticmethod
    def _category(item: dict[str, Any]) -> AssetCategory | None:
        classify = str(item.get("Classify") or item.get("classify") or "")
        security_type = str(item.get("SecurityTypeName") or item.get("security_typeName") or "")
        name = str(item.get("Name") or item.get("name") or "")
        if classify in {"Index", "UniversalIndex"} or "指数" in security_type:
            return AssetCategory.INDEX
        if "ETF" in security_type.upper() or "ETF" in name.upper():
            return AssetCategory.ETF
        if classify in {"AStock", "UsStock", "HKStock"} or security_type in {
            "深A",
            "沪A",
            "京A",
            "港股",
            "美股",
            "科创板",
            "创业板",
        }:
            return AssetCategory.STOCK
        return None

    @staticmethod
    def _canonical_symbol(code: str, provider_id: str, item: dict[str, Any]) -> str:
        market = provider_id.split(".", 1)[0] if "." in provider_id else ""
        market_name = str(item.get("JYS") or item.get("jys") or "").upper()
        if market_name in {"SH", "SZ", "BJ", "HK", "US"}:
            suffix = market_name
        elif market == "1":
            suffix = "SH"
        elif market == "0":
            suffix = "BJ" if code.startswith(("4", "8")) else "SZ"
        else:
            suffix = market_name or "UNKNOWN"
        return f"{code.upper()}.{suffix}"

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        try:
            response = self.client.get(
                self.SEARCH_URL,
                params={"input": query, "type": "14", "token": self.token, "count": limit},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"EastMoney search failed: {exc}") from exc

        items = (payload.get("QuotationCodeTable") or {}).get("Data") or []
        found: list[ProviderAsset] = []
        for item in items:
            item_category = self._category(item)
            code = str(item.get("Code") or item.get("code") or "").strip()
            name = str(item.get("Name") or item.get("name") or "").strip()
            provider_id = str(item.get("QuoteID") or item.get("quote_id") or "").strip()
            if not item_category or not code or not name or not provider_id:
                continue
            if category is not None and category != item_category:
                continue
            symbol = self._canonical_symbol(code, provider_id, item)
            found.append(
                ProviderAsset(
                    symbol=symbol,
                    code=code,
                    name=name,
                    category=item_category,
                    provider_id=provider_id,
                    currency=infer_currency(symbol),
                )
            )
        return found[:limit]

    def history(self, asset: ProviderAsset, start_date: date, end_date: date) -> list[ProviderBar]:
        fields = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        try:
            response = self.client.get(
                self.HISTORY_URL,
                params={
                    "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                    "fields2": fields,
                    "beg": start_date.strftime("%Y%m%d"),
                    "end": end_date.strftime("%Y%m%d"),
                    "rtntype": "6",
                    "secid": asset.provider_id,
                    "klt": "101",
                    "fqt": "1",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"EastMoney history failed for {asset.symbol}: {exc}") from exc

        rows = (payload.get("data") or {}).get("klines") or []
        result: list[ProviderBar] = []
        for raw in rows:
            values = raw.split(",")
            if len(values) < 10:
                continue
            close = _decimal(values[2])
            if close is None:
                continue
            change = _decimal(values[9])
            result.append(
                ProviderBar(
                    trade_date=date.fromisoformat(values[0]),
                    open=_decimal(values[1]),
                    close=close,
                    high=_decimal(values[3]),
                    low=_decimal(values[4]),
                    volume=_decimal(values[5]),
                    amount=_decimal(values[6]),
                    change_percent=_decimal(values[8]),
                    change=change,
                    previous_close=close - change if change is not None else None,
                    source="eastmoney",
                )
            )
        return result
