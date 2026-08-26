from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MarketScope, MarketScopeType
from ..schemas import MarketScopeCreate, MarketScopeUpdate


class MarketScopeNotFound(LookupError):
    pass


class MarketScopeInUse(RuntimeError):
    pass


class MarketScopeService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: MarketScopeCreate) -> MarketScope:
        self._validate_parent(data.code, data.parent_code)
        scope = MarketScope(**data.model_dump())
        scope.name = scope.name.strip()
        self.session.add(scope)
        self.session.commit()
        return scope

    def list(
        self,
        scope_type: MarketScopeType | None = None,
        parent_code: str | None = None,
    ) -> list[MarketScope]:
        query = select(MarketScope)
        if scope_type is not None:
            query = query.where(MarketScope.scope_type == scope_type)
        if parent_code is not None:
            query = query.where(MarketScope.parent_code == parent_code)
        return list(self.session.scalars(query.order_by(MarketScope.code)))

    def get(self, code: str) -> MarketScope:
        scope = self.session.get(MarketScope, code.strip().upper())
        if scope is None:
            raise MarketScopeNotFound(f"Market scope {code} was not found")
        return scope

    def update(self, code: str, data: MarketScopeUpdate) -> MarketScope:
        scope = self.get(code)
        if "parent_code" in data.model_fields_set:
            self._validate_parent(scope.code, data.parent_code)
        for field in ("name", "scope_type", "parent_code", "description"):
            if field in data.model_fields_set:
                value = getattr(data, field)
                if field == "name" and value is not None:
                    value = value.strip()
                setattr(scope, field, value)
        self.session.commit()
        return scope

    def delete(self, code: str) -> None:
        scope = self.get(code)
        child = self.session.scalar(
            select(MarketScope.code).where(MarketScope.parent_code == scope.code).limit(1)
        )
        if child is not None:
            raise MarketScopeInUse(
                f"Market scope {scope.code} cannot be deleted while it has children"
            )
        self.session.delete(scope)
        self.session.commit()

    def _validate_parent(self, code: str, parent_code: str | None) -> None:
        if parent_code is None:
            return
        if parent_code == code:
            raise ValueError("market scope cannot be its own parent")
        parent = self.session.get(MarketScope, parent_code)
        if parent is None:
            raise ValueError(f"Parent market scope {parent_code} was not found")
        visited = {code}
        while parent is not None:
            if parent.code in visited:
                raise ValueError("market scope hierarchy cannot contain a cycle")
            visited.add(parent.code)
            parent = (
                self.session.get(MarketScope, parent.parent_code)
                if parent.parent_code
                else None
            )
