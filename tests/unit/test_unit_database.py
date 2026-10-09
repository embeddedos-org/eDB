"""Unit tests for the Database facade (src/edb/core/database.py).

Covers the previously untested surface: the context-manager protocol,
the engine property, close(), the savepoint transaction (commit and
rollback paths), and __repr__. Part of the eDB#88 coverage drive.
"""

import pytest

from edb.core.database import Database


@pytest.fixture
def mem_db():
    db = Database(":memory:")
    yield db
    db.close()


def test_context_manager_returns_self_and_closes():
    with Database(":memory:") as db:
        assert isinstance(db, Database)
        assert db.kv is not None
    # __exit__ closed the engine: the facade is unusable afterwards
    with pytest.raises(Exception):
        db.kv.set("k", "v")


def test_engine_property_exposes_storage_engine():
    with Database(":memory:") as db:
        assert db.engine is db._engine


def test_repr_mentions_path():
    with Database(":memory:") as db:
        assert "Database(path=':memory:')" == repr(db)


def test_close_is_idempotent_enough_to_call_twice(mem_db):
    mem_db.close()
    mem_db.close()  # must not raise


def test_transaction_commits(mem_db):
    with mem_db.transaction():
        mem_db.kv.set("committed", "yes")
    assert mem_db.kv.get("committed") == "yes"


def test_transaction_rolls_back_on_exception(mem_db):
    with pytest.raises(RuntimeError, match="boom"):
        with mem_db.transaction():
            mem_db.kv.set("rolled-back", "no")
            raise RuntimeError("boom")
    assert mem_db.kv.get("rolled-back") is None


def test_transaction_exception_propagates(mem_db):
    with pytest.raises(ValueError):
        with mem_db.transaction():
            raise ValueError("propagates")


def test_subsystems_share_the_engine(mem_db):
    assert mem_db.kv._e is mem_db.engine
    assert mem_db.sql._e is mem_db.engine
    assert mem_db.docs._e is mem_db.engine
    assert mem_db.graph._e is mem_db.engine
    assert mem_db.fts._e is mem_db.engine
