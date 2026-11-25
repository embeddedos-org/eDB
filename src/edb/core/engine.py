"""EoS eDB StorageEngine — SQLite-backed low-level storage layer."""
from __future__ import annotations

import sqlite3
import threading
import uuid
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
        # sqlite3.connect(":memory:") gives every connection its own empty
        # database, so ":memory:" is opened as a named in-memory database
        # (SQLite's memdb VFS) that all of this engine's connections share, with
        # the same per-connection transactions and locking as a file. It exists
        # while at least one connection is open; _keeper holds one until close().
        self._uri = f"file:/edb-{uuid.uuid4().hex}?vfs=memdb" if path == ":memory:" else None
        self._keeper: sqlite3.Connection | None = None
        # Ensure the file exists
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Open a connection on the calling thread
        self._get_conn()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._uri or self._path,
            uri=self._uri is not None,
            check_same_thread=False,
            isolation_level=None,
            factory=_Connection,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with self._conns_lock:
            self._conns.add(conn)
            if self._uri is not None and self._keeper is None:
                self._keeper = conn
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        # threading.local() attributes are untyped (Any); keep the
        # connection in a typed local so this never returns Any.
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None or getattr(self._local, "generation", None) != self._generation:
            # Read the generation first: if close() runs while this connection is
            # being opened, the next call sees the stale generation and reopens.
            generation = self._generation
            conn = self._connect()
            self._local.conn = conn
            self._local.generation = generation
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_seq: list[tuple]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params_seq)

    def commit(self) -> None:
        # Only commit if not inside an explicit transaction (BEGIN)
        if self.conn.in_transaction:
            return
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        """Close every connection the engine has open, in all threads.

        Call it once no other thread is using the engine: a thread in the middle
        of a call gets an error, and its open transaction is rolled back. The
        engine stays usable afterwards; the next call in any thread opens a new
        connection. For ":memory:" that is a new, empty database.
        """
        with self._conns_lock:
            for conn in list(self._conns):
                conn.close()
            self._conns.clear()
            self._keeper = None
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
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        # Cursor.fetchone() is untyped in typeshed (Any); cast so callers
        # get the declared Row | None instead of Any.
        return cast("sqlite3.Row | None", self.conn.execute(sql, params).fetchone())

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def __repr__(self) -> str:
        return f"StorageEngine(path={self._path!r})"

    @property
    def engine(self) -> StorageEngine:
        """Self-reference for compatibility with code that calls .engine on StorageEngine."""
        return self
