"""MCP over HTTP 的响应解析：兼容纯 JSON 与 SSE。"""

from __future__ import annotations

import json
from typing import Any


def parse_json_or_sse(text: str) -> dict[str, Any]:
    """把 MCP 响应解析成 dict；纯 JSON 和 ``data: {...}`` 的 SSE 都支持。"""
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("empty MCP response")
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    for line in stripped.splitlines():
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            return json.loads(chunk)
        except ValueError:
            continue
    raise ValueError(f"unparseable MCP response: {stripped[:160]}")
