"""EoS eDB StorageEngine — SQLite-backed low-level storage layer."""
from __future__ import annotations
import sqlite3
import threading
from pathlib import Path
from typing import Any


class StorageEngine:
    """Thread-safe SQLite storage engine used by all eDB subsystems."""

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._local = threading.local()
        # Ensure the file exists
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Open a connection on the calling thread
        self._get_conn()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
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
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


    def table_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def __repr__(self) -> str:
        return f"StorageEngine(path={self._path!r})"

    @property
    def engine(self) -> 'StorageEngine':
        """Self-reference for compatibility with code that calls .engine on StorageEngine."""
        return self
