from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.provider_usage import ProviderUsageService
from ..services.skill_runs import SkillRunService

router = APIRouter(prefix="/external", tags=["external"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/skill-runs")
def list_skill_runs(
    db: DB,
    limit: int = Query(default=20, ge=1, le=100),
    source: str | None = Query(default=None, description="按来源过滤，如 wind_alice"),
):
    """Recent unstructured skill executions (prompt, output, timing)."""
    rows = SkillRunService(db).recent(source=source, limit=limit)
    return [
        {
            "id": row.id,
            "source": row.source,
            "skill": row.skill,
            "prompt": row.prompt,
            "output": row.output,
            "duration_ms": row.duration_ms,
            "cache_hit": row.cache_hit,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/provider-usage")
def provider_usage(db: DB, days: int = Query(default=7, ge=1, le=90)):
    """Daily call counters for metered providers."""
    return ProviderUsageService(db).recent(days=days)
