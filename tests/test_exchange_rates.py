from datetime import date
from decimal import Decimal

import httpx

from invest_service.models import ExchangeRate
from invest_service.providers.exchange_rates import EcbExchangeRateProvider
from invest_service.services.exchange_rate import ExchangeRateService

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-07-10">
    <Cube currency="USD" rate="1.2"/>
    <Cube currency="CNY" rate="8.4"/>
    <Cube currency="HKD" rate="9.6"/>
  </Cube></Cube>
</gesmes:Envelope>"""


def test_ecb_provider_parses_euro_based_xml():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=XML))
    )
    rows = EcbExchangeRateProvider(client).fetch(full_history=True)
    assert rows[0].trade_date == date(2026, 7, 10)
    assert rows[0].units_per_eur["EUR"] == Decimal("1")
    assert rows[0].units_per_eur["HKD"] == Decimal("9.6")


def test_exchange_rate_sync_and_cross_conversion(session_factory):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=XML))
    )
    with session_factory() as session:
        service = ExchangeRateService(session, EcbExchangeRateProvider(client))
        result = service.sync(full_history=True)
        assert result.created == 4
        assert session.query(ExchangeRate).count() == 4
        converted = service.convert(
            Decimal("100"), "HKD", "CNY", date(2026, 7, 12)
        )
        assert converted.quantize(Decimal("0.000001")) == Decimal("87.500000")
