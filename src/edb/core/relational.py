"""EoS eDB RelationalStore — SQL table management on top of StorageEngine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .engine import StorageEngine
from .models import ColumnType, TableSchema

_TYPE_MAP = {
    ColumnType.INTEGER: "INTEGER",
    ColumnType.REAL: "REAL",
    ColumnType.TEXT: "TEXT",
    ColumnType.BLOB: "BLOB",
    ColumnType.BOOLEAN: "INTEGER",
    ColumnType.JSON: "TEXT",
}

# Table and column names cannot be bound with "?" like values can, so they are
# pasted into the SQL text. Only plain identifiers may get that far
# (SECURITY-STANDARDS.md: identifiers need an allowlist).
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _ident(name: str) -> str:
    """Return ``name`` unchanged if it is a plain SQL identifier, else raise."""
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def _order_by(clause: str) -> str:
    """Allow ``column`` or ``column ASC|DESC``; reject anything else."""
    parts = clause.split()
    if len(parts) == 1:
        return _ident(parts[0])
    if len(parts) == 2 and parts[1].upper() in ("ASC", "DESC"):
        return f"{_ident(parts[0])} {parts[1].upper()}"
    raise ValueError(f"Invalid SQL ORDER BY clause: {clause!r}")


@dataclass
class QueryResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    affected_rows: int = 0
    columns: list[str] = field(default_factory=list)
    #: Primary key assigned by the last INSERT, as reported by the driver.
    last_insert_id: int = 0

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def last_row_id(self) -> int:
        """Primary key of the row the last INSERT created.

        This previously returned ``affected_rows``, which is a count, not an
        id -- so a table whose rows were assigned ids 1, 2, 3 reported a
        last_row_id of 1 every time, and ``POST /sql/insert`` returned that
        to callers.
        """
        return self.last_insert_id

    def __len__(self) -> int:
        return len(self.rows)


class RelationalStore:
    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine

    def create_table(self, schema: TableSchema) -> None:
        cols = []
        for c in schema.columns:
            col = f"{_ident(c.name)} {_TYPE_MAP[c.col_type]}"
            if c.primary_key:
                col += " PRIMARY KEY"
            if not c.nullable and not c.primary_key:
                col += " NOT NULL"
            if c.unique and not c.primary_key:
                col += " UNIQUE"
            cols.append(col)
        ddl = f"CREATE TABLE IF NOT EXISTS {_ident(schema.name)} ({', '.join(cols)})"
        self._e.execute(ddl)
        self._e.commit()

    def drop_table(self, name: str) -> None:
        name = _ident(name)
        self._e.execute(f"DROP TABLE IF EXISTS {name}")
        self._e.commit()

    def list_tables(self) -> list[str]:
        rows = self._e.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
        )
        return [r["name"] for r in rows]

    def insert(self, table: str, data: dict[str, Any]) -> QueryResult:
        table = _ident(table)
        cols = ", ".join(_ident(k) for k in data)
        placeholders = ", ".join(["?"] * len(data))
        cur = self._e.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            tuple(data.values()),
        )
        self._e.commit()
        return QueryResult(
            rows=[],
            affected_rows=cur.rowcount or 1,
            last_insert_id=cur.lastrowid or 0,
        )

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> QueryResult:
        if not rows:
            return QueryResult()
        table = _ident(table)
        cols = ", ".join(_ident(k) for k in rows[0])
        placeholders = ", ".join(["?"] * len(rows[0]))
        cur = self._e.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            [tuple(r.values()) for r in rows],
        )
        self._e.commit()
        return QueryResult(
            rows=[],
            affected_rows=len(rows),
            last_insert_id=(getattr(cur, "lastrowid", 0) or 0),
        )

    def select(
        self,
        table: str,
        columns: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order_by: str | None = None,
    ) -> QueryResult:
        table = _ident(table)
        col_str = ", ".join(_ident(c) for c in columns) if columns else "*"
        sql = f"SELECT {col_str} FROM {table}"
        params: list[Any] = []
        if where:
            clauses = [f"{_ident(k)} = ?" for k in where]
            sql += " WHERE " + " AND ".join(clauses)
            params.extend(where.values())
        if order_by:
            sql += f" ORDER BY {_order_by(order_by)}"
        if limit is not None:
            sql += f" LIMIT {limit}"
        elif offset is not None:
            # SQLite requires a LIMIT before OFFSET; -1 means no limit.
            sql += " LIMIT -1"
        if offset is not None:
            sql += f" OFFSET {offset}"
        rows = self._e.fetchall(sql, tuple(params))
        result_rows = [dict(r) for r in rows]
        cols_out = list(result_rows[0].keys()) if result_rows else []
        return QueryResult(rows=result_rows, affected_rows=len(result_rows), columns=cols_out)

    def update(self, table: str, data: dict[str, Any], where: dict[str, Any]) -> QueryResult:
        table = _ident(table)
        set_clause = ", ".join([f"{_ident(k)} = ?" for k in data])
        where_clause = " AND ".join([f"{_ident(k)} = ?" for k in where])
        params = tuple(data.values()) + tuple(where.values())
        cur = self._e.execute(f"UPDATE {table} SET {set_clause} WHERE {where_clause}", params)
        self._e.commit()
        return QueryResult(rows=[], affected_rows=cur.rowcount)

    def delete(self, table: str, where: dict[str, Any]) -> QueryResult:
        table = _ident(table)
        where_clause = " AND ".join([f"{_ident(k)} = ?" for k in where])
        cur = self._e.execute(f"DELETE FROM {table} WHERE {where_clause}", tuple(where.values()))
        self._e.commit()
        return QueryResult(rows=[], affected_rows=cur.rowcount)

    def execute_raw(self, sql: str, params: tuple = ()) -> QueryResult:
        cur = self._e.execute(sql, params)
        self._e.commit()
        rows = cur.fetchall()
        result_rows = [dict(r) for r in rows] if rows else []
        cols = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(rows=result_rows, affected_rows=cur.rowcount, columns=cols)
