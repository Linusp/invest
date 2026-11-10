from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ..config import get_settings
from ..database import Base
from ..models import Asset, AssetCategory, AssetSearchIndex

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt():
    """Publish a concise, stable orientation for AI agents and tooling."""
    return """# Invest Service

> 本地投资数据服务，提供标的搜索、行情历史、自选分组、组合账本、点评、资讯和交易计划。

Invest exposes both a REST API and an MCP server. Use the MCP server for agent tool
calls; use the REST API or the web pages when a human-facing workflow is needed.

## Machine-readable interfaces

- [OpenAPI schema](/openapi.json): complete REST API schema and parameter definitions.
- [MCP Streamable HTTP](/mcp/): MCP endpoint with the full tool set.
- [MCP integration guide](/docs/guide): HTTP and stdio setup for coding agents.

## Human-readable documentation

- [REST API reference](/docs/api): business concepts, endpoint overview and MCP tool coverage.
- [Market data guide](/docs/market-data): providers, search index and scheduled updates.
- [Information ingestion guide](/docs/information): submitting and associating external information.
- [Portfolio, commentary and trade-plan requirements](/docs/portfolio-commentary-trade-plan-prd.md):
  domain rules and workflows.

## Main web pages

- [/favorites](/favorites): browse and manage favorite assets.
- [/asset/{category}/{symbol}](/asset/stock/600000.SH): view an asset's quote, K-line,
  history, commentaries and related information.
- [/strategy](/strategy): manage portfolios, positions, trades, commentaries and trade plans.
- [/analysis](/analysis): manage market, sector, theme and commodity scopes.
- [/information](/information): browse submitted information and open full details.
- [/capabilities](/capabilities): data tables, sources with quotas, MCP tools, tasks and limits.

## Agent usage notes

- Asset identity is `category + symbol`; pass both when a symbol may be ambiguous.
- Commentary and information content can be requested from MCP as Markdown (default)
  or structured blocks.
- Creating or changing a trade plan never writes a trade automatically; adding a trade
  is a separate operation.
- MCP Host/Origin checks are not authentication. Production deployments should add
  authentication and HTTPS at the gateway.
"""


@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/strategy")


@router.get("/favorites", response_class=HTMLResponse)
def favorites(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="market.html",
        context={
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/asset/{category}/{symbol}", response_class=HTMLResponse)
def asset(request: Request, category: AssetCategory, symbol: str):
    return templates.TemplateResponse(
        request=request,
        name="market_asset.html",
        context={
            "symbol": symbol.strip().upper(),
            "category": category.value,
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/market", response_class=RedirectResponse)
def legacy_market(request: Request):
    legacy_symbol = request.query_params.get("symbol") or request.query_params.get("code")
    if legacy_symbol:
        category = _legacy_category(request, legacy_symbol)
        normalized = quote(legacy_symbol.strip().upper(), safe="")
        return RedirectResponse(f"/asset/{category.value}/{normalized}")
    return RedirectResponse("/favorites")


@router.get("/market/{category}/{symbol}", response_class=RedirectResponse)
def legacy_market_asset_category(category: AssetCategory, symbol: str):
    return RedirectResponse(f"/asset/{category.value}/{quote(symbol.strip().upper(), safe='')}")


@router.get("/market/{symbol}", response_class=RedirectResponse)
def legacy_market_asset(request: Request, symbol: str):
    category = _legacy_category(request, symbol)
    return RedirectResponse(
        f"/asset/{category.value}/{quote(symbol.strip().upper(), safe='')}"
    )


def _legacy_category(request: Request, symbol: str) -> AssetCategory:
    normalized = symbol.strip().upper()
    with request.app.state.session_factory() as session:
        categories = set(
            session.scalars(
                select(AssetSearchIndex.category).where(
                    AssetSearchIndex.symbol == normalized
                )
            )
        )
        categories.update(
            session.scalars(
                select(Asset.category).where(Asset.symbol == normalized)
            )
        )
    if len(categories) == 1:
        return categories.pop()
    if not categories:
        raise HTTPException(status_code=404, detail=f"Asset {normalized} was not found")
    raise HTTPException(
        status_code=409,
        detail=f"Asset {normalized} has multiple categories; use a category-specific URL",
    )


@router.get("/strategy", response_class=HTMLResponse)
def strategy(request: Request):
    return templates.TemplateResponse(request=request, name="strategy.html")


@router.get("/analysis", response_class=HTMLResponse)
def analysis(request: Request):
    return templates.TemplateResponse(request=request, name="analysis.html")


@router.get("/capabilities", response_class=HTMLResponse)
def capabilities(request: Request):
    """能力清单：数据、来源、工具、定时任务与边界。"""
    from .capabilities import BOUNDARIES, DATA_TABLES, PROVIDERS, TOOL_GROUPS

    settings = get_settings()

    from ..celery_app import build_beat_schedule

    schedule = build_beat_schedule(settings)
    tasks = [
        {
            "name": name,
            "task": entry.get("task", ""),
            "cadence": _describe_schedule(entry.get("schedule")),
        }
        for name, entry in schedule.items()
    ]

    providers = [
        {
            "key": item["key"],
            "name": item["name"],
            "coverage": item["coverage"],
            "limit": getattr(settings, item["limit_setting"], 0),
        }
        for item in PROVIDERS
    ]

    known = set(DATA_TABLES)
    extra = sorted(
        name
        for name in Base.metadata.tables
        if name not in known and name != "asset_tags"
    )
    tables = [{"name": name, "desc": DATA_TABLES[name]} for name in DATA_TABLES]
    tables += [{"name": name, "desc": "关联表"} for name in extra]

    groups = [
        {"name": group["name"], "tools": group["tools"], "count": len(group["tools"])}
        for group in TOOL_GROUPS
    ]
    total_tools = sum(group["count"] for group in groups)

    return templates.TemplateResponse(
        request=request,
        name="capabilities.html",
        context={
            "active_page": "capabilities",
            "groups": groups,
            "total_tools": total_tools,
            "providers": providers,
            "priority": settings.provider_priority,
            "tasks": tasks,
            "tables": tables,
            "boundaries": BOUNDARIES,
            "cache_enabled": settings.external_cache_enabled,
        },
    )


def _describe_schedule(schedule) -> str:
    if isinstance(schedule, int):
        return f"每 {schedule // 60} 分钟"
    hour = getattr(schedule, "_orig_hour", None)
    minute = getattr(schedule, "_orig_minute", None)
    if hour is not None and minute is not None:
        return f"每天 {hour:02d}:{minute:02d}"
    return str(schedule)


@router.get("/information", response_class=HTMLResponse)
def information(request: Request):
    return templates.TemplateResponse(request=request, name="information.html")


@router.get("/information/{information_id}", response_class=HTMLResponse)
def information_detail(request: Request, information_id: str):
    return templates.TemplateResponse(
        request=request, name="information_detail.html", context={"information_id": information_id}
    )
