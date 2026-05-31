"""EoS eDB RelationalStore — SQL table management on top of StorageEngine."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from .engine import StorageEngine
from .models import ColumnDefinition, ColumnType, TableSchema

_TYPE_MAP = {
    ColumnType.INTEGER: "INTEGER",
    ColumnType.REAL: "REAL",
    ColumnType.TEXT: "TEXT",
    ColumnType.BLOB: "BLOB",
    ColumnType.BOOLEAN: "INTEGER",
    ColumnType.JSON: "TEXT",
}


@dataclass
class QueryResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    affected_rows: int = 0
    columns: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def last_row_id(self) -> int:
        return self.affected_rows

    def __len__(self) -> int:
        return len(self.rows)


class RelationalStore:
    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine

    def create_table(self, schema: TableSchema) -> None:
        cols = []
        for c in schema.columns:
            col = f"{c.name} {_TYPE_MAP[c.col_type]}"
            if c.primary_key:
                col += " PRIMARY KEY"
            if not c.nullable and not c.primary_key:
                col += " NOT NULL"
            if c.unique and not c.primary_key:
                col += " UNIQUE"
            cols.append(col)
        ddl = f"CREATE TABLE IF NOT EXISTS {schema.name} ({', '.join(cols)})"
        self._e.execute(ddl)
        self._e.commit()

    def drop_table(self, name: str) -> None:
        self._e.execute(f"DROP TABLE IF EXISTS {name}")
        self._e.commit()

    def list_tables(self) -> list[str]:
        rows = self._e.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
        )
        return [r["name"] for r in rows]

    def insert(self, table: str, data: dict[str, Any]) -> QueryResult:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        cur = self._e.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            tuple(data.values()),
        )
        self._e.commit()
        return QueryResult(rows=[], affected_rows=cur.rowcount or 1)

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> QueryResult:
        if not rows:
            return QueryResult()
        cols = ", ".join(rows[0].keys())
        placeholders = ", ".join(["?"] * len(rows[0]))
        self._e.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            [tuple(r.values()) for r in rows],
        )
        self._e.commit()
        return QueryResult(rows=[], affected_rows=len(rows))

    def select(self, table: str, columns: list[str] | None = None,
               where: dict[str, Any] | None = None, limit: int | None = None,
               offset: int | None = None, order_by: str | None = None) -> QueryResult:
        col_str = ", ".join(columns) if columns else "*"
        sql = f"SELECT {col_str} FROM {table}"
        params: list[Any] = []
        if where:
            clauses = [f"{k} = ?" for k in where]
            sql += " WHERE " + " AND ".join(clauses)
            params.extend(where.values())
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {limit}"
        if offset is not None:
            sql += f" OFFSET {offset}"
        rows = self._e.fetchall(sql, tuple(params))
        result_rows = [dict(r) for r in rows]
        cols_out = list(result_rows[0].keys()) if result_rows else []
        return QueryResult(rows=result_rows, affected_rows=len(result_rows), columns=cols_out)

    def update(self, table: str, data: dict[str, Any], where: dict[str, Any]) -> QueryResult:
        set_clause = ", ".join([f"{k} = ?" for k in data])
        where_clause = " AND ".join([f"{k} = ?" for k in where])
        params = tuple(data.values()) + tuple(where.values())
        cur = self._e.execute(
            f"UPDATE {table} SET {set_clause} WHERE {where_clause}", params
        )
        self._e.commit()
        return QueryResult(rows=[], affected_rows=cur.rowcount)

    def delete(self, table: str, where: dict[str, Any]) -> QueryResult:
        where_clause = " AND ".join([f"{k} = ?" for k in where])
        cur = self._e.execute(
            f"DELETE FROM {table} WHERE {where_clause}", tuple(where.values())
        )
        self._e.commit()
        return QueryResult(rows=[], affected_rows=cur.rowcount)

    def execute_raw(self, sql: str, params: tuple = ()) -> QueryResult:
        cur = self._e.execute(sql, params)
        self._e.commit()
        rows = cur.fetchall()
        result_rows = [dict(r) for r in rows] if rows else []
        return QueryResult(rows=result_rows, affected_rows=cur.rowcount)
