"""EoS eDB StorageEngine — SQLite-backed low-level storage layer."""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import weakref
from pathlib import Path
from typing import Any, cast


class _Connection(sqlite3.Connection):
    """A plain sqlite3 connection that, unlike the base class, can be weakly referenced."""


class StorageEngine:
    """Thread-safe SQLite storage engine used by all eDB subsystems."""

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._local = threading.local()
        # Every open connection, so close() can close the ones other threads opened.
        # Weak references, so a connection is still freed when its thread exits.
        self._conns: weakref.WeakSet[_Connection] = weakref.WeakSet()
        self._conns_lock = threading.Lock()
        # close() bumps this; a thread whose connection is older opens a new one.
        self._generation = 0
        # Each sqlite3.connect(":memory:") is a new, empty database, so for
        # ":memory:" every thread shares one connection. _memory_lock serialises
        # its use, and Database.transaction() holds it for the whole transaction
        # so other threads' writes cannot join it.
        self._shared: sqlite3.Connection | None = None
        self._memory_lock = threading.RLock()
        # Ensure the file exists
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Open a connection on the calling thread
        self._get_conn()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None, factory=_Connection
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with self._conns_lock:
            self._conns.add(conn)
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._path == ":memory:":
            with self._memory_lock:
                if self._shared is None:
                    self._shared = self._connect()
                return self._shared
        # threading.local() attributes are untyped (Any); keep the
        # connection in a typed local so this never returns Any.
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None or getattr(self._local, "generation", None) != self._generation:
            conn = self._connect()
            self._local.conn = conn
            self._local.generation = self._generation
        return conn

    def locked(self) -> contextlib.AbstractContextManager[Any]:
        """Hold the engine's lock for a block of calls (only ":memory:" has one)."""
        if self._path == ":memory:":
            return self._memory_lock
        return contextlib.nullcontext()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Cursor:
        with self.locked():
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_seq: list[tuple]) -> sqlite3.Cursor:
        with self.locked():
            return self.conn.executemany(sql, params_seq)

    def commit(self) -> None:
        with self.locked():
            # Only commit if not inside an explicit transaction (BEGIN)
            if self.conn.in_transaction:
                return
            self.conn.commit()

    def rollback(self) -> None:
        with self.locked():
            self.conn.rollback()

    def close(self) -> None:
        """Close every connection the engine has open, in all threads.

        The engine stays usable: the next call in any thread opens a new
        connection. For ":memory:" that is a new, empty database.
        """
        with self._memory_lock, self._conns_lock:
            for conn in list(self._conns):
                conn.close()
            self._conns.clear()
            self._shared = None
            self._generation += 1

    def backup(self, dest: str) -> None:
        """Back up the database file to *dest* via SQLite's online backup API.

        The CLI `edb backup` command calls this; it previously raised
        AttributeError because the method did not exist.
        """
        if self._path == ":memory:":
            raise ValueError("cannot back up an in-memory database to a file")
        dest_conn = sqlite3.connect(dest)
        try:
            self.conn.backup(dest_conn)
        finally:
            dest_conn.close()


    def table_exists(self, name: str) -> bool:
        return (
            self.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
            is not None
        )

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        # Cursor.fetchone() is untyped in typeshed (Any); cast so callers
        # get the declared Row | None instead of Any.
        with self.locked():
            return cast("sqlite3.Row | None", self.conn.execute(sql, params).fetchone())

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.locked():
            return self.conn.execute(sql, params).fetchall()

    def __repr__(self) -> str:
        return f"StorageEngine(path={self._path!r})"

    @property
    def engine(self) -> StorageEngine:
        """Self-reference for compatibility with code that calls .engine on StorageEngine."""
        return self
