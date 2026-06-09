from __future__ import annotations

import pytest

from app.db.database import configure_test_database, get_session_local
from app.db.models import Base


@pytest.fixture(autouse=True)
def _clear_encoder_cache():
    """Isolate the process-level E5 model cache between tests so a mocked
    SentenceTransformer in one test can't leak into another (and vice-versa)."""
    from app.ingestion.embedder import _ENCODER_CACHE

    _ENCODER_CACHE.clear()
    yield
    _ENCODER_CACHE.clear()


@pytest.fixture()
def db():
    engine = configure_test_database()
    Base.metadata.create_all(engine)
    session = get_session_local()()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)

