from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Asset, ExchangeRate, OpeningBalance, Trade
from ..providers.exchange_rates import EcbExchangeRateProvider
from ..schemas import ExchangeRateSyncResult


class ExchangeRateUnavailable(LookupError):
    pass


class ExchangeRateService:
    def __init__(
        self,
        session: Session,
        provider: EcbExchangeRateProvider | None = None,
        reporting_currency: str | None = None,
    ):
        self.session = session
        self.provider = provider
        self.reporting_currency = (
            reporting_currency or get_settings().reporting_currency
        ).upper()

    def sync(self, full_history: bool | None = None) -> ExchangeRateSyncResult:
        if self.provider is None:
            raise ValueError("exchange-rate provider is not configured")
        currencies = self._used_currencies() | {
            "CNY",
            "HKD",
            "USD",
            "EUR",
            self.reporting_currency,
        }
        latest = self.session.scalar(select(func.max(ExchangeRate.trade_date)))
        available = set(
            self.session.scalars(
                select(ExchangeRate.currency)
                .where(ExchangeRate.currency.in_(currencies))
                .distinct()
            )
        )
        use_history = (
            latest is None or not currencies.issubset(available)
            if full_history is None
            else full_history
        )
        batches = self.provider.fetch(full_history=use_history)
        dates = [item.trade_date for item in batches]
        existing = {
            (item.trade_date, item.currency): item
            for item in self.session.scalars(
                select(ExchangeRate).where(
                    ExchangeRate.trade_date >= min(dates),
                    ExchangeRate.trade_date <= max(dates),
                    ExchangeRate.currency.in_(currencies),
                )
            )
        }
        created = 0
        updated = 0
        for batch in batches:
            for currency, rate in batch.units_per_eur.items():
                if currency not in currencies:
                    continue
                row = existing.get((batch.trade_date, currency))
                if row is None:
                    row = ExchangeRate(
                        trade_date=batch.trade_date,
                        currency=currency,
                        units_per_eur=rate,
                        source=self.provider.name,
                    )
                    self.session.add(row)
                    created += 1
                else:
                    row.units_per_eur = rate
                    row.source = self.provider.name
                    updated += 1
        self.session.commit()
        return ExchangeRateSyncResult(
            start_date=min(dates),
            end_date=max(dates),
            created=created,
            updated=updated,
        )

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        on_date: date,
    ) -> Decimal:
        source = from_currency.upper()
        target = to_currency.upper()
        if source == target:
            return amount
        source_rate = self._rate(source, on_date)
        target_rate = self._rate(target, on_date)
        return amount / source_rate * target_rate

    def latest(self, currency: str, on_date: date | None = None) -> ExchangeRate:
        selected_date = on_date or date.today()
        row = self.session.scalar(
            select(ExchangeRate)
            .where(
                ExchangeRate.currency == currency.upper(),
                ExchangeRate.trade_date <= selected_date,
            )
            .order_by(ExchangeRate.trade_date.desc())
            .limit(1)
        )
        if row is None:
            raise ExchangeRateUnavailable(
                f"No exchange rate for {currency.upper()} on or before {selected_date}"
            )
        return row

    def _rate(self, currency: str, on_date: date) -> Decimal:
        if currency == "EUR":
            return Decimal("1")
        return self.latest(currency, on_date).units_per_eur

    def _used_currencies(self) -> set[str]:
        asset_currencies = self.session.scalars(select(Asset.currency).distinct())
        trade_currencies = self.session.scalars(select(Trade.currency).distinct())
        opening_currencies = self.session.scalars(
            select(OpeningBalance.currency).distinct()
        )
        return {
            item.upper()
            for item in [*asset_currencies, *trade_currencies, *opening_currencies]
            if item
        }
