from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..models import AssetCategory


def infer_currency(symbol: str) -> str:
    suffix = symbol.strip().upper().rsplit(".", 1)[-1]
    if suffix == "HK":
        return "HKD"
    if suffix in {"US", "NYSE", "NASDAQ", "AMEX"}:
        return "USD"
    return "CNY"


@dataclass(frozen=True)
class ProviderAsset:
    symbol: str
    code: str
    name: str
    category: AssetCategory
    provider_id: str
    currency: str = "CNY"


@dataclass(frozen=True)
class ProviderBar:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    previous_close: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    source: str | None = None


class ProviderError(RuntimeError):
    pass


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 15,
        category: AssetCategory | None = None,
    ) -> list[ProviderAsset]: ...

    @abstractmethod
    def history(
        self, asset: ProviderAsset, start_date: date, end_date: date
    ) -> list[ProviderBar]: ...
