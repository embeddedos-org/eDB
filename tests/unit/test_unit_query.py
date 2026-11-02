"""
tests/unit/test_unit_query.py — eDB query parser and planner unit tests
SPDX-License-Identifier: MIT  Copyright (c) 2026 EmbeddedOS Foundation

Exercises src/edb/query/parser.py and src/edb/query/planner.py (the query
layer, eDB#88): every type alias and action the parser accepts or refuses,
and every planner route against a real in-memory Database, including the
validation errors each action returns instead of raising.
"""
import unittest
from typing import Any

from edb.core.database import Database
from edb.query.models import (
    DocumentQuery,
    KVQuery,
    QueryType,
    SQLQuery,
    UnifiedQuery,
)
from edb.query.parser import QueryParseError, QueryParser
from edb.query.planner import QueryPlanner


class TestParserTypes(unittest.TestCase):
    def setUp(self):
        self.p = QueryParser()

    def test_type_aliases_resolve(self):
        cases = {
            "sql": QueryType.SQL,
            "relational": QueryType.SQL,
            "SQL": QueryType.SQL,
            "document": QueryType.DOCUMENT,
            "doc": QueryType.DOCUMENT,
            "nosql": QueryType.DOCUMENT,
            "kv": QueryType.KV,
            "key_value": QueryType.KV,
            "keyvalue": QueryType.KV,
        }
        for raw, expected in cases.items():
            body = {"type": raw, "action": "count"}
            if expected == QueryType.SQL:
                body = {"type": raw, "action": "select", "table": "t"}
            elif expected == QueryType.DOCUMENT:
                body["collection"] = "c"
            self.assertEqual(self.p.parse(body).type, expected, raw)

    def test_unknown_type_is_refused(self):
        with self.assertRaises(QueryParseError) as ctx:
            self.p.parse({"type": "graph", "action": "find"})
        self.assertIn("Invalid query type 'graph'", str(ctx.exception))

    def test_missing_type_is_refused(self):
        with self.assertRaises(QueryParseError):
            self.p.parse({"action": "select"})


class TestParserSQL(unittest.TestCase):
    def setUp(self):
        self.p = QueryParser()

    def test_select_carries_every_field(self):
        q = self.p.parse({
            "type": "sql", "action": "SELECT", "table": "users",
            "columns": ["id"], "where": {"id": 1}, "order_by": "id",
            "limit": 5, "offset": 2,
        })
        self.assertEqual(q.sql.action, "select")
        self.assertEqual(q.sql.table, "users")
        self.assertEqual(q.sql.columns, ["id"])
        self.assertEqual(q.sql.where, {"id": 1})
        self.assertEqual((q.sql.order_by, q.sql.limit, q.sql.offset), ("id", 5, 2))

    def test_raw_needs_no_table(self):
        q = self.p.parse({"type": "sql", "action": "raw", "raw_sql": "SELECT 1", "params": [1]})
        self.assertEqual(q.sql.raw_sql, "SELECT 1")
        self.assertEqual(q.sql.params, [1])
        self.assertEqual(q.sql.table, "")

    def test_non_raw_without_table_is_refused(self):
        with self.assertRaises(QueryParseError) as ctx:
            self.p.parse({"type": "sql", "action": "select"})
        self.assertIn("'table'", str(ctx.exception))

    def test_unknown_sql_action_is_refused(self):
        with self.assertRaises(QueryParseError):
            self.p.parse({"type": "sql", "action": "truncate", "table": "t"})


class TestParserDocumentAndKV(unittest.TestCase):
    def setUp(self):
        self.p = QueryParser()

    def test_document_fields_and_merge_default(self):
        q = self.p.parse({
            "type": "doc", "action": "update", "collection": "c",
            "doc_id": "d1", "data": {"a": 1}, "filter": {"a": 1},
        })
        self.assertEqual(q.document.doc_id, "d1")
        self.assertTrue(q.document.merge)
        q2 = self.p.parse({"type": "doc", "action": "update", "collection": "c", "merge": False})
        self.assertFalse(q2.document.merge)

    def test_list_collections_needs_no_collection(self):
        q = self.p.parse({"type": "document", "action": "list_collections"})
        self.assertEqual(q.document.action, "list_collections")

    def test_document_without_collection_is_refused(self):
        with self.assertRaises(QueryParseError) as ctx:
            self.p.parse({"type": "document", "action": "find"})
        self.assertIn("'collection'", str(ctx.exception))

    def test_unknown_document_action_is_refused(self):
        with self.assertRaises(QueryParseError):
            self.p.parse({"type": "document", "action": "upsert", "collection": "c"})

    def test_kv_fields(self):
        q = self.p.parse({"type": "kv", "action": "set", "key": "k", "value": [1], "ttl": 9})
        self.assertEqual((q.kv.key, q.kv.value, q.kv.ttl), ("k", [1], 9))
        q2 = self.p.parse({"type": "kv", "action": "list", "prefix": "a:"})
        self.assertEqual(q2.kv.prefix, "a:")

    def test_unknown_kv_action_is_refused(self):
        with self.assertRaises(QueryParseError):
            self.p.parse({"type": "kv", "action": "incr", "key": "k"})


