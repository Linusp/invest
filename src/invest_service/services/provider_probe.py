"""探测被熔断的 provider 是否恢复。

只做「不会消耗业务额度」的最轻量探测（MCP initialize）；对按天计次的
provider（iwencai / indexhub）不做探测，它们的熔断由次日自动过期。
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..providers.ifind_mcp import IfindMcpClient
from ..providers.miaoxiang import MxMcpClient
from ..providers.wind import WindMcpClient
from ..providers.yingmi import YingmiMcpClient

logger = logging.getLogger(__name__)


def probe_provider(provider: str, settings: Settings) -> tuple[bool, str]:
    """Returns (ok, detail). 只处理能安全 ping 的 provider。"""
    try:
        if provider == "wind":
            key = settings.wind_key()
            if not key:
                return False, "WIND key 未配置"
            WindMcpClient(key).ping()
            return True, "wind initialize ok"
        if provider == "ifind":
            key = settings.ifind_key()
            if not key:
                return False, "iFinD key 未配置"
            IfindMcpClient(key).ping()
            return True, "ifind initialize ok"
        if provider == "yingmi":
            key = settings.yingmi_api_key
            if not key:
                return False, "盈米 key 未配置"
            YingmiMcpClient(key).ping()
            return True, "yingmi initialize ok"
        if provider == "mx":
            key = settings.mx_api_key
            if not key:
                return False, "妙想 key 未配置"
            MxMcpClient(key).ping()
            return True, "mx initialize ok"
    except Exception as exc:  # noqa: BLE001 - 探测失败不应抛出
        return False, str(exc)[:300]
    return False, "该 provider 不支持自动探测"
