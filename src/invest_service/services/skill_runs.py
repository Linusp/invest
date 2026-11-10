"""非结构化 skill 的执行记录。

Wind Alice 这类工作流没有结构化返回，结果是 Markdown 分析文本。每次真实执行
都落一条记录，便于回看、对比和复用；缓存命中时不重复执行。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SkillRun


class SkillRunService:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        source: str,
        skill: str | None,
        prompt: str,
        output: str,
        duration_ms: int = 0,
        cache_hit: bool = False,
    ) -> int:
        row = SkillRun(
            source=source,
            skill=skill,
            prompt=prompt,
            output=output,
            duration_ms=duration_ms,
            cache_hit=cache_hit,
        )
        self.session.add(row)
        self.session.commit()
        return row.id

    def recent(self, source: str | None = None, limit: int = 20) -> list[SkillRun]:
        stmt = select(SkillRun).order_by(SkillRun.created_at.desc()).limit(limit)
        if source:
            stmt = stmt.where(SkillRun.source == source)
        return list(self.session.scalars(stmt))

    def get(self, run_id: int) -> SkillRun | None:
        return self.session.get(SkillRun, run_id)
