"""EoS eDB Database — unified facade over all storage subsystems."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from types import TracebackType

from .document import DocumentStore
from .engine import StorageEngine
from .fts import FullTextSearch
from .graph import GraphStore
from .keyvalue import KeyValueStore
from .relational import RelationalStore


class Database:
    """
    Unified multi-model database.

    Subsystems:
        db.kv   → KeyValueStore
        db.fts  → FullTextSearch
        db.graph → GraphStore
        db.sql  → RelationalStore
        db.docs → DocumentStore
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._engine = StorageEngine(path)
        self.kv = KeyValueStore(self._engine)
        self.fts = FullTextSearch(self._engine)
        self.graph = GraphStore(self._engine)
        self.sql = RelationalStore(self._engine)
        self.docs = DocumentStore(self._engine)

    # ── Context manager ──────────────────────────────────────────────────────
    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def engine(self) -> StorageEngine:
        """Expose the underlying StorageEngine for auth/api layer compatibility."""
        return self._engine

    def close(self) -> None:
        self._engine.close()

    # ── Transaction ──────────────────────────────────────────────────────────
    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        import uuid as _uuid
        conn = self._engine.conn
        sp = 'sp_' + _uuid.uuid4().hex[:8]
        conn.execute(f'SAVEPOINT {sp}')
        try:
            yield
            conn.execute(f'RELEASE SAVEPOINT {sp}')
        except Exception:
            conn.execute(f'ROLLBACK TO SAVEPOINT {sp}')
            conn.execute(f'RELEASE SAVEPOINT {sp}')
            raise

    # ── Repr ─────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"Database(path={self._path!r})"

