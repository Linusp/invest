from datetime import date

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from invest_service.database import Base
from invest_service.models import MarketScope, MarketScopeType, SectorCapitalFlow
from invest_service.providers.sector_flow import EastMoneySectorFlow, SectorDailyFlow
from invest_service.services.sector_capital_flow import (
    SectorCapitalFlowService,
    SectorFlowNotFound,
)


class FakeProvider:
    """Deterministic stand-in for EastMoneySectorFlow (no network)."""

    def __init__(self, boards=None, flows=None):
        self.boards = boards if boards is not None else _boards()
        self.flows = flows if flows is not None else _flows()

    def industry_boards(self):
        return self.boards

    def daily_flows(self, code, days=30):
        return self.flows[code]


def _boards():
    from invest_service.providers.sector_flow import SectorBoard

    return [
        SectorBoard(code="BK0001", name="电子", change_percent=1.5, market_cap=1000.0),
        SectorBoard(code="BK0002", name="银行", change_percent=-0.5, market_cap=2000.0),
        SectorBoard(code="BK0003", name="食品", change_percent=0.2, market_cap=500.0),
    ]


def _flows():
    return {
        "BK0001": [
            SectorDailyFlow(date(2025, 1, 2), 100.0, 60.0, 40.0, -20.0, -80.0),
            SectorDailyFlow(date(2025, 1, 3), 300.0, 150.0, 150.0, -100.0, -200.0),
        ],
        "BK0002": [
            SectorDailyFlow(date(2025, 1, 2), -50.0, -20.0, -30.0, 10.0, 40.0),
            SectorDailyFlow(date(2025, 1, 3), -900.0, -500.0, -400.0, 300.0, 600.0),
        ],
        "BK0003": [
            SectorDailyFlow(date(2025, 1, 2), 10.0, 5.0, 5.0, -5.0, -5.0),
            SectorDailyFlow(date(2025, 1, 3), 20.0, 10.0, 10.0, -10.0, -10.0),
        ],
    }


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_refresh_upserts_and_is_idempotent():
    session = _session()
    service = SectorCapitalFlowService(session)
    provider = FakeProvider()

    first = service.refresh_daily(provider=provider, sync_scopes=False)
    assert first["boards"] == 3
    assert first["created"] == 6
    assert session.query(SectorCapitalFlow).count() == 6

    # Second run must update, not duplicate.
    second = service.refresh_daily(provider=provider, sync_scopes=False)
    assert second["created"] == 0
    assert second["updated"] == 0
    assert session.query(SectorCapitalFlow).count() == 6


def test_refresh_updates_changed_values():
    session = _session()
    service = SectorCapitalFlowService(session)
    service.refresh_daily(provider=FakeProvider(), sync_scopes=False)

    changed = _flows()
    changed["BK0003"][1] = SectorDailyFlow(
        date(2025, 1, 3), 999.0, 10.0, 10.0, -10.0, -10.0
    )
    result = service.refresh_daily(
        provider=FakeProvider(flows=changed), sync_scopes=False
    )
    assert result["updated"] == 1
    row = service.list_flows(
        trade_date=date(2025, 1, 3), order_by="main_net", limit=10
    )
    food = next(item for item in row if item["sector_code"] == "BK0003")
    assert float(food["main_net"]) == 999.0


def test_ranking_and_history_queries():
    session = _session()
    service = SectorCapitalFlowService(session)
    service.refresh_daily(provider=FakeProvider(), sync_scopes=False)

    assert service.latest_trade_date() == date(2025, 1, 3)

    top = service.list_flows(trade_date=date(2025, 1, 3), limit=2)
    assert [row["sector_code"] for row in top] == ["BK0001", "BK0003"]

    bottom = service.list_flows(
        trade_date=date(2025, 1, 3), direction="asc", limit=1
    )
    assert bottom[0]["sector_code"] == "BK0002"

    history = service.flow_history("bk0001", days=30)
    assert [row["trade_date"] for row in history] == ["2025-01-02", "2025-01-03"]


def test_history_missing_sector_raises():
    session = _session()
    service = SectorCapitalFlowService(session)
    try:
        service.flow_history("BK9999")
    except SectorFlowNotFound:
        return
    raise AssertionError("expected SectorFlowNotFound")


def test_scope_sync_creates_only_and_never_overwrites():
    session = _session()
    service = SectorCapitalFlowService(session)
    provider = FakeProvider()

    result = service.refresh_daily(
        provider=provider, sync_scopes=True, scopes_top=2, scopes_parent="em_industry"
    )
    assert result["scopes_synced"] == 2

    parent = session.get(MarketScope, "em_industry")
    assert parent is not None and parent.scope_type == MarketScopeType.SECTOR

    # A hand-managed scope must not be overwritten by the synced board of same code.
    manual = MarketScope(
        code="BK0003", name="我的食品板块", scope_type=MarketScopeType.SECTOR
    )
    session.add(manual)
    session.commit()

    second = service.refresh_daily(
        provider=provider, sync_scopes=True, scopes_top=3, scopes_parent="em_industry"
    )
    assert second["scopes_synced"] == 0
    session.refresh(manual)
    assert manual.name == "我的食品板块"

    # Tracked-only ranking resolves through the synced scopes.
    codes = service.sector_codes_for_scope("em_industry")
    assert "BK0001" in codes and "BK0002" in codes
    tracked = service.list_flows(
        trade_date=date(2025, 1, 3), scope_codes=codes, limit=10
    )
    assert {row["sector_code"] for row in tracked} <= set(codes)


def test_provider_parses_eastmoney_payloads():
    board_payload = {
        "data": {
            "total": 2,
            "diff": [
                {"f12": "BK1515", "f14": "粮食种植", "f3": 7.84, "f20": 39604976000},
                {"f12": "bk1516", "f14": "林业", "f3": -1.2, "f20": 100},
            ],
        }
    }
    flow_payload = {
        "data": {
            "name": "粮食种植",
            "klines": [
                "2025-01-02,19925156.0,-25851200.0,5926032.0,4907680.0,15017476.0",
                "2025-01-03,1.0,2.0,3.0,4.0,5.0",
            ],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "clist" in str(request.url):
            return httpx.Response(200, json=board_payload)
        return httpx.Response(200, json=flow_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastMoneySectorFlow(client=client)

    boards = provider.industry_boards()
    assert [b.code for b in boards] == ["BK1515", "BK1516"]
    assert boards[0].name == "粮食种植"
    assert boards[0].market_cap == 39604976000

    flows = provider.daily_flows("BK1515", days=2)
    assert len(flows) == 2
    assert flows[0].trade_date == date(2025, 1, 2)
    assert flows[0].super_large_net == 15017476.0
    assert flows[0].small_net == -25851200.0
