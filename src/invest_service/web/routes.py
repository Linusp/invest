from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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
        return RedirectResponse(f"/market/{quote(legacy_symbol, safe='')}")
    return templates.TemplateResponse(
        request=request,
        name="market.html",
        context={
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/market/{symbol}", response_class=HTMLResponse)
def market_asset(request: Request, symbol: str):
    return templates.TemplateResponse(
        request=request,
        name="market_asset.html",
        context={
            "symbol": symbol.strip().upper(),
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/strategy", response_class=HTMLResponse)
def strategy(request: Request):
    return templates.TemplateResponse(request=request, name="strategy.html")
