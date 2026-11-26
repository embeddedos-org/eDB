"""EoS eDB DocumentStore — JSON document collections with schema-free storage."""
from __future__ import annotations

import json
import sqlite3
import time as _time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .engine import StorageEngine

_SCHEMA = """
CREATE TABLE IF NOT EXISTS _doc_collections (
    name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS _documents (
    doc_id     TEXT NOT NULL,
    collection TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at REAL,
    PRIMARY KEY (doc_id, collection)
);
CREATE INDEX IF NOT EXISTS idx_doc_coll ON _documents(collection);
"""


@dataclass
class Document:
    id: str
    collection: str
    data: dict[str, Any] = field(default_factory=dict)

    # None only for rows written before created_at was stored.
    created_at: float | None = field(default_factory=_time.time)

    def model_dump(self, mode: str = 'python') -> dict:
        return {'id': self.id, 'collection': self.collection, 'data': self.data, 'created_at': self.created_at}


class DocumentStore:
    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine
        for stmt in _SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                self._e.execute(s)
        # Databases created before created_at was stored lack the column.
        cols = {r["name"] for r in self._e.fetchall("PRAGMA table_info(_documents)")}
        if "created_at" not in cols:
            try:
                self._e.execute("ALTER TABLE _documents ADD COLUMN created_at REAL")
            except sqlite3.OperationalError:
                # Another process may add the column between the PRAGMA above and
                # this ALTER, which fails as a duplicate column. Opening the store
                # must not depend on winning that race, so re-read the layout and
                # only re-raise if the column really is still missing.
                cols = {r["name"] for r in self._e.fetchall("PRAGMA table_info(_documents)")}
                if "created_at" not in cols:
                    raise
        self._e.commit()

    @staticmethod
    def _to_doc(row: sqlite3.Row, collection: str) -> Document:
        return Document(id=row["doc_id"], collection=collection,
                        data=json.loads(row["data"]), created_at=row["created_at"])

    def create_collection(self, name: str) -> None:
        self._e.execute(
            "INSERT OR IGNORE INTO _doc_collections (name) VALUES (?)", (name,)
        )
        self._e.commit()

    def list_collections(self) -> list[str]:
        rows = self._e.fetchall("SELECT name FROM _doc_collections")
        return [r["name"] for r in rows]

    def insert(self, collection: str, data: dict[str, Any],
               doc_id: str | None = None) -> Document:
        did = doc_id or str(uuid.uuid4())
        now = _time.time()
        # Auto-create collection
        self._e.execute(
            "INSERT OR IGNORE INTO _doc_collections (name) VALUES (?)", (collection,)
        )
        # An upsert keeps the rowid: INSERT OR REPLACE deleted the row and
        # inserted a new one, moving a re-inserted document to the end of
        # find() and breaking paging (eDB#228). Same stored data as before.
        # Re-inserting is still a fresh write of the whole document, so
        # created_at moves to the new time (eDB#129) -- it has to, because that
        # is the value this method returns below.
        self._e.execute(
            "INSERT INTO _documents (doc_id, collection, data, created_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(doc_id, collection) DO UPDATE SET"
            " data = excluded.data, created_at = excluded.created_at",
            (did, collection, json.dumps(data), now),
        )
        self._e.commit()
        return Document(id=did, collection=collection, data=data, created_at=now)

    def insert_many(self, collection: str, docs: list[dict[str, Any]]) -> list[Document]:
        return [self.insert(collection, d) for d in docs]

    def find_by_id(self, collection: str, doc_id: str) -> Document | None:
        row = self._e.fetchone(
            "SELECT * FROM _documents WHERE collection = ? AND doc_id = ?",
            (collection, doc_id),
        )
        if row is None:
            return None
        return self._to_doc(row, collection)

    def find(self, collection: str, filter_dict: dict[str, Any] | None = None,
             filter_fn: Callable[[dict], bool] | None = None,
             limit: int | None = None, offset: int | None = None) -> list[Document]:
        # Slicing with a negative number counts from the end of the list, which
        # would silently return the wrong documents.
        if (limit is not None and limit < 0) or (offset is not None and offset < 0):
            raise ValueError("limit and offset must not be negative")
        # ORDER BY rowid is insertion order (insert() keeps the rowid on
        # re-insert), so a re-insert no longer moves a document to the end and
        # consecutive pages stay consistent across one.
        #
        # That is the whole of the guarantee: these are offset pages over a live
        # table, not a snapshot. Anything that changes which documents precede
        # the boundary still shifts the pages after it -- a delete, or a write
        # that changes whether an earlier document matches, since filter_dict
        # and filter_fn are applied below before offset is taken. A caller that
        # needs pages to be stable against concurrent writes needs a cursor, not
        # an offset.
        rows = self._e.fetchall(
            "SELECT * FROM _documents WHERE collection = ? ORDER BY rowid",
            (collection,),
        )
        docs = [self._to_doc(r, collection) for r in rows]
        if filter_dict:
            docs = [d for d in docs
                    if all(d.data.get(k) == v for k, v in filter_dict.items())]
        if filter_fn:
            docs = [d for d in docs if filter_fn(d.data)]
        if offset is not None:
            docs = docs[offset:]
        if limit is not None:
            docs = docs[:limit]
        return docs

    def update(self, collection: str, doc_id: str, data: dict[str, Any],
               merge: bool = True) -> Document | None:
        existing = self.find_by_id(collection, doc_id)
        if existing is None:
            return None
        new_data = {**existing.data, **data} if merge else data
        self._e.execute(
            "UPDATE _documents SET data = ? WHERE collection = ? AND doc_id = ?",
            (json.dumps(new_data), collection, doc_id),
        )
        self._e.commit()
        return Document(id=doc_id, collection=collection, data=new_data,
                        created_at=existing.created_at)

    def delete(self, collection: str, doc_id: str) -> bool:
        cur = self._e.execute(
            "DELETE FROM _documents WHERE collection = ? AND doc_id = ?",
            (collection, doc_id),
        )
        self._e.commit()
        return cur.rowcount > 0

    def count(self, collection: str, filter_dict: dict[str, Any] | None = None) -> int:
        if filter_dict:
            return len(self.find(collection, filter_dict=filter_dict))
        row = self._e.fetchone(
            "SELECT COUNT(*) FROM _documents WHERE collection = ?", (collection,)
        )
        return int(row[0]) if row is not None else 0

    def drop_collection(self, name: str) -> None:
        self._e.execute("DELETE FROM _documents WHERE collection = ?", (name,))
        self._e.execute("DELETE FROM _doc_collections WHERE name = ?", (name,))
        self._e.commit()