class _PlannerCase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.planner = QueryPlanner(self.db)
        self.parse = QueryParser().parse

    def tearDown(self):
        self.db.close()

    def run_q(self, body):
        return self.planner.execute(self.parse(body))


class TestPlannerSQL(_PlannerCase):
    def _make_table(self):
        r = self.run_q({
            "type": "sql", "action": "create_table", "table": "users",
            "data": {"columns": [
                {"name": "id", "col_type": "INTEGER", "primary_key": True},
                {"name": "name", "col_type": "TEXT"},
            ]},
        })
        self.assertTrue(r.success, r.error)
        self.assertEqual(r.data, {"table_created": "users"})

    def test_create_insert_select_update_delete_drop(self):
        self._make_table()
        ins = self.run_q({"type": "sql", "action": "insert", "table": "users",
                          "data": {"id": 7, "name": "Ada"}})
        self.assertTrue(ins.success, ins.error)
        self.assertEqual(ins.data, {"last_row_id": 7})
        self.assertEqual(ins.row_count, 1)

        sel = self.run_q({"type": "sql", "action": "select", "table": "users"})
        self.assertTrue(sel.success, sel.error)
        self.assertEqual(sel.data, [{"id": 7, "name": "Ada"}])
        self.assertEqual(sel.row_count, 1)
        self.assertEqual(sel.metadata["columns"], ["id", "name"])

        upd = self.run_q({"type": "sql", "action": "update", "table": "users",
                          "data": {"name": "Grace"}, "where": {"id": 7}})
        self.assertEqual((upd.success, upd.row_count), (True, 1))

        raw = self.run_q({"type": "sql", "action": "raw",
                          "raw_sql": "SELECT name FROM users WHERE id = ?", "params": [7]})
        self.assertTrue(raw.success, raw.error)
        self.assertEqual(raw.data, [{"name": "Grace"}])
        self.assertEqual(raw.metadata["columns"], ["name"])

        dele = self.run_q({"type": "sql", "action": "delete", "table": "users", "where": {"id": 7}})
        self.assertEqual((dele.success, dele.row_count), (True, 1))
        empty = self.run_q({"type": "sql", "action": "select", "table": "users"})
        self.assertEqual((empty.data, empty.row_count), ([], 0))

        drop = self.run_q({"type": "sql", "action": "drop_table", "table": "users"})
        self.assertEqual(drop.data, {"table_dropped": "users"})

    def test_raw_select_reports_columns_even_with_no_rows(self):
        self._make_table()
        r = self.run_q({"type": "sql", "action": "raw",
                        "raw_sql": "SELECT id, name FROM users WHERE id = -1"})
        self.assertTrue(r.success, r.error)
        self.assertIsNone(r.data)
        self.assertEqual(r.metadata["columns"], ["id", "name"])

    def test_raw_without_rows_returns_none_data(self):
        self._make_table()
        r = self.run_q({"type": "sql", "action": "raw",
                        "raw_sql": "UPDATE users SET name = 'x' WHERE id = -1"})
        self.assertTrue(r.success, r.error)
        self.assertIsNone(r.data)

    def test_validation_errors_are_results_not_exceptions(self):
        cases: list[tuple[dict[str, Any], str]] = [
            ({"action": "insert", "table": "t"}, "Insert requires 'data'"),
            ({"action": "update", "table": "t", "data": {"a": 1}}, "Update requires 'data' and 'where'"),
            ({"action": "delete", "table": "t"}, "Delete requires 'where'"),
            ({"action": "raw"}, "Raw query requires 'raw_sql'"),
            ({"action": "create_table", "table": "t", "data": {}}, "create_table requires"),
        ]
        for body, msg in cases:
            r = self.run_q({"type": "sql", **body})
            self.assertFalse(r.success, body)
            self.assertIn(msg, r.error)
            self.assertEqual(r.query_type, QueryType.SQL)

    def test_store_error_is_reported_not_raised(self):
        r = self.run_q({"type": "sql", "action": "select", "table": "no_such_table"})
        self.assertFalse(r.success)
        self.assertIn("no_such_table", r.error)

    def test_unknown_sql_action_reaching_planner(self):
        q = UnifiedQuery(type=QueryType.SQL, sql=SQLQuery(action="merge", table="t"))
        r = self.planner.execute(q)
        self.assertFalse(r.success)
        self.assertEqual(r.error, "Unknown SQL action: merge")


