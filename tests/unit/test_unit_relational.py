# SPDX-License-Identifier: MIT
"""Unit tests for the relational store (issue #88 coverage drive).

Covers edb/core/relational.py — measured at 78.57% by the unit
suite before this file, the largest unit-owned uncovered module:
QueryResult semantics (including last_row_id reporting the
insert id, not the affected count), the create_table DDL matrix
(every column type, PRIMARY KEY / NOT NULL / UNIQUE placement),
insert / insert_many, select (columns, where, order, limit,
offset), update, delete, and execute_raw.
"""

import sqlite3

import pytest

from edb.core.engine import StorageEngine
from edb.core.models import ColumnDefinition, ColumnType, TableSchema
from edb.core.relational import QueryResult, RelationalStore


@pytest.fixture
def store():
    return RelationalStore(StorageEngine(":memory:"))


@pytest.fixture
def users(store):
    store.create_table(
        TableSchema(
            name="users",
            columns=[
                ColumnDefinition("id", ColumnType.INTEGER, primary_key=True),
                ColumnDefinition("name", ColumnType.TEXT, nullable=False),
                ColumnDefinition("email", ColumnType.TEXT, unique=True),
                ColumnDefinition("age", ColumnType.INTEGER),
            ],
        )
    )
    return store


def seed_users(store, n=3):
    rows = [{"name": f"user{i}", "email": f"user{i}@example.com", "age": 20 + i} for i in range(n)]
    return store.insert_many("users", rows)


class TestQueryResult:
    def test_defaults(self):
        result = QueryResult()
        assert result.rows == []
        assert result.affected_rows == 0
        assert result.columns == []
        assert result.last_insert_id == 0
        assert result.row_count == 0
        assert len(result) == 0

    def test_row_count_and_len_follow_rows(self):
        result = QueryResult(rows=[{"a": 1}, {"a": 2}])
        assert result.row_count == 2
        assert len(result) == 2

    def test_last_row_id_is_insert_id_not_affected_count(self):
        # Regression pin: last_row_id previously returned
        # affected_rows, so ids 1, 2, 3 reported a last id of 1.
        result = QueryResult(affected_rows=1, last_insert_id=3)
        assert result.last_row_id == 3


class TestCreateTable:
    def test_all_column_types(self, store):
        store.create_table(
            TableSchema(
                name="all_types",
                columns=[
                    ColumnDefinition("i", ColumnType.INTEGER),
                    ColumnDefinition("r", ColumnType.REAL),
                    ColumnDefinition("t", ColumnType.TEXT),
                    ColumnDefinition("b", ColumnType.BLOB),
                    ColumnDefinition("flag", ColumnType.BOOLEAN),
                    ColumnDefinition("j", ColumnType.JSON),
                ],
            )
        )
        assert "all_types" in store.list_tables()
        result = store.insert(
            "all_types",
            {"i": 1, "r": 1.5, "t": "x", "b": b"\x01", "flag": True, "j": "{}"},
        )
        assert result.affected_rows == 1

    def test_create_is_idempotent(self, users):
        users.create_table(
            TableSchema(
                name="users",
                columns=[ColumnDefinition("id", ColumnType.INTEGER, primary_key=True)],
            )
        )
        assert "users" in users.list_tables()

    def test_primary_key_suppresses_not_null_and_unique(self, store):
        # A primary-key column must not also gain NOT NULL / UNIQUE
        # suffixes from the flags; insertion without the key still
        # auto-assigns it.
        store.create_table(
            TableSchema(
                name="pk_flags",
                columns=[
                    ColumnDefinition(
                        "id",
                        ColumnType.INTEGER,
                        primary_key=True,
                        nullable=False,
                        unique=True,
                    ),
                    ColumnDefinition("v", ColumnType.TEXT),
                ],
            )
        )
        result = store.insert("pk_flags", {"v": "a"})
        assert result.last_insert_id == 1

    def test_not_null_enforced(self, users):
        with pytest.raises(sqlite3.IntegrityError):
            users.insert("users", {"email": "noname@example.com"})

    def test_unique_enforced(self, users):
        users.insert("users", {"name": "one", "email": "dup@example.com"})
        with pytest.raises(sqlite3.IntegrityError):
            users.insert("users", {"name": "two", "email": "dup@example.com"})


class TestDropAndListTables:
    def test_list_tables_empty(self, store):
        assert store.list_tables() == []

    def test_drop_table(self, users):
        assert "users" in users.list_tables()
        users.drop_table("users")
        assert "users" not in users.list_tables()

    def test_drop_missing_table_is_a_no_op(self, store):
        store.drop_table("never_existed")


class TestInsert:
    def test_insert_reports_id_and_count(self, users):
        first = users.insert("users", {"name": "a", "email": "a@example.com"})
        second = users.insert("users", {"name": "b", "email": "b@example.com"})
        assert first.affected_rows == 1
        assert first.rows == []
        assert first.last_insert_id == 1
        assert second.last_insert_id == 2
        assert second.last_row_id == 2

    def test_insert_many(self, users):
        result = seed_users(users, 3)
        assert result.affected_rows == 3
        # Quirk, pinned as-is: sqlite3's executemany does not surface
        # a lastrowid, so insert_many reports last_insert_id 0 where
        # insert reports the real id. Pinning current behaviour; any
        # change to that is its own issue, not a coverage edit.
        assert result.last_insert_id == 0
        assert users.select("users").row_count == 3

    def test_insert_many_empty_rows(self, users):
        result = users.insert_many("users", [])
        assert result.affected_rows == 0
        assert result.last_insert_id == 0
        assert result.rows == []


