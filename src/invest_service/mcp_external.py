"""对外部能力的 MCP 工具注册。

结构化数据（Wind 数据工具、问财、iFinD）走「内容寻址缓存 + TTL」；
非结构化 skill（Wind Alice）每次执行落 ``skill_runs``，缓存命中不重复执行。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .providers.ifind_mcp import IfindMcpClient
from .providers.iwencai import IwencaiProvider
from .providers.wind_skills import (
    ALICE_SKILLS,
    DATA_TOOLS,
    WindAliceClient,
    WindDataTools,
    WindSkillError,
    resolve_alice_skill,
)
from .providers.yingmi import YingmiMcpClient
from .services.external_cache import ExternalCacheService, cache_key
from .services.provider_usage import ProviderUsageService
from .services.skill_runs import SkillRunService

logger = logging.getLogger(__name__)

WIND_DATA_TTL = timedelta(hours=6)
ALICE_TTL = timedelta(hours=24)
YINGMI_FUND_TTL = timedelta(hours=6)
YINGMI_NEWS_TTL = timedelta(hours=3)
IFIND_NEWS_TTL = timedelta(hours=3)
IFIND_SECTOR_TTL = timedelta(hours=6)
IWENCAI_TTL = timedelta(hours=6)


def _require_wind_key() -> str:
    key = get_settings().wind_key()
    if not key:
        raise WindSkillError("WIND_API_KEY 未配置，无法调用 Wind 能力")
    return key


def _metered(session, provider: str, limit: int, fetch):
    """先检查当日额度，再执行并记账；缓存命中的路径不会走到这里。"""
    usage = ProviderUsageService(session)
    try:
        usage.ensure_capacity(provider, limit)
    except ValueError as exc:
        raise WindSkillError(str(exc)) from exc
    payload = fetch()
    usage.record(provider)
    return payload


def _require_yingmi_key() -> str:
    key = get_settings().yingmi_api_key
    if not key:
        raise WindSkillError("INVEST_YINGMI_API_KEY 未配置，无法调用盈米能力")
    return key


def _yingmi_call(session, tool: str, arguments: dict, ttl: timedelta, refresh: bool):
    """统一处理盈米工具的缓存与额度记账。"""
    settings = get_settings()
    key = _require_yingmi_key()
    cache = ExternalCacheService(session)

    def fetch() -> dict[str, Any]:
        payload = _metered(
            session,
            "yingmi",
            settings.yingmi_daily_limit,
            lambda: YingmiMcpClient(key).call(tool, arguments),
        )
        return {"tool": tool, "data": payload}

    payload, hit = cache.get_or_fetch(
        "yingmi",
        tool,
        arguments,
        ttl,
        fetch,
        enabled=settings.external_cache_enabled and not refresh,
    )
    return {**payload, "cached": hit}


def _require_ifind_key() -> str:
    key = get_settings().ifind_key()
    if not key:
        raise WindSkillError("IFIND_MCP_KEY 未配置，无法调用 iFinD 能力")
    return key


def _ifind_news_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """iFinD 把新闻列表塞在 data.data 的 JSON 字符串里。"""
    data = payload.get("data")
    raw = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def _ifind_markdown(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        answer = data.get("answer")
        if isinstance(answer, str):
            return answer
    return ""


def register_external_tools(mcp: FastMCP, session_factory: sessionmaker) -> None:
    @mcp.tool()
    def wind_data(tool: str, question: str, refresh: bool = False) -> dict:
        """Query Wind's structured data tools with natural language.

        ``tool`` must be one of: get_stock_summary, get_stock_fundamentals,
        get_stock_equity_holders, get_risk_metrics, get_stock_events,
        get_stock_technicals, search_stocks. ``question`` should name the
        security and the fields you want (e.g. "贵州茅台 2025年报 ROE 毛利率").
        Results are cached for 6 hours; pass refresh=True to bypass the cache.
        """
        if tool not in DATA_TOOLS:
            raise WindSkillError(
                f"tool 必须是以下之一: {', '.join(sorted(DATA_TOOLS))}"
            )
        key = _require_wind_key()
        arguments = {"tool": tool, "question": question}
        with session_factory() as session:
            cache = ExternalCacheService(session)

            def fetch() -> dict[str, Any]:
                return _metered(
                    session,
                    "wind",
                    get_settings().wind_daily_limit,
                    lambda: WindDataTools(key).call(tool, question),
                )

            payload, hit = cache.get_or_fetch(
                "wind",
                tool,
                arguments,
                WIND_DATA_TTL,
                fetch,
                enabled=get_settings().external_cache_enabled and not refresh,
            )
        return {**payload, "cached": hit}

    @mcp.tool()
    def wind_alice(prompt: str, skill: str | None = None, refresh: bool = False) -> dict:
        """Run a Wind Alice research workflow and store the result.

        Use for company one-pagers, earnings reviews, comparables, thematic
        screening, fact checks, macro/bond/credit analysis. ``skill`` accepts
        the Chinese or English name (e.g. "公司一页纸" / "Company One-Page
        Investment Memo"); omit it to let Alice decide. Results are cached for
        24 hours and every run is recorded in ``list_skill_runs``.
        """
        if not prompt.strip():
            raise WindSkillError("prompt 不能为空")
        resolved = resolve_alice_skill(skill)
        key = _require_wind_key()
        arguments = {"prompt": prompt, "skill": resolved.zh if resolved else None}
        settings = get_settings()

        with session_factory() as session:
            cache = ExternalCacheService(session)
            runs = SkillRunService(session)

            cached = None
            if settings.external_cache_enabled and not refresh:
                cached = cache.get(cache_key("wind_alice", "alice", arguments))
            if cached is not None:
                run_id = runs.record(
                    source="wind_alice",
                    skill=resolved.zh if resolved else None,
                    prompt=prompt,
                    output=str(cached.get("output", "")),
                    duration_ms=0,
                    cache_hit=True,
                )
                return {
                    "run_id": run_id,
                    "cached": True,
                    "skill": resolved.zh if resolved else None,
                    "output": cached.get("output", ""),
                }

            started = time.monotonic()
            output = _metered(
                session,
                "wind",
                settings.wind_daily_limit,
                lambda: WindAliceClient(key).run(prompt, resolved),
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            run_id = runs.record(
                source="wind_alice",
                skill=resolved.zh if resolved else None,
                prompt=prompt,
                output=output,
                duration_ms=duration_ms,
                cache_hit=False,
            )
            if settings.external_cache_enabled:
                cache.put(
                    cache_key("wind_alice", "alice", arguments),
                    "wind_alice",
                    "alice",
                    {"output": output},
                    ALICE_TTL,
                )
        return {
            "run_id": run_id,
            "cached": False,
            "skill": resolved.zh if resolved else None,
            "duration_ms": duration_ms,
            "output": output,
        }

    @mcp.tool()
    def ifind_news(
        query: str,
        time_start: str,
        time_end: str,
        size: int = 5,
        refresh: bool = False,
    ) -> dict:
        """Search iFinD financial news snippets for a subject.

        ``time_start`` / ``time_end`` use YYYY-MM-DD. Returns title, content,
        date and URL for each hit. Cached for 3 hours.
        """
        key = _require_ifind_key()
        arguments = {
            "query": query,
            "time_start": time_start,
            "time_end": time_end,
            "size": size,
        }
        with session_factory() as session:
            cache = ExternalCacheService(session)

            def fetch() -> dict[str, Any]:
                payload = _metered(
                    session,
                    "ifind",
                    get_settings().ifind_daily_limit,
                    lambda: IfindMcpClient(key).call(
                        "news",
                        "search_news",
                        {
                            "query": query,
                            "size": size,
                            "time_start": time_start,
                            "time_end": time_end,
                        },
                    ),
                )
                return {"items": _ifind_news_items(payload)}

            payload, hit = cache.get_or_fetch(
                "ifind_news",
                "search_news",
                arguments,
                IFIND_NEWS_TTL,
                fetch,
                enabled=get_settings().external_cache_enabled and not refresh,
            )
        return {**payload, "cached": hit}

    @mcp.tool()
    def ifind_notices(
        query: str,
        time_start: str,
        time_end: str,
        size: int = 5,
        refresh: bool = False,
    ) -> dict:
        """Search iFinD company announcements (公告) for a subject.

        Same parameters and caching as ``ifind_news``.
        """
        key = _require_ifind_key()
        arguments = {
            "query": query,
            "time_start": time_start,
            "time_end": time_end,
            "size": size,
        }
        with session_factory() as session:
            cache = ExternalCacheService(session)

            def fetch() -> dict[str, Any]:
                payload = _metered(
                    session,
                    "ifind",
                    get_settings().ifind_daily_limit,
                    lambda: IfindMcpClient(key).call(
                        "news",
                        "search_notice",
                        {
                            "query": query,
                            "size": size,
                            "time_start": time_start,
                            "time_end": time_end,
                        },
                    ),
                )
                return {"items": _ifind_news_items(payload)}

            payload, hit = cache.get_or_fetch(
                "ifind_notice",
                "search_notice",
                arguments,
                IFIND_NEWS_TTL,
                fetch,
                enabled=get_settings().external_cache_enabled and not refresh,
            )
        return {**payload, "cached": hit}

    @mcp.tool()
    def ifind_sector(query: str, refresh: bool = False) -> dict:
        """Query iFinD sector (板块) data such as constituents and flows.

        ``query`` is natural language, e.g. "电子板块 20261105-20261110 成份股个数".
        Returns the Markdown table iFinD produces. Cached for 6 hours.
        """
        key = _require_ifind_key()
        with session_factory() as session:
            cache = ExternalCacheService(session)

            def fetch() -> dict[str, Any]:
                payload = _metered(
                    session,
                    "ifind",
                    get_settings().ifind_daily_limit,
                    lambda: IfindMcpClient(key).call(
                        "index", "sector_data", {"query": query}
                    ),
                )
                return {"markdown": _ifind_markdown(payload)}

            payload, hit = cache.get_or_fetch(
                "ifind_sector",
                "sector_data",
                {"query": query},
                IFIND_SECTOR_TTL,
                fetch,
                enabled=get_settings().external_cache_enabled and not refresh,
            )
        return {**payload, "cached": hit}

    @mcp.tool()
    def iwencai_screen(question: str, limit: int = 50, refresh: bool = False) -> dict:
        """Screen A-share stocks with an iWenCai natural-language query.

        Example: "总市值大于1000亿 且 市盈率小于15 的股票，返回代码、简称、PE、股息率".
        Returns the rows iWenCai produced plus ``count``. Cached for 6 hours.
        """
        settings = get_settings()
        provider = IwencaiProvider(settings.iwencai_api_key)
        if not settings.iwencai_api_key:
            raise WindSkillError("IWENCAI_API_KEY 未配置，无法调用问财")
        with session_factory() as session:
            cache = ExternalCacheService(session)

            def fetch() -> dict[str, Any]:
                payload = _metered(
                    session,
                    "iwencai",
                    settings.iwencai_daily_limit,
                    lambda: provider.query(question, limit=min(limit, 100)),
                )
                return {
                    "count": payload.get("code_count"),
                    "rows": payload.get("datas") or [],
                }

            payload, hit = cache.get_or_fetch(
                "iwencai",
                "screen",
                {"question": question, "limit": min(limit, 100)},
                IWENCAI_TTL,
                fetch,
                enabled=settings.external_cache_enabled and not refresh,
            )
        return {**payload, "cached": hit}

    @mcp.tool()
    def yingmi_fund_search(keyword: str, limit: int = 10, refresh: bool = False) -> dict:
        """Search funds by name or code (盈米).

        Returns fundCode, fundName, type, setup date and year-to-date return.
        Cached for 6 hours.
        """
        with session_factory() as session:
            return _yingmi_call(
                session,
                "SearchFunds",
                {"keyword": keyword, "page": 0, "size": min(limit, 50)},
                YINGMI_FUND_TTL,
                refresh,
            )

    @mcp.tool()
    def yingmi_fund_detail(fund_codes: list[str], refresh: bool = False) -> dict:
        """Fund profile: tags, fees, manager, scale, benchmark (盈米)."""
        with session_factory() as session:
            return _yingmi_call(
                session, "BatchGetFundsDetail", {"fundCodes": fund_codes}, YINGMI_FUND_TTL, refresh
            )

    @mcp.tool()
    def yingmi_fund_performance(fund_codes: list[str], refresh: bool = False) -> dict:
        """Fund performance table across horizons plus risk-control metrics (盈米)."""
        with session_factory() as session:
            return _yingmi_call(
                session,
                "GetBatchFundPerformance",
                {"fundCodes": fund_codes},
                YINGMI_FUND_TTL,
                refresh,
            )

    @mcp.tool()
    def yingmi_fund_nav(
        fund_codes: list[str],
        dimension: str = "oneMonth",
        refresh: bool = False,
    ) -> dict:
        """Fund NAV history (盈米).

        dimension: oneMonth / quarter / halfYear / oneYear / threeYear / fiveYear.
        """
        with session_factory() as session:
            return _yingmi_call(
                session,
                "BatchGetFundNavHistory",
                {"fundCodes": fund_codes, "dimensionType": dimension},
                YINGMI_FUND_TTL,
                refresh,
            )

    @mcp.tool()
    def yingmi_fund_risk(fund_codes: list[str], refresh: bool = False) -> dict:
        """Fund risk metrics: Sharpe, max drawdown, volatility (盈米)."""
        with session_factory() as session:
            return _yingmi_call(
                session, "AnalyzeFundRisk", {"fundCodes": fund_codes}, YINGMI_FUND_TTL, refresh
            )

    @mcp.tool()
    def yingmi_fund_diagnosis(fund_code: str, refresh: bool = False) -> dict:
        """Full fund diagnosis: risk, valuation, industry, style, holdings (盈米)."""
        with session_factory() as session:
            return _yingmi_call(
                session,
                "GetFundDiagnosis",
                {"fundCode": fund_code},
                YINGMI_FUND_TTL,
                refresh,
            )

    @mcp.tool()
    def yingmi_fund_news(
        keyword: str,
        start_date: str | None = None,
        end_date: str | None = None,
        page_size: int = 10,
        refresh: bool = False,
    ) -> dict:
        """Fund-related financial news search (盈米), dates as YYYY-MM-DD."""
        arguments: dict[str, Any] = {"keyword": keyword, "page": 1, "pageSize": min(page_size, 20)}
        if start_date:
            arguments["startDate"] = start_date
        if end_date:
            arguments["endDate"] = end_date
        with session_factory() as session:
            return _yingmi_call(session, "SearchFinancialNews", arguments, YINGMI_NEWS_TTL, refresh)

    @mcp.tool()
    def list_skill_runs(limit: int = 20, source: str | None = None) -> list[dict]:
        """List recent unstructured skill runs (prompt, skill, output, timing)."""
        with session_factory() as session:
            rows = SkillRunService(session).recent(source=source, limit=min(limit, 100))
            return [
                {
                    "id": row.id,
                    "source": row.source,
                    "skill": row.skill,
                    "prompt": row.prompt,
                    "output": row.output,
                    "duration_ms": row.duration_ms,
                    "cache_hit": row.cache_hit,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    logger.info(
        "[external] registered wind tools; alice skills=%s",
        len(ALICE_SKILLS),
    )
