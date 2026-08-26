from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ..models import Asset, AssetCategory, AssetSearchIndex

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/strategy")


@router.get("/market", response_class=HTMLResponse)
def market(request: Request):
    legacy_symbol = request.query_params.get("symbol") or request.query_params.get("code")
    if legacy_symbol:
        category = _legacy_category(request, legacy_symbol)
        return RedirectResponse(
            f"/market/{category.value}/{quote(legacy_symbol.strip().upper(), safe='')}"
        )
    return templates.TemplateResponse(
        request=request,
        name="market.html",
        context={
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/market/{category}/{symbol}", response_class=HTMLResponse)
def market_asset(request: Request, category: AssetCategory, symbol: str):
    return templates.TemplateResponse(
        request=request,
        name="market_asset.html",
        context={
            "symbol": symbol.strip().upper(),
            "category": category.value,
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/market/{symbol}", response_class=RedirectResponse)
def legacy_market_asset(request: Request, symbol: str):
    category = _legacy_category(request, symbol)
    return RedirectResponse(
        f"/market/{category.value}/{quote(symbol.strip().upper(), safe='')}"
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