class TestSelect:
    def test_select_all(self, users):
        seed_users(users, 3)
        result = users.select("users")
        assert result.row_count == 3
        assert result.affected_rows == 3
        assert result.columns == ["id", "name", "email", "age"]
        assert result.rows[0]["name"] == "user0"

    def test_select_explicit_columns(self, users):
        seed_users(users, 2)
        result = users.select("users", columns=["name"])
        assert result.columns == ["name"]
        assert result.rows == [{"name": "user0"}, {"name": "user1"}]

    def test_select_where_single_key(self, users):
        seed_users(users, 3)
        result = users.select("users", where={"name": "user1"})
        assert result.row_count == 1
        assert result.rows[0]["email"] == "user1@example.com"

    def test_select_where_multiple_keys_are_anded(self, users):
        seed_users(users, 3)
        hit = users.select("users", where={"name": "user1", "age": 21})
        miss = users.select("users", where={"name": "user1", "age": 99})
        assert hit.row_count == 1
        assert miss.row_count == 0
        assert miss.columns == []

    def test_select_order_by(self, users):
        seed_users(users, 3)
        result = users.select("users", order_by="age DESC")
        assert [r["age"] for r in result.rows] == [22, 21, 20]

    def test_select_limit(self, users):
        seed_users(users, 3)
        assert users.select("users", limit=2).row_count == 2

    def test_select_offset_without_limit(self, users):
        # Regression test for #102: a bare OFFSET (no LIMIT) used
        # to build invalid SQL and raise OperationalError.
        seed_users(users, 3)
        result = users.select("users", order_by="id", offset=2)
        assert result.row_count == 1
        assert result.rows[0]["name"] == "user2"

    def test_select_limit_and_offset(self, users):
        seed_users(users, 3)
        result = users.select("users", order_by="id", limit=1, offset=1)
        assert result.row_count == 1
        assert result.rows[0]["name"] == "user1"


class TestUpdateDelete:
    def test_update_matching_row(self, users):
        seed_users(users, 2)
        result = users.update("users", {"age": 50}, {"name": "user0"})
        assert result.affected_rows == 1
        assert users.select("users", where={"name": "user0"}).rows[0]["age"] == 50

    def test_update_no_match(self, users):
        seed_users(users, 1)
        result = users.update("users", {"age": 50}, {"name": "ghost"})
        assert result.affected_rows == 0

    def test_delete_matching_row(self, users):
        seed_users(users, 2)
        result = users.delete("users", {"name": "user0"})
        assert result.affected_rows == 1
        assert users.select("users").row_count == 1

    def test_delete_no_match(self, users):
        seed_users(users, 1)
        result = users.delete("users", {"name": "ghost"})
        assert result.affected_rows == 0


class TestExecuteRaw:
    def test_select_with_params(self, users):
        seed_users(users, 3)
        result = users.execute_raw("SELECT name FROM users WHERE age > ?", (20,))
        assert result.row_count == 2
        assert result.columns == ["name"]
        assert {r["name"] for r in result.rows} == {"user1", "user2"}

    def test_insert_via_raw_sql(self, users):
        result = users.execute_raw(
            "INSERT INTO users (name, email) VALUES (?, ?)", ("raw", "raw@example.com")
        )
        assert result.rows == []
        assert result.columns == []
        assert users.select("users").row_count == 1

    def test_select_no_params_default(self, users):
        seed_users(users, 1)
        result = users.execute_raw("SELECT COUNT(*) AS n FROM users")
        assert result.rows == [{"n": 1}]
        assert result.columns == ["n"]


BAD_NAME = "id OR 1=1"


class TestIdentifierAllowlist:
    """Table/column names and order_by are pasted into the SQL text, so the
    store must reject anything outside the identifier allowlist
    (SECURITY-STANDARDS.md, Injection) before it reaches SQLite."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.create_table(
                TableSchema(name=BAD_NAME, columns=[ColumnDefinition("id", ColumnType.INTEGER)])
            ),
            lambda s: s.create_table(
                TableSchema(name="t", columns=[ColumnDefinition(BAD_NAME, ColumnType.INTEGER)])
            ),
            lambda s: s.drop_table(BAD_NAME),
            lambda s: s.insert(BAD_NAME, {"name": "x"}),
            lambda s: s.insert("users", {BAD_NAME: "x"}),
            lambda s: s.insert_many("users", [{BAD_NAME: "x"}]),
            lambda s: s.select(BAD_NAME),
            lambda s: s.select("users", columns=[BAD_NAME]),
            lambda s: s.select("users", where={BAD_NAME: 1}),
            lambda s: s.select("users", order_by="age DESC, (SELECT 1)"),
            lambda s: s.update("users", {BAD_NAME: 1}, {"id": 1}),
            lambda s: s.update("users", {"age": 1}, {BAD_NAME: 1}),
        ],
        ids=[
            "create_table_name",
            "create_table_column",
            "drop_table",
            "insert_table",
            "insert_column",
            "insert_many_column",
            "select_table",
            "select_column",
            "select_where_key",
            "select_order_by",
            "update_set_key",
            "update_where_key",
        ],
    )
    def test_bad_identifier_rejected(self, users, call):
        with pytest.raises(ValueError, match="Invalid SQL"):
            call(users)

    def test_where_key_cannot_widen_delete(self, users):
        seed_users(users, 3)
        with pytest.raises(ValueError, match="Invalid SQL"):
            users.delete("users", {BAD_NAME: 0})
        assert users.select("users").row_count == 3
