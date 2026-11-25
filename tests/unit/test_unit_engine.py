"""Unit tests for edb.core.engine — StorageEngine (#88 coverage drive).

Whole-module slice: engine.py measured 6 missed statements /
89.55% at 41419d70 (unit scope) — rollback(), backup()'s
in-memory guard, table_exists(), __repr__ and the .engine
self-reference property had no unit coverage, and close()'s
no-connection branch was unexercised. These tests use real
SQLite databases (in-memory and tmp_path files), mirroring
test_unit_document.py's approach.

Behaviour pinned as the code implements it:

- rollback() delegates to the connection: rows written inside
  an explicit BEGIN are discarded; a rollback with no open
  transaction is a silent no-op.
- commit() is a no-op while an explicit transaction is open
  (it returns early and the transaction stays open); outside
  one it commits.
- backup() refuses an in-memory engine with ValueError, and
  for a file-backed engine copies the live data to the
  destination file via SQLite's online backup API.
- table_exists() answers from sqlite_master: True only for a
  table that exists.
- close() with no live connection (already closed) is a
  silent no-op; a closed engine lazily reopens on next use.
- repr is exactly StorageEngine(path=<repr of path>) and the
  .engine property returns the engine itself.
"""

import sqlite3
import threading

import pytest

from edb.core.database import Database
from edb.core.engine import StorageEngine


@pytest.fixture
def mem():
    engine = StorageEngine(":memory:")
    yield engine
    engine.close()


@pytest.fixture
def file_engine(tmp_path):
    engine = StorageEngine(str(tmp_path / "main.db"))
    yield engine
    engine.close()


def test_rollback_discards_uncommitted_rows(mem):
    mem.execute("CREATE TABLE t (v INTEGER)")
    mem.execute("BEGIN")
    mem.execute("INSERT INTO t VALUES (1)")
    mem.rollback()
    assert mem.fetchall("SELECT v FROM t") == []


def test_rollback_without_transaction_is_noop(mem):
    mem.execute("CREATE TABLE t (v INTEGER)")
    mem.rollback()  # must not raise
    assert mem.table_exists("t")


def test_commit_inside_explicit_transaction_stays_open(mem):
    mem.execute("CREATE TABLE t (v INTEGER)")
    mem.execute("BEGIN")
    mem.execute("INSERT INTO t VALUES (1)")
    mem.commit()  # early return: still inside the transaction
    assert mem.conn.in_transaction
    mem.rollback()
    assert mem.fetchall("SELECT v FROM t") == []


def test_backup_memory_engine_raises(mem, tmp_path):
    with pytest.raises(ValueError, match="in-memory"):
        mem.backup(str(tmp_path / "out.db"))


def test_backup_file_engine_copies_data(file_engine, tmp_path):
    file_engine.execute("CREATE TABLE t (v INTEGER)")
    file_engine.execute("INSERT INTO t VALUES (42)")
    dest = str(tmp_path / "backup.db")
    file_engine.backup(dest)
    check = sqlite3.connect(dest)
    try:
        rows = check.execute("SELECT v FROM t").fetchall()
    finally:
        check.close()
    assert rows == [(42,)]


def test_table_exists_true_and_false(mem):
    assert mem.table_exists("t") is False
    mem.execute("CREATE TABLE t (v INTEGER)")
    assert mem.table_exists("t") is True


def test_fetchall_returns_all_rows(mem):
    mem.execute("CREATE TABLE t (v INTEGER)")
    mem.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    rows = mem.fetchall("SELECT v FROM t ORDER BY v")
    assert [row[0] for row in rows] == [1, 2]


def test_close_without_connection_is_noop(mem):
    mem.close()
    mem.close()  # _local.conn is None now: silent no-op
    # a closed engine lazily reopens on next use
    assert mem.table_exists("anything") is False


def test_repr_format(mem, file_engine, tmp_path):
    assert repr(mem) == "StorageEngine(path=':memory:')"
    expected = f"StorageEngine(path={str(tmp_path / 'main.db')!r})"
    assert repr(file_engine) == expected


def test_engine_property_is_self_reference(mem):
    assert mem.engine is mem


def _in_thread(fn):
    """Run fn in a new thread and return its result, or the exception it raised."""
    result = []

    def run():
        try:
            result.append(fn())
        except Exception as e:
            result.append(e)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    return result[0]


def test_memory_database_is_shared_between_threads(mem):
    mem.execute("CREATE TABLE t (v INTEGER)")
    mem.execute("INSERT INTO t VALUES (1)")
    rows = _in_thread(lambda: mem.fetchall("SELECT v FROM t"))
    assert [row[0] for row in rows] == [1]


def test_memory_transaction_keeps_other_threads_writes_out():
    db = Database(":memory:")
    try:
        about_to_write = threading.Event()

        def write_other():
            about_to_write.set()
            db.kv.set("other", 1)

        writer = threading.Thread(target=write_other)
        with pytest.raises(RuntimeError), db.transaction():
            db.kv.set("mine", 1)
            writer.start()
            about_to_write.wait()
            writer.join(timeout=0.2)
            # The writer waits for the transaction instead of joining it.
            assert writer.is_alive()
            raise RuntimeError("roll back")
        writer.join()
        assert db.kv.get("mine") is None
        assert db.kv.get("other") == 1
    finally:
        db.close()


def test_memory_database_runs_transactions_from_many_threads():
    db = Database(":memory:")
    errors = []

    def write_batches(n):
        for i in range(20):
            try:
                db.kv.set_many({f"{n}-{i}-{j}": j for j in range(5)})
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=write_batches, args=(n,)) for n in range(8)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(db.kv.list_keys("")) == 8 * 20 * 5
    finally:
        db.close()


def test_close_closes_connections_opened_by_other_threads(file_engine):
    conns = [_in_thread(lambda: file_engine.conn) for _ in range(3)]
    file_engine.close()
    for conn in conns:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_a_thread_opens_a_new_connection_after_close(file_engine):
    file_engine.execute("CREATE TABLE t (v INTEGER)")
    inserted, closed = threading.Event(), threading.Event()
    result = []

    def worker():
        file_engine.execute("INSERT INTO t VALUES (1)")
        inserted.set()
        closed.wait()
        # Same thread, after close(): it must open a new connection, not reuse the closed one.
        try:
            result.append(file_engine.fetchall("SELECT v FROM t"))
        except Exception as e:
            result.append(e)

    thread = threading.Thread(target=worker)
    thread.start()
    inserted.wait()
    file_engine.close()
    closed.set()
    thread.join()
    assert not isinstance(result[0], Exception), result[0]
    assert [row[0] for row in result[0]] == [1]
