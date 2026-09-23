import os
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.db import Base, session_factory
from backend.app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def engine():
    # TEST_DATABASE_URL deve apontar SOMENTE para um banco descartável de testes.
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        eng = create_engine(url)
        assert eng.url.database.endswith("_test"), "Use um banco dedicado com sufixo _test."
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(eng, "connect")
        def foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine)) as c:
        yield c


@pytest.fixture
def factory(engine):
    return session_factory(engine)
