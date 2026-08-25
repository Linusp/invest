import json
import logging
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

from ..models import AssetCategory
from .base import MarketDataProvider, ProviderAsset, ProviderBar, ProviderError
from .eastmoney import EastMoneyProvider

logger = logging.getLogger(__name__)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class _RecordsFrame:
    """Small DataFrame-compatible wrapper for isolated AkShare results."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records

    @property
    def empty(self) -> bool:
        return not self.records

    def to_dict(self, orient: str) -> list[dict[str, Any]]:
        if orient != "records":
            raise ValueError("only records orientation is supported")
        return self.records


class AkshareFallbackProvider(MarketDataProvider):
    name = "akshare"

    def __init__(
        self,
        api: Any | None = None,
        catalog_ttl_seconds: int = 3600,
        etf_history_provider: MarketDataProvider | None = None,
        call_timeout_seconds: int = 30,
    ):
        self._api = api
        self.catalog_ttl_seconds = catalog_ttl_seconds
        self._stock_catalog_cache: tuple[float, list[ProviderAsset]] | None = None
        self._etf_catalog_cache: tuple[float, list[ProviderAsset]] | None = None
        self._index_catalog_cache: tuple[float, list[ProviderAsset]] | None = None
        self._etf_history_provider = etf_history_provider
        self.call_timeout_seconds = call_timeout_seconds

    @property
    def api(self):
        if self._api is None:
            try:
                import akshare
            except ImportError as exc:
                raise ProviderError(
                    "AkShare fallback is unavailable; install the akshare dependency"
                ) from exc
            self._api = akshare
        return self._api

    def _fetch(self, function_name: str, **kwargs: Any) -> Any:
        if self._api is not None:
            return getattr(self._api, function_name)(**kwargs)

        request = json.dumps(
            {"function": function_name, "kwargs": kwargs},
            ensure_ascii=False,
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "invest_service.providers.akshare_runner"],
                input=request,
                text=True,
                capture_output=True,
                timeout=self.call_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"AkShare {function_name} timed out after {self.call_timeout_seconds} seconds"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            message = detail[-1] if detail else f"exit status {completed.returncode}"
            raise ProviderError(f"AkShare {function_name} failed: {message}")
        try:
            records = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"AkShare {function_name} returned malformed data") from exc
        if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
            raise ProviderError(f"AkShare {function_name} returned malformed data")
        return _RecordsFrame(records)

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        catalogs = {
            AssetCategory.STOCK: self._stock_catalog,
            AssetCategory.ETF: self._etf_catalog,
            AssetCategory.INDEX: self._index_catalog,
        }
        categories = (category,) if category is not None else tuple(catalogs)
        candidates: list[ProviderAsset] = []
        errors: list[Exception] = []
        for selected in categories:
            try:
                candidates.extend(catalogs[selected]())
            except Exception as exc:
                errors.append(exc)
                logger.warning(
                    "AkShare %s catalog failed; keeping other categories: %s",
                    selected.value,
                    exc,
                )
        if not candidates and errors:
            raise ProviderError(f"AkShare catalog failed: {errors[0]}") from errors[0]
        needle = query.strip().lower()
        matches = [
            asset
            for asset in candidates
            if not needle or needle in f"{asset.symbol} {asset.code} {asset.name}".lower()
        ]
        return matches[:limit]

    def catalog(self) -> list[ProviderAsset]:
        return self.search("", limit=100_000)

    def history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        if asset.category == AssetCategory.ETF:
            return self._etf_history(asset, start_date, end_date)
        if asset.category == AssetCategory.STOCK:
            return self._stock_history(asset, start_date, end_date)
        if asset.category != AssetCategory.INDEX:
            raise ProviderError("AkShare fallback does not support this asset category")

        symbol = self._symbol(asset.symbol)
        errors: list[str] = []
        sources = (
            (
                "Tencent",
                "stock_zh_index_daily_tx",
                {
                    "symbol": symbol,
                    "start_date": start_date.strftime("%Y%m%d"),
                    "end_date": end_date.strftime("%Y%m%d"),
                },
            ),
            ("Sina", "stock_zh_index_daily", {"symbol": symbol}),
        )
        for source_name, function_name, kwargs in sources:
            try:
                frame = self._fetch(function_name, **kwargs)
                if frame is None or frame.empty:
                    errors.append(f"{source_name} returned no data")
                    continue
                bars = self._bars(frame, start_date, end_date)
                if bars:
                    return bars
                errors.append(f"{source_name} returned no rows in the requested range")
            except Exception as exc:
                errors.append(f"{source_name} failed: {exc}")
        raise ProviderError(f"AkShare index history failed for {asset.symbol}: {'; '.join(errors)}")

    def _stock_history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        symbol = self._symbol(asset.symbol)
        date_args = {
            "start_date": start_date.strftime("%Y%m%d"),
            "end_date": end_date.strftime("%Y%m%d"),
        }
        errors: list[str] = []
        sources = (
            (
                "Tencent",
                "stock_zh_a_hist_tx",
                {"symbol": symbol, **date_args, "adjust": "", "timeout": 15},
            ),
            (
                "Sina",
                "stock_zh_a_daily",
                {"symbol": symbol, **date_args, "adjust": ""},
            ),
        )
        for source_name, function_name, kwargs in sources:
            try:
                frame = self._fetch(function_name, **kwargs)
                if frame is None or frame.empty:
                    errors.append(f"{source_name} returned no data")
                    continue
                bars = self._bars(frame, start_date, end_date)
                if bars:
                    return bars
                errors.append(f"{source_name} returned no rows in the requested range")
            except Exception as exc:
                errors.append(f"{source_name} failed: {exc}")
        raise ProviderError(f"AkShare stock history failed for {asset.symbol}: {'; '.join(errors)}")

    def _etf_catalog(self) -> list[ProviderAsset]:
        now = monotonic()
        if self._etf_catalog_cache and now - self._etf_catalog_cache[0] < self.catalog_ttl_seconds:
            return self._etf_catalog_cache[1]
        errors: list[str] = []
        frame = None
        for source_name, function_name, kwargs in (
            ("Sina", "fund_etf_category_sina", {"symbol": "ETF基金"}),
            ("EastMoney", "fund_etf_spot_em", {}),
        ):
            try:
                frame = self._fetch(function_name, **kwargs)
                if frame is not None and not frame.empty:
                    break
                errors.append(f"{source_name} returned no data")
            except Exception as exc:
                errors.append(f"{source_name} failed: {exc}")
        if frame is None or frame.empty:
            raise ProviderError(f"AkShare ETF catalog failed: {'; '.join(errors)}")

        assets: list[ProviderAsset] = []
        for row in frame.to_dict(orient="records"):
            raw_code = str(row.get("代码") or row.get("code") or "").strip()
            name = str(row.get("名称") or row.get("name") or "").strip()
            if not raw_code or not name:
                continue
            market_prefix = raw_code[:2].lower()
            code = raw_code[2:] if market_prefix in {"sh", "sz"} else raw_code
            suffix = (
                market_prefix.upper()
                if market_prefix in {"sh", "sz"}
                else "SH"
                if code.startswith(("5", "6"))
                else "SZ"
            )
            symbol = f"{code}.{suffix}"
            assets.append(
                ProviderAsset(
                    symbol=symbol,
                    code=code,
                    name=name,
                    category=AssetCategory.ETF,
                    provider_id=symbol,
                )
            )
        self._etf_catalog_cache = (now, assets)
        return assets

    def _stock_catalog(self) -> list[ProviderAsset]:
        now = monotonic()
        if (
            self._stock_catalog_cache
            and now - self._stock_catalog_cache[0] < self.catalog_ttl_seconds
        ):
            return self._stock_catalog_cache[1]
        try:
            frame = self._fetch("stock_info_a_code_name")
        except Exception as exc:
            raise ProviderError(f"AkShare stock catalog failed: {exc}") from exc
        if frame is None or frame.empty:
            raise ProviderError("AkShare stock catalog returned no data")
        assets: list[ProviderAsset] = []
        for row in frame.to_dict(orient="records"):
            code = str(row.get("code") or row.get("代码") or "").strip()
            name = str(row.get("name") or row.get("名称") or "").strip()
            if not code or not name:
                continue
            suffix = "SH" if code.startswith("6") else "BJ" if code.startswith(("4", "8")) else "SZ"
            symbol = f"{code}.{suffix}"
            assets.append(
                ProviderAsset(
                    symbol=symbol,
                    code=code,
                    name=name,
                    category=AssetCategory.STOCK,
                    provider_id=symbol,
                    default_tags=("A股",),
                )
            )
        self._stock_catalog_cache = (now, assets)
        return assets

    def _index_catalog(self) -> list[ProviderAsset]:
        now = monotonic()
        if (
            self._index_catalog_cache
            and now - self._index_catalog_cache[0] < self.catalog_ttl_seconds
        ):
            return self._index_catalog_cache[1]
        try:
            frame = self._fetch("stock_zh_index_spot_sina")
        except Exception as exc:
            raise ProviderError(f"AkShare index catalog failed: {exc}") from exc
        if frame is None or frame.empty:
            raise ProviderError("AkShare index catalog returned no data")
        assets: list[ProviderAsset] = []
        for row in frame.to_dict(orient="records"):
            raw_code = str(row.get("代码") or row.get("code") or "").strip()
            name = str(row.get("名称") or row.get("name") or "").strip()
            prefix = raw_code[:2].lower()
            code = raw_code[2:] if prefix in {"sh", "sz", "bj"} else raw_code
            if not code or not name:
                continue
            suffix = prefix.upper() if prefix in {"sh", "sz", "bj"} else "SH"
            symbol = f"{code}.{suffix}"
            assets.append(
                ProviderAsset(
                    symbol=symbol,
                    code=code,
                    name=name,
                    category=AssetCategory.INDEX,
                    provider_id=symbol,
                    default_tags=("指数",),
                )
            )
        self._index_catalog_cache = (now, assets)
        return assets

    def _etf_history(
        self,
        asset: ProviderAsset,
        start_date: date,
        end_date: date,
    ) -> list[ProviderBar]:
        errors: list[str] = []
        if self._etf_history_provider is None:
            self._etf_history_provider = EastMoneyProvider("")
        market_id = "1" if asset.symbol.upper().endswith(".SH") else "0"
        provider_asset = ProviderAsset(
            symbol=asset.symbol,
            code=asset.code,
            name=asset.name,
            category=asset.category,
            provider_id=f"{market_id}.{asset.code}",
        )
        try:
            bars = self._etf_history_provider.history(provider_asset, start_date, end_date)
            if bars:
                return bars
            errors.append("EastMoney returned no rows in range")
        except ProviderError as exc:
            errors.append(str(exc))

        try:
            frame = self._fetch(
                "fund_etf_hist_sina",
                symbol=self._symbol(asset.symbol),
            )
            if frame is not None and not frame.empty:
                bars = self._bars(frame, start_date, end_date)
                if bars:
                    return bars
            errors.append("Sina returned no rows in range")
        except Exception as exc:
            errors.append(f"Sina failed: {exc}")
        raise ProviderError(f"ETF history fallback failed for {asset.symbol}: {'; '.join(errors)}")

    @staticmethod
    def _symbol(symbol: str) -> str:
        code, _, suffix = symbol.strip().upper().partition(".")
        market = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(suffix, suffix.lower() or "sz")
        return f"{market}{code}"

    @staticmethod
    def _bars(frame: Any, start_date: date, end_date: date) -> list[ProviderBar]:
        parsed: list[tuple[date, dict[str, Any], Decimal]] = []
        for row in frame.to_dict(orient="records"):
            trade_date = _date(row.get("date", row.get("日期")))
            close = _decimal(row.get("close", row.get("收盘")))
            if trade_date is not None and close is not None:
                parsed.append((trade_date, row, close))
        parsed.sort(key=lambda item: item[0])

        bars: list[ProviderBar] = []
        previous_close: Decimal | None = None
        for trade_date, row, close in parsed:
            reported_change = _decimal(row.get("change", row.get("涨跌额")))
            change = (
                reported_change
                if reported_change is not None
                else close - previous_close
                if previous_close is not None
                else None
            )
            reported_percent = _decimal(row.get("change_percent", row.get("涨跌幅")))
            change_percent = (
                reported_percent
                if reported_percent is not None
                else change / previous_close * 100
                if change is not None and previous_close
                else None
            )
            row_previous_close = close - change if reported_change is not None else previous_close
            if start_date <= trade_date <= end_date:
                bars.append(
                    ProviderBar(
                        trade_date=trade_date,
                        open=_decimal(row.get("open", row.get("开盘"))),
                        high=_decimal(row.get("high", row.get("最高"))),
                        low=_decimal(row.get("low", row.get("最低"))),
                        close=close,
                        previous_close=row_previous_close,
                        change=change,
                        change_percent=change_percent,
                        volume=_decimal(row.get("volume", row.get("成交量"))),
                        amount=_decimal(row.get("amount", row.get("成交额"))),
                        source="akshare",
                    )
                )
            previous_close = close
        return bars


AkshareIndexProvider = AkshareFallbackProvider
