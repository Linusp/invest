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
    return templates.TemplateResponse(
        request=request,
        name="market.html",
        context={
            "market_provider_warning": request.app.state.market_provider_warning,
        },
    )


@router.get("/strategy", response_class=HTMLResponse)
def strategy(request: Request):
    return templates.TemplateResponse(request=request, name="strategy.html")
