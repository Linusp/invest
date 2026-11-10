"""第三方数据与 skill 调用的缓存。

两层用途：
- 结构化数据（Wind 数据工具、问财、iFinD）按内容寻址缓存，降低额度消耗；
- 非结构化 skill（Wind Alice）每次执行都会落一条 ``skill_runs`` 记录，
  缓存命中时不重复执行，但仍可追溯历史结果。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..models import ExternalCache

logger = logging.getLogger(__name__)


def cache_key(source: str, tool: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(
        {"source": source, "tool": tool, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExternalCacheService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.session.get(ExternalCache, key)
        if row is None:
            return None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(tz=timezone.utc):
            self.session.delete(row)
            self.session.commit()
            return None
        try:
            return json.loads(row.payload)
        except ValueError:
            return None

    def put(
        self,
        key: str,
        source: str,
        tool: str,
        payload: dict[str, Any],
        ttl: timedelta,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        row = self.session.get(ExternalCache, key)
        if row is None:
            row = ExternalCache(cache_key=key, source=source, tool=tool)
            self.session.add(row)
        row.source = source
        row.tool = tool
        row.payload = json.dumps(payload, ensure_ascii=False, default=str)
        row.created_at = now
        row.expires_at = now + ttl
        self.session.commit()

    def get_or_fetch(
        self,
        source: str,
        tool: str,
        arguments: dict[str, Any],
        ttl: timedelta,
        fetcher: Callable[[], dict[str, Any]],
        enabled: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        """Return (payload, cache_hit)."""
        key = cache_key(source, tool, arguments)
        if enabled:
            cached = self.get(key)
            if cached is not None:
                logger.info("[cache] hit %s/%s", source, tool)
                return cached, True
        payload = fetcher()
        if enabled:
            self.put(key, source, tool, payload, ttl)
        return payload, False
