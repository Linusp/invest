from pathlib import Path

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
    return templates.TemplateResponse(request=request, name="market.html")


@router.get("/strategy", response_class=HTMLResponse)
def strategy(request: Request):
    return templates.TemplateResponse(request=request, name="strategy.html")


@router.get("/invest/market", response_class=RedirectResponse)
def legacy_market():
    return RedirectResponse("/market")


@router.get("/invest/strategy", response_class=RedirectResponse)
def legacy_strategy():
    return RedirectResponse("/strategy")


@router.get("/invest/chart", response_class=RedirectResponse)
def legacy_chart(request: Request):
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/market{query}")
