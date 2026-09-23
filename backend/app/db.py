import os

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        if os.environ.get("PGHOST") and os.environ.get("PGPASSWORD"):
            return URL.create("postgresql+psycopg", username=os.environ.get("PGUSER", "separador"),
                              password=os.environ["PGPASSWORD"], host=os.environ["PGHOST"],
                              port=int(os.environ.get("PGPORT", "5432")),
                              database=os.environ.get("PGDATABASE", "separador_materiais"))
        raise RuntimeError("Configure DATABASE_URL ou PGHOST/PGUSER/PGPASSWORD/PGDATABASE.")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Esta API requer PostgreSQL (postgresql+psycopg://).")
    return url


def make_engine(url=None):
    return create_engine(url or database_url(), pool_pre_ping=True)


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
