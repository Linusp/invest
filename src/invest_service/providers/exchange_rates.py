from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

import httpx

from .base import ProviderError


@dataclass(frozen=True)
class ProviderExchangeRates:
    trade_date: date
    units_per_eur: dict[str, Decimal]


class EcbExchangeRateProvider:
    name = "ecb"
    DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            timeout=60,
            headers={"User-Agent": "InvestService/0.1"},
            trust_env=False,
        )

    def fetch(self, full_history: bool = False) -> list[ProviderExchangeRates]:
        url = self.HISTORY_URL if full_history else self.DAILY_URL
        try:
            response = self.client.get(url)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            raise ProviderError(f"ECB exchange-rate request failed: {exc}") from exc

        result = []
        for element in root.iter():
            raw_date = element.attrib.get("time")
            if not raw_date:
                continue
            rates = {"EUR": Decimal("1")}
            for child in element:
                currency = child.attrib.get("currency", "").upper()
                raw_rate = child.attrib.get("rate")
                if not currency or raw_rate is None:
                    continue
                try:
                    rates[currency] = Decimal(raw_rate)
                except InvalidOperation:
                    continue
            result.append(
                ProviderExchangeRates(
                    trade_date=date.fromisoformat(raw_date),
                    units_per_eur=rates,
                )
            )
        if not result:
            raise ProviderError("ECB exchange-rate response contained no rates")
        return result
