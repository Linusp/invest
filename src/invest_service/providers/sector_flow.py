"""EastMoney sector (板块) capital-flow data access.

Ported from the MIT-licensed project *CapitalPulse* by 阿溪研究点啥
(https://github.com/Dr-Liu23/CapitalPulse) and adapted to the Invest Service
sync-request / persistence conventions. See backend/services/sector_flow_upstream.py
upstream for the reference implementation.

EastMoney does not expose a clean official industry list; the "行业板块"
endpoint (``m:90+t:2``) returns a granular BK board pool (hundreds of boards).
We fetch the whole pool as *data* and let callers decide which boards to
promote into market scopes. Each BK board has its own ``secid=90.<BK>`` daily
capital-flow history (主力/超大/大/中/小净流入).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": DEFAULT_UA, "Referer": "https://data.eastmoney.com/"}

SECTOR_LIST_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
SECTOR_LIST_FALLBACK_URL = "https://push2.eastmoney.com/api/qt/clist/get"
SECTOR_DAILY_FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
SECTOR_DAILY_FLOW_FALLBACK_URL = (
    "https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get"
)
SECTOR_INTRADAY_FLOW_URL = "https://push2delay.eastmoney.com/api/qt/stock/fflow/kline/get"
SECTOR_INTRADAY_FLOW_FALLBACK_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
)

REQUEST_TIMEOUT = 12.0
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 0.5
SECTOR_FS = "m:90+t:2+f:!50"
SECTOR_FIELDS = "f3,f12,f14,f20"
# kline day fields: date, main, small, mid, large, super_large net flow (yuan)
DAILY_FLOW_FIELDS = "f51,f52,f53,f54,f55,f56"


class SectorFlowError(RuntimeError):
    """Raised when the EastMoney sector-flow upstream is unavailable/invalid."""


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_params(overrides: dict[str, Any]) -> dict[str, Any]:
    """EastMoney push endpoints require these request tokens."""
    return {
        "ut": "7eea3edcaed734bea9telecast",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "_": str(int(time.time() * 1000)),
        **overrides,
    }


@dataclass(frozen=True)
class SectorBoard:
    """One EastMoney BK board from the industry pool."""

    code: str
    name: str
    change_percent: float
    market_cap: float  # total market cap in CNY


@dataclass(frozen=True)
class SectorDailyFlow:
    """One trading day of net flows for a board (values in CNY)."""

    trade_date: date
    main_net: float
    super_large_net: float
    large_net: float
    mid_net: float
    small_net: float


def _get(client: httpx.Client, url: str, fallback_url: str, params: dict[str, Any]) -> Any:
    """GET one EastMoney JSON payload, retrying and falling back to a mirror host."""
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        for candidate in (url, fallback_url):
            try:
                response = client.get(
                    candidate,
                    params=params,
                    headers={"Referer": "https://data.eastmoney.com/"},
                )
                response.raise_for_status()
                payload = response.json()
                if payload is not None:
                    return payload
            except (httpx.HTTPError, ValueError) as exc:  # network or bad JSON
                last_error = exc
                logger.warning(
                    "[sector-flow] fetch failed url=%s attempt=%s err=%s",
                    candidate,
                    attempt,
                    exc,
                )
        time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
    raise SectorFlowError(f"EastMoney sector-flow upstream unavailable: {last_error}")


class EastMoneySectorFlow:
    """Blocking client for EastMoney sector capital-flow endpoints."""

    name = "eastmoney-sector-flow"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=REQUEST_TIMEOUT, headers=DEFAULT_HEADERS)

    def industry_boards(self) -> list[SectorBoard]:
        """Fetch the full EastMoney BK industry pool (may be several hundred boards)."""
        boards: list[SectorBoard] = []
        seen: set[str] = set()
        page = 1
        page_size = 100
        while True:
            payload = _get(
                self.client,
                SECTOR_LIST_URL,
                SECTOR_LIST_FALLBACK_URL,
                _build_params(
                    {
                        "dpt": "wz.zhyj",
                        "Ession": "",
                        "fs": SECTOR_FS,
                        "fields": SECTOR_FIELDS,
                        "pn": str(page),
                        "pz": str(page_size),
                        "po": "1",
                        "fid": "f3",
                    }
                ),
            )
            data = payload.get("data") or {}
            items = data.get("diff") or []
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("f12") or "").strip().upper()
                name = str(item.get("f14") or "").strip()
                if not code or not name or code in seen:
                    continue
                seen.add(code)
                boards.append(
                    SectorBoard(
                        code=code,
                        name=name,
                        change_percent=round(_number(item.get("f3")), 4),
                        market_cap=_number(item.get("f20")),
                    )
                )
            try:
                total = int(data.get("total") or len(boards))
            except (TypeError, ValueError):
                total = len(boards)
            if len(boards) >= total or len(items) < page_size:
                break
            page += 1
            if page > 20:  # refuse to paginate forever
                logger.warning("[sector-flow] stopped paging at board #%s", len(boards))
                break
        if not boards:
            raise SectorFlowError("EastMoney returned no industry boards")
        return boards

    def daily_flows(self, code: str, days: int = 30) -> list[SectorDailyFlow]:
        """Fetch up to ``days`` trading days of net flows for one BK board."""
        code = code.strip().upper()
        if not code or len(code) > 16:
            raise SectorFlowError(f"invalid sector code: {code!r}")
        payload = _get(
            self.client,
            SECTOR_DAILY_FLOW_URL,
            SECTOR_DAILY_FLOW_FALLBACK_URL,
            {
                "lmt": str(days),
                "klt": "101",
                "secid": f"90.{code}",
                "fields1": "f1,f2,f3,f7",
                "fields2": DAILY_FLOW_FIELDS,
                "_": str(int(time.time() * 1000)),
            },
        )
        data = payload.get("data") or {}
        klines = data.get("klines") or []
        flows: list[SectorDailyFlow] = []
        for kline in klines:
            if not isinstance(kline, str):
                continue
            parts = kline.split(",")
            if len(parts) < 6 or not parts[0]:
                continue
            try:
                trade_date = date.fromisoformat(parts[0])
            except ValueError:
                continue
            flows.append(
                SectorDailyFlow(
                    trade_date=trade_date,
                    main_net=_number(parts[1]),
                    small_net=_number(parts[2]),
                    mid_net=_number(parts[3]),
                    large_net=_number(parts[4]),
                    super_large_net=_number(parts[5]),
                )
            )
        if not flows:
            raise SectorFlowError(f"EastMoney returned no daily flows for {code}")
        return flows

    def intraday_flows(self, code: str) -> list[dict[str, Any]]:
        """Fetch today's 1-minute cumulative net-flow series for one BK board.

        EastMoney returns the whole session in one request (240 points), so a
        periodic refresh simply overwrites the same timestamps.
        """
        code = code.strip().upper()
        if not code or len(code) > 16:
            raise SectorFlowError(f"invalid sector code: {code!r}")
        payload = _get(
            self.client,
            SECTOR_INTRADAY_FLOW_URL,
            SECTOR_INTRADAY_FLOW_FALLBACK_URL,
            {
                "lmt": "0",
                "klt": "1",
                "secid": f"90.{code}",
                "fields1": "f1,f2,f3,f7",
                "fields2": DAILY_FLOW_FIELDS,
                "_": str(int(time.time() * 1000)),
            },
        )
        data = payload.get("data") or {}
        points: list[dict[str, Any]] = []
        for kline in data.get("klines") or []:
            if not isinstance(kline, str):
                continue
            parts = kline.split(",")
            if len(parts) < 6 or not parts[0]:
                continue
            try:
                ts = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            points.append(
                {
                    "ts": ts,
                    "main_net": _number(parts[1]),
                    "small_net": _number(parts[2]),
                    "mid_net": _number(parts[3]),
                    "large_net": _number(parts[4]),
                    "super_large_net": _number(parts[5]),
                }
            )
        if not points:
            raise SectorFlowError(f"EastMoney returned no intraday flows for {code}")
        return points

    def refresh_snapshot(self, days: int = 30) -> list[dict[str, Any]]:
        """Convenience: boards plus their daily flows, ready for persistence.

        Returns a list of dicts shaped for the SectorCapitalFlow model.
        """
        rows: list[dict[str, Any]] = []
        for board in self.industry_boards():
            try:
                flows = self.daily_flows(board.code, days=days)
            except SectorFlowError as exc:
                logger.warning("[sector-flow] skip %s(%s): %s", board.name, board.code, exc)
                continue
            for flow in flows:
                rows.append(
                    {
                        "sector_code": board.code,
                        "sector_name": board.name,
                        "trade_date": flow.trade_date,
                        "interval": "1d",
                        "main_net": flow.main_net,
                        "super_large_net": flow.super_large_net,
                        "large_net": flow.large_net,
                        "mid_net": flow.mid_net,
                        "small_net": flow.small_net,
                        "change_percent": board.change_percent,
                        "market_cap": board.market_cap,
                        "source": "eastmoney",
                    }
                )
        return rows
