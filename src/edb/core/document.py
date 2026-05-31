"""EoS eDB DocumentStore — JSON document collections with schema-free storage."""
from __future__ import annotations
import json
import uuid
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable
from .engine import StorageEngine

_SCHEMA = """
CREATE TABLE IF NOT EXISTS _doc_collections (
    name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS _documents (
    doc_id     TEXT NOT NULL,
    collection TEXT NOT NULL,
    data       TEXT NOT NULL,
    PRIMARY KEY (doc_id, collection)
);
CREATE INDEX IF NOT EXISTS idx_doc_coll ON _documents(collection);
"""


@dataclass
class Document:
    id: str
    collection: str
    data: dict[str, Any] = field(default_factory=dict)

    created_at: float = field(default_factory=_time.time)

    def model_dump(self, mode: str = 'python') -> dict:
        return {'id': self.id, 'collection': self.collection, 'data': self.data, 'created_at': self.created_at}


class DocumentStore:
    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine
        for stmt in _SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                self._e.execute(s)
        self._e.commit()

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
        # Auto-create collection
        self._e.execute(
            "INSERT OR IGNORE INTO _doc_collections (name) VALUES (?)", (collection,)
        )
        self._e.execute(
            "INSERT OR REPLACE INTO _documents (doc_id, collection, data) VALUES (?, ?, ?)",
            (did, collection, json.dumps(data)),
        )
        self._e.commit()
        return Document(id=did, collection=collection, data=data)

    def insert_many(self, collection: str, docs: list[dict[str, Any]]) -> list[Document]:
        return [self.insert(collection, d) for d in docs]

    def find_by_id(self, collection: str, doc_id: str) -> Document | None:
        row = self._e.fetchone(
            "SELECT * FROM _documents WHERE collection = ? AND doc_id = ?",
            (collection, doc_id),
        )
        if row is None:
            return None
        return Document(id=row["doc_id"], collection=collection,
                        data=json.loads(row["data"]))

    def find(self, collection: str, filter_dict: dict[str, Any] | None = None,
             filter_fn: Callable[[dict], bool] | None = None,
             limit: int | None = None, offset: int | None = None) -> list[Document]:
        rows = self._e.fetchall(
            "SELECT * FROM _documents WHERE collection = ?", (collection,)
        )
        docs = [Document(id=r["doc_id"], collection=collection,
                         data=json.loads(r["data"])) for r in rows]
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
        if merge:
            new_data = {**existing.data, **data}
        else:
            new_data = data
        self._e.execute(
            "UPDATE _documents SET data = ? WHERE collection = ? AND doc_id = ?",
            (json.dumps(new_data), collection, doc_id),
        )
        self._e.commit()
        return Document(id=doc_id, collection=collection, data=new_data)

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
        return row[0]

    def drop_collection(self, name: str) -> None:
        self._e.execute("DELETE FROM _documents WHERE collection = ?", (name,))
        self._e.execute("DELETE FROM _doc_collections WHERE name = ?", (name,))
        self._e.commit()
