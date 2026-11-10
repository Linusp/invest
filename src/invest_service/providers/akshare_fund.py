"""场外基金 provider（AkShare）。

数据源：
- ``fund_name_em``：全市场基金目录（代码/简称/类型），用于目录与搜索；
- ``fund_open_fund_info_em``：单只基金的净值走势（单位净值 + 日增长率）。

约定：场外基金统一用 ``{6位代码}.OF`` 作为标的代码，category 为 ``fund``；
净值写入 ``market_bars.close``，``change_percent`` 直接取东财给的日增长率。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models import AssetCategory
from .akshare import AkshareFallbackProvider
from .base import ProviderAsset, ProviderBar, ProviderError


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "--"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return frame.to_dict(orient="records")
        except TypeError:
            return frame.to_dict("records")
    return list(frame) if isinstance(frame, list) else []


class AkshareFundProvider(AkshareFallbackProvider):
    """场外基金：目录、搜索、单位净值走势。"""

    name = "akshare-fund"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._fund_rows_cache: tuple[float, list[dict[str, Any]]] | None = None

    def _fund_rows(self) -> list[dict[str, Any]]:
        import time

        now = time.time()
        if self._fund_rows_cache and now - self._fund_rows_cache[0] < self.catalog_ttl_seconds:
            return self._fund_rows_cache[1]
        rows = _records(self._fetch("fund_name_em"))
        self._fund_rows_cache = (now, rows)
        return rows

    def catalog(self) -> list[ProviderAsset]:
        assets: list[ProviderAsset] = []
        for row in self._fund_rows():
            code = str(row.get("基金代码") or "").strip()
            name = str(row.get("基金简称") or "").strip()
            if not code or not name:
                continue
            assets.append(
                ProviderAsset(
                    symbol=f"{code}.OF",
                    code=code,
                    name=name,
                    category=AssetCategory.FUND,
                    provider_id=code,
                    currency="CNY",
                    default_tags=("场外基金",),
                )
            )
        return assets

    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]:
        if category not in (None, AssetCategory.FUND):
            return []
        keyword = query.strip().lower()
        if not keyword:
            return []
        matches: list[ProviderAsset] = []
        for asset in self.catalog():
            if keyword in asset.code or keyword in asset.name.lower():
                matches.append(asset)
                if len(matches) >= limit:
                    break
        return matches

    def history(
        self, asset: ProviderAsset, start_date: date, end_date: date
    ) -> list[ProviderBar]:
        code = asset.code or asset.symbol.split(".")[0]
        try:
            frame = self._fetch(
                "fund_open_fund_info_em", symbol=code, indicator="单位净值走势"
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - 第三方库异常不统一
            raise ProviderError(f"场外基金净值查询失败: {exc}") from exc

        rows = _records(frame)
        bars: list[ProviderBar] = []
        previous: Decimal | None = None
        for row in rows:
            raw_date = str(row.get("净值日期") or "").strip()
            try:
                trade_date = date.fromisoformat(raw_date[:10])
            except ValueError:
                continue
            if not start_date <= trade_date <= end_date:
                continue
            close = _decimal(row.get("单位净值"))
            if close is None:
                continue
            change_percent = _decimal(row.get("日增长率"))
            change = close - previous if previous is not None else None
            bars.append(
                ProviderBar(
                    trade_date=trade_date,
                    open=None,
                    high=None,
                    low=None,
                    close=close,
                    previous_close=previous,
                    change=change,
                    change_percent=change_percent,
                    volume=None,
                    amount=None,
                    source="akshare",
                )
            )
            previous = close
        bars.sort(key=lambda bar: bar.trade_date)
        return bars
