"""EoS eDB FullTextSearch — SQLite FTS5-backed full-text search engine."""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
from .engine import StorageEngine

_META = """
CREATE TABLE IF NOT EXISTS _fts_meta (
    index_name TEXT PRIMARY KEY,
    fields     TEXT NOT NULL
)
"""


@dataclass
class SearchResult:
    doc_id: str
    score: float
    fields: dict[str, Any]


class FullTextSearch:
    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine
        self._e.execute(_META)
        self._e.commit()

    def _table(self, name: str) -> str:
        return f"_fts_{name}"

    def create_index(self, name: str, fields: list[str]) -> None:
        tbl = self._table(name)
        cols = ", ".join(fields)
        self._e.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {tbl} "
            f"USING fts5(doc_id UNINDEXED, {cols})"
        )
        self._e.execute(
            "INSERT OR REPLACE INTO _fts_meta (index_name, fields) VALUES (?, ?)",
            (name, json.dumps(fields)),
        )
        self._e.commit()

    def list_indexes(self) -> list[str]:
        rows = self._e.execute("SELECT index_name FROM _fts_meta").fetchall()
        return [r["index_name"] for r in rows]

    def index_document(self, index: str, doc_id: str, data: dict[str, Any]) -> None:
        meta = self._e.execute(
            "SELECT fields FROM _fts_meta WHERE index_name = ?", (index,)
        ).fetchone()
        if meta is None:
            raise ValueError(f"Index '{index}' does not exist")
        fields = json.loads(meta["fields"])
        tbl = self._table(index)
        # Delete existing entry for this doc_id
        self._e.execute(f"DELETE FROM {tbl} WHERE doc_id = ?", (doc_id,))
        vals = [doc_id] + [str(data.get(f, "")) for f in fields]
        placeholders = ", ".join(["?"] * len(vals))
        self._e.execute(f"INSERT INTO {tbl} VALUES ({placeholders})", vals)
        self._e.commit()

    def search(self, index: str, query: str, limit: int = 20) -> list[SearchResult]:
        meta = self._e.execute(
            "SELECT fields FROM _fts_meta WHERE index_name = ?", (index,)
        ).fetchone()
        if meta is None:
            return []
        fields = json.loads(meta["fields"])
        tbl = self._table(index)
        try:
            rows = self._e.execute(
                f"SELECT doc_id, {', '.join(fields)}, rank FROM {tbl} "
                f"WHERE {tbl} MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except Exception:
            return []
        results = []
        for row in rows:
            fd = {f: row[f] for f in fields}
            results.append(SearchResult(doc_id=row["doc_id"], score=-row["rank"], fields=fd))
        return results

    def delete_document(self, index: str, doc_id: str) -> bool:
        tbl = self._table(index)
        cur = self._e.execute(f"DELETE FROM {tbl} WHERE doc_id = ?", (doc_id,))
        self._e.commit()
        return cur.rowcount > 0

    def drop_index(self, name: str) -> None:
        tbl = self._table(name)
        self._e.execute(f"DROP TABLE IF EXISTS {tbl}")
        self._e.execute("DELETE FROM _fts_meta WHERE index_name = ?", (name,))
        self._e.commit()
