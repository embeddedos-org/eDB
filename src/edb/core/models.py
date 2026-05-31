"""EoS eDB Core Models — shared data structures for all storage engines."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ColumnType(str, Enum):
    INTEGER = "INTEGER"
    REAL = "REAL"
    TEXT = "TEXT"
    BLOB = "BLOB"
    BOOLEAN = "BOOLEAN"
    JSON = "JSON"


@dataclass
class ColumnDefinition:
    name: str
    col_type: ColumnType
    primary_key: bool = False
    nullable: bool = True
    unique: bool = False
    default: Any = None


@dataclass
class TableSchema:
    name: str
    columns: list[ColumnDefinition] = field(default_factory=list)


@dataclass
class QueryResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    affected: int = 0
    columns: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)