class TestPlannerDocument(_PlannerCase):
    def test_insert_find_update_count_delete(self):
        ins = self.run_q({"type": "doc", "action": "insert", "collection": "c",
                          "doc_id": "d1", "data": {"a": 1, "b": 2}})
        self.assertTrue(ins.success, ins.error)
        self.assertEqual(ins.row_count, 1)

        found = self.run_q({"type": "doc", "action": "find", "collection": "c", "filter": {"a": 1}})
        self.assertEqual(found.row_count, 1)
        by_id = self.run_q({"type": "doc", "action": "find_by_id", "collection": "c", "doc_id": "d1"})
        self.assertEqual(by_id.row_count, 1)

        merged = self.run_q({"type": "doc", "action": "update", "collection": "c",
                             "doc_id": "d1", "data": {"b": 3}})
        self.assertTrue(merged.success, merged.error)
        self.assertEqual(merged.data["data"], {"a": 1, "b": 3})

        cnt = self.run_q({"type": "doc", "action": "count", "collection": "c"})
        self.assertEqual((cnt.data, cnt.row_count), ({"count": 1}, 1))
        cols = self.run_q({"type": "doc", "action": "list_collections"})
        self.assertIn("c", cols.data)

        gone = self.run_q({"type": "doc", "action": "delete", "collection": "c", "doc_id": "d1"})
        self.assertEqual((gone.data, gone.row_count), ({"deleted": True}, 1))
        again = self.run_q({"type": "doc", "action": "delete", "collection": "c", "doc_id": "d1"})
        self.assertEqual((again.data, again.row_count), ({"deleted": False}, 0))

    def test_missing_documents(self):
        miss = self.run_q({"type": "doc", "action": "find_by_id", "collection": "c", "doc_id": "x"})
        self.assertEqual((miss.success, miss.data, miss.row_count), (True, None, 0))
        upd = self.run_q({"type": "doc", "action": "update", "collection": "c",
                          "doc_id": "x", "data": {"a": 1}})
        self.assertEqual((upd.success, upd.error), (False, "Document not found"))

    def test_validation_errors(self):
        cases: list[tuple[dict[str, Any], str]] = [
            ({"action": "find_by_id", "collection": "c"}, "find_by_id requires 'doc_id'"),
            ({"action": "insert", "collection": "c"}, "Insert requires 'data'"),
            ({"action": "update", "collection": "c", "doc_id": "d"}, "Update requires 'doc_id' and 'data'"),
            ({"action": "delete", "collection": "c"}, "Delete requires 'doc_id'"),
        ]
        for body, msg in cases:
            r = self.run_q({"type": "doc", **body})
            self.assertFalse(r.success, body)
            self.assertEqual(r.error, msg)

    def test_unknown_document_action_reaching_planner(self):
        q = UnifiedQuery(type=QueryType.DOCUMENT,
                         document=DocumentQuery(action="upsert", collection="c"))
        self.assertEqual(self.planner.execute(q).error, "Unknown document action: upsert")


class TestPlannerKV(_PlannerCase):
    def test_set_get_exists_list_count_delete(self):
        s = self.run_q({"type": "kv", "action": "set", "key": "a:1", "value": {"v": 1}})
        self.assertTrue(s.success, s.error)
        self.assertEqual(s.row_count, 1)
        self.run_q({"type": "kv", "action": "set", "key": "b:1", "value": 2})

        g = self.run_q({"type": "kv", "action": "get", "key": "a:1"})
        self.assertEqual((g.data, g.row_count), ({"v": 1}, 1))
        ex = self.run_q({"type": "kv", "action": "exists", "key": "a:1"})
        self.assertEqual(ex.data, {"exists": True})
        lst = self.run_q({"type": "kv", "action": "list", "prefix": "a:"})
        self.assertEqual(lst.data, ["a:1"])
        everything = self.run_q({"type": "kv", "action": "list"})
        self.assertEqual(sorted(everything.data), ["a:1", "b:1"])
        cnt = self.run_q({"type": "kv", "action": "count"})
        self.assertEqual(cnt.data, {"count": 2})

        d = self.run_q({"type": "kv", "action": "delete", "key": "a:1"})
        self.assertEqual((d.data, d.row_count), ({"deleted": True}, 1))
        miss = self.run_q({"type": "kv", "action": "get", "key": "a:1"})
        self.assertEqual((miss.data, miss.row_count), (None, 0))

    def test_key_required(self):
        for action, msg in (("get", "Get requires 'key'"), ("set", "Set requires 'key'"),
                            ("delete", "Delete requires 'key'"), ("exists", "Exists requires 'key'")):
            r = self.run_q({"type": "kv", "action": action})
            self.assertEqual((r.success, r.error), (False, msg))

    def test_unknown_kv_action_reaching_planner(self):
        q = UnifiedQuery(type=QueryType.KV, kv=KVQuery(action="incr", key="k"))
        self.assertEqual(self.planner.execute(q).error, "Unknown KV action: incr")


class TestPlannerDispatch(_PlannerCase):
    def test_type_without_its_payload_is_refused(self):
        for t in (QueryType.SQL, QueryType.DOCUMENT, QueryType.KV):
            r = self.planner.execute(UnifiedQuery(type=t))
            self.assertFalse(r.success)
            self.assertEqual(r.error, "Invalid query: missing type-specific query data")


if __name__ == "__main__":
    unittest.main()
