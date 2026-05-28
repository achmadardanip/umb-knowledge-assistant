from __future__ import annotations

import pytest

from app.db.database import configure_test_database, get_session_local
from app.db.models import Base


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

