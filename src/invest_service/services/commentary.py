import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..commentary_content import (
    content_to_html,
    content_to_markdown,
    normalize_content,
)
from ..models import (
    AnalysisSession,
    Asset,
    AssetCategory,
    Commentary,
    CommentarySource,
    CommentarySubjectType,
    MarketScope,
    Strategy,
    asset_identity,
)
from ..schemas import (
    CommentaryCreate,
    CommentaryRead,
    CommentaryRevisionCreate,
)


class CommentaryNotFound(LookupError):
    pass


class CommentaryService:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self, data: CommentaryCreate, revises_id: str | None = None
    ) -> CommentaryRead:
        asset_key = self._validate_subject(data)
        commentary = Commentary(
            subject_type=data.subject_type,
            market_scope_code=data.market_scope_code,
            portfolio_id=data.portfolio_id,
            asset_key=asset_key,
            analysis_session=data.session,
            trading_date=data.trading_date,
            title=data.title.strip(),
            summary=data.summary,
            content=normalize_content(data.content, data.content_format),
            source=data.source,
            source_ref=data.source_ref,
            data_snapshot=data.data_snapshot,
            has_outlook=data.has_outlook,
            has_risk=data.has_risk,
            has_trade_plan=data.has_trade_plan,
            revises_id=revises_id,
        )
        self.session.add(commentary)
        self.session.commit()
        if asset_key:
            commentary.asset = self.session.get(Asset, asset_key)
        return self._read(commentary)

    def list(
        self,
        subject_type: CommentarySubjectType | None = None,
        market_scope_code: str | None = None,
        portfolio_id: str | None = None,
        asset_symbol: str | None = None,
        asset_category: AssetCategory | None = None,
        analysis_session: AnalysisSession | None = None,
        source: CommentarySource | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommentaryRead]:
        statement = select(Commentary).options(selectinload(Commentary.asset))
        if subject_type is not None:
            statement = statement.where(Commentary.subject_type == subject_type)
        if market_scope_code is not None:
            statement = statement.where(
                Commentary.market_scope_code == market_scope_code.strip().upper()
            )
        if portfolio_id is not None:
            statement = statement.where(Commentary.portfolio_id == portfolio_id)
        if bool(asset_symbol) != bool(asset_category):
            raise ValueError("asset_symbol and asset_category must be provided together")
        if asset_symbol and asset_category:
            statement = statement.where(
                Commentary.asset_key == asset_identity(asset_category, asset_symbol)
            )
        if analysis_session is not None:
            statement = statement.where(
                Commentary.analysis_session == analysis_session
            )
        if source is not None:
            statement = statement.where(Commentary.source == source)
        if start_date is not None:
            statement = statement.where(Commentary.trading_date >= start_date)
        if end_date is not None:
            statement = statement.where(Commentary.trading_date <= end_date)
        statement = statement.order_by(
            Commentary.trading_date.desc(), Commentary.created_at.desc()
        )
        items = list(self.session.scalars(statement))
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in self._search_text(item)]
        return [self._read(item) for item in items[offset : offset + limit]]

    def get(self, commentary_id: str) -> CommentaryRead:
        return self._read(self._get_model(commentary_id))

    def revise(
        self, commentary_id: str, data: CommentaryRevisionCreate
    ) -> CommentaryRead:
        original = self._get_model(commentary_id)
        values = {
            "subject_type": original.subject_type,
            "market_scope_code": original.market_scope_code,
            "portfolio_id": original.portfolio_id,
            "asset_symbol": original.asset.symbol if original.asset else None,
            "asset_category": original.asset.category if original.asset else None,
            "session": original.analysis_session,
            "trading_date": original.trading_date,
            "title": data.title or original.title,
            "summary": (
                data.summary
                if "summary" in data.model_fields_set
                else original.summary
            ),
            "content": data.content,
            "content_format": data.content_format,
            "source": data.source,
            "source_ref": (
                data.source_ref
                if "source_ref" in data.model_fields_set
                else original.source_ref
            ),
            "data_snapshot": (
                data.data_snapshot
                if "data_snapshot" in data.model_fields_set
                else original.data_snapshot
            ),
            "has_outlook": (
                data.has_outlook
                if data.has_outlook is not None
                else original.has_outlook
            ),
            "has_risk": (
                data.has_risk if data.has_risk is not None else original.has_risk
            ),
            "has_trade_plan": (
                data.has_trade_plan
                if data.has_trade_plan is not None
                else original.has_trade_plan
            ),
        }
        return self.create(CommentaryCreate(**values), revises_id=original.id)

    def _get_model(self, commentary_id: str) -> Commentary:
        commentary = self.session.scalar(
            select(Commentary)
            .options(selectinload(Commentary.asset))
            .where(Commentary.id == commentary_id)
        )
        if commentary is None:
            raise CommentaryNotFound(f"Commentary {commentary_id} was not found")
        return commentary

    def _validate_subject(self, data: CommentaryCreate) -> str | None:
        if data.subject_type == CommentarySubjectType.MARKET:
            if self.session.get(MarketScope, data.market_scope_code) is None:
                raise ValueError(
                    f"Market scope {data.market_scope_code} was not found"
                )
            return None
        if data.subject_type == CommentarySubjectType.PORTFOLIO:
            if self.session.get(Strategy, data.portfolio_id) is None:
                raise ValueError(f"Portfolio {data.portfolio_id} was not found")
            return None
        key = asset_identity(data.asset_category, data.asset_symbol)
        if self.session.get(Asset, key) is None:
            raise ValueError(
                f"Asset {data.asset_category.value}:{data.asset_symbol} was not found"
            )
        return key

    @staticmethod
    def _read(commentary: Commentary) -> CommentaryRead:
        asset = commentary.asset
        return CommentaryRead(
            id=commentary.id,
            subject_type=commentary.subject_type,
            market_scope_code=commentary.market_scope_code,
            portfolio_id=commentary.portfolio_id,
            asset_symbol=asset.symbol if asset else None,
            asset_category=asset.category if asset else None,
            session=commentary.analysis_session,
            trading_date=commentary.trading_date,
            title=commentary.title,
            summary=commentary.summary,
            content=commentary.content,
            content_markdown=content_to_markdown(commentary.content),
            content_html=content_to_html(commentary.content),
            source=commentary.source,
            source_ref=commentary.source_ref,
            data_snapshot=commentary.data_snapshot,
            has_outlook=commentary.has_outlook,
            has_risk=commentary.has_risk,
            has_trade_plan=commentary.has_trade_plan,
            revises_id=commentary.revises_id,
            created_at=commentary.created_at,
        )

    @staticmethod
    def _search_text(commentary: Commentary) -> str:
        return " ".join(
            (
                commentary.title,
                commentary.summary or "",
                json.dumps(commentary.content, ensure_ascii=False, default=str),
            )
        ).casefold()
