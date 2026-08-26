from .assets import router as assets_router
from .exchange_rates import router as exchange_rates_router
from .portfolios import router as portfolios_router
from .strategies import router as strategies_router
from .tags import router as tags_router

__all__ = [
    "assets_router",
    "exchange_rates_router",
    "portfolios_router",
    "strategies_router",
    "tags_router",
]
