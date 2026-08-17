from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_engine_kwargs = {"pool_pre_ping": True}
if settings.is_sqlite:
    # sqlite runs single-threaded in this process; the default pool and thread
    # check would otherwise refuse to reuse a connection across request threads.
    _engine_kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()