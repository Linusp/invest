import httpx
import pytest

from invest_service.providers.base import ProviderError
from invest_service.providers.iwencai import IwencaiProvider


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {"status_code": 0, "datas": []}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.response


def test_before_call_can_block_the_request():
    client = _Client(_Response())
    events = []

    def before():
        events.append("before")
        raise ProviderError("问财已被熔断")

    provider = IwencaiProvider("key", client=client, before_call=before)
    with pytest.raises(ProviderError, match="熔断"):
        provider.query("贵州茅台")
    assert client.calls == 0
    assert events == ["before"]


def test_successful_query_records_call():
    client = _Client(_Response())
    recorded = []
    provider = IwencaiProvider("key", client=client, record_call=lambda: recorded.append(1))
    provider.query("贵州茅台")
    assert client.calls == 1
    assert recorded == [1]


def test_quota_error_trips_the_breaker_and_raises():
    client = _Client(_Response(status_code=401, text="您今天的次数已用完"))
    trips = []
    provider = IwencaiProvider("key", client=client, on_quota_error=trips.append)
    with pytest.raises(ProviderError, match="额度已用完"):
        provider.query("贵州茅台")
    assert len(trips) == 1
    assert "次数已用完" in trips[0]


def test_quota_error_still_counts_as_an_attempt():
    client = _Client(_Response(status_code=401, text="您今天的次数已用完"))
    recorded = []
    provider = IwencaiProvider(
        "key", client=client, record_call=lambda: recorded.append(1), on_quota_error=lambda _m: None
    )
    with pytest.raises(ProviderError):
        provider.query("贵州茅台")
    assert recorded == [1]


def test_catalog_is_skipped_when_provider_is_disabled():
    client = _Client(_Response())
    provider = IwencaiProvider(
        "key", client=client, catalog_needed=lambda: True, available=lambda: False
    )
    assert provider.catalog() == []
    assert client.calls == 0


def test_catalog_is_skipped_when_not_needed():
    client = _Client(_Response())
    provider = IwencaiProvider("key", client=client, catalog_needed=lambda: False)
    assert provider.catalog() == []
    assert client.calls == 0


def test_catalog_runs_when_needed():
    client = _Client(_Response(payload={"status_code": 0, "datas": []}))
    provider = IwencaiProvider("key", client=client, catalog_needed=lambda: True)
    assert provider.catalog() == []
    assert client.calls >= 1
