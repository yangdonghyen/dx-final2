from unittest.mock import Mock

import pytest

from app.core.config import DatabaseNotConfiguredError, Settings
from app.db import session
from app.db.base import Base


def test_model_import_does_not_initialize_database():
    import app.models

    assert len(Base.metadata.tables) == 28  # + user_notifications (013)
    assert session.get_engine.cache_info().currsize == 0
    with pytest.raises(DatabaseNotConfiguredError):
        session.get_engine()


def test_engine_and_session_are_lazy(monkeypatch):
    settings = Settings(mysql_host="mysql.invalid", mysql_user="unit_test",
                        mysql_database="unit_test", mysql_password="unit-test-only")
    monkeypatch.setattr(session, "get_settings", lambda: settings)
    engine = session.get_engine()
    try:
        assert engine.url.drivername == "mysql+pymysql"
        assert session.get_engine() is engine
        with session.SessionLocal() as db:
            assert db.get_bind() is engine
            assert not db.in_transaction()
    finally:
        engine.dispose()


@pytest.mark.parametrize("fails", [False, True])
def test_session_closes_and_rolls_back_only_on_failure(monkeypatch, fails):
    db = Mock()
    monkeypatch.setattr(session, "SessionLocal", lambda: db)
    dependency = session.get_db()
    assert next(dependency) is db
    if fails:
        with pytest.raises(RuntimeError, match="unit test failure"):
            dependency.throw(RuntimeError("unit test failure"))
        db.rollback.assert_called_once()
    else:
        with pytest.raises(StopIteration):
            next(dependency)
        db.rollback.assert_not_called()
    db.close.assert_called_once()
    db.commit.assert_not_called()

