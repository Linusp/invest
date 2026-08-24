from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


SUPPORTED_DATABASES = {"sqlite", "postgresql", "mysql"}


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() not in SUPPORTED_DATABASES:
        supported = ", ".join(sorted(SUPPORTED_DATABASES))
        raise ValueError(f"Unsupported database backend; expected one of: {supported}")
    kwargs = {"pool_pre_ping": True}
    if url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


engine = make_engine(get_settings().database_url)
SessionLocal = make_session_factory(engine)


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
