"""
tests/unit/test_unit_graph.py — Real eDB GraphStore unit tests
SPDX-License-Identifier: MIT  Copyright (c) 2026 EmbeddedOS Foundation

Exercises src/edb/core/graph.py (the least-covered core module, eDB#88)
against an in-memory StorageEngine.
"""
import unittest

from edb.core.engine import StorageEngine
from edb.core.graph import GraphStore


class TestGraphNodes(unittest.TestCase):
    def setUp(self):
        self.g = GraphStore(StorageEngine(":memory:"))

    def test_add_and_get_node(self):
        n = self.g.add_node("Person", {"name": "Ada"}, node_id="n1")
        self.assertEqual(n["id"], "n1")
        self.assertEqual(n["label"], "Person")
        got = self.g.get_node("n1")
        self.assertEqual(got["properties"], {"name": "Ada"})

    def test_add_node_generates_id(self):
        n = self.g.add_node("Person")
        self.assertTrue(n["id"])
        self.assertIsNotNone(self.g.get_node(n["id"]))

    def test_get_missing_node_returns_none(self):
        self.assertIsNone(self.g.get_node("nope"))

    def test_find_nodes_by_label(self):
        self.g.add_node("Person", node_id="a")
        self.g.add_node("Person", node_id="b")
        self.g.add_node("Place", node_id="c")
        found = self.g.find_nodes("Person")
        self.assertEqual({n["id"] for n in found}, {"a", "b"})

    def test_find_nodes_all(self):
        self.g.add_node("Person", node_id="a")
        self.g.add_node("Place", node_id="b")
        self.assertEqual(len(self.g.find_nodes()), 2)

    def test_delete_node_removes_incident_edges(self):
        self.g.add_node("Person", node_id="a")
        self.g.add_node("Person", node_id="b")
        self.g.add_edge("a", "b", "KNOWS")
        self.assertTrue(self.g.delete_node("a"))
        self.assertIsNone(self.g.get_node("a"))
        self.assertEqual(self.g.edge_count(), 0)

    def test_delete_missing_node_returns_false(self):
        self.assertFalse(self.g.delete_node("nope"))

    def test_node_count(self):
        self.assertEqual(self.g.node_count(), 0)
        self.g.add_node("Person", node_id="a")
        self.g.add_node("Person", node_id="b")
        self.assertEqual(self.g.node_count(), 2)


class TestGraphEdges(unittest.TestCase):
    def setUp(self):
        self.g = GraphStore(StorageEngine(":memory:"))
        self.g.add_node("Person", node_id="a")
        self.g.add_node("Person", node_id="b")
        self.g.add_node("Person", node_id="c")

    def test_add_and_get_edges_out(self):
        e = self.g.add_edge("a", "b", "KNOWS", {"since": 2020})
        self.assertEqual(e["source_id"], "a")
        self.assertEqual(e["target_id"], "b")
        out = self.g.get_edges("a", direction="out")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["relationship"], "KNOWS")
        self.assertEqual(out[0]["properties"], {"since": 2020})

    def test_get_edges_in(self):
        self.g.add_edge("a", "b", "KNOWS")
        inn = self.g.get_edges("b", direction="in")
        self.assertEqual(len(inn), 1)
        self.assertEqual(inn[0]["source_id"], "a")

    def test_get_edges_both(self):
        self.g.add_edge("a", "b", "KNOWS")
        self.g.add_edge("c", "a", "LIKES")
        both = self.g.get_edges("a", direction="both")
        self.assertEqual(len(both), 2)

    def test_get_edges_filtered_by_relationship(self):
        self.g.add_edge("a", "b", "KNOWS")
        self.g.add_edge("a", "c", "LIKES")
        knows = self.g.get_edges("a", relationship="KNOWS")
        self.assertEqual(len(knows), 1)
        self.assertEqual(knows[0]["target_id"], "b")

    def test_delete_edge(self):
        e = self.g.add_edge("a", "b", "KNOWS")
        self.assertTrue(self.g.delete_edge(e["id"]))
        self.assertEqual(self.g.get_edges("a"), [])

    def test_delete_missing_edge_returns_false(self):
        self.assertFalse(self.g.delete_edge("nope"))

    def test_edge_count(self):
        self.assertEqual(self.g.edge_count(), 0)
        self.g.add_edge("a", "b", "KNOWS")
        self.g.add_edge("b", "c", "KNOWS")
        self.assertEqual(self.g.edge_count(), 2)


class TestGraphTraversal(unittest.TestCase):
    def setUp(self):
        self.g = GraphStore(StorageEngine(":memory:"))
        for nid in ("a", "b", "c", "d"):
            self.g.add_node("N", node_id=nid)
        self.g.add_edge("a", "b", "KNOWS")
        self.g.add_edge("b", "c", "KNOWS")
        self.g.add_edge("a", "d", "LIKES")

    def test_traverse_reaches_all(self):
        ids = {n["id"] for n in self.g.traverse("a")}
        self.assertEqual(ids, {"a", "b", "c", "d"})

    def test_traverse_relationship_filter(self):
        ids = {n["id"] for n in self.g.traverse("a", relationship="KNOWS")}
        self.assertEqual(ids, {"a", "b", "c"})

    def test_traverse_depth_limit(self):
        ids = {n["id"] for n in self.g.traverse("a", depth=1)}
        self.assertEqual(ids, {"a", "b", "d"})

    def test_shortest_path(self):
        self.assertEqual(self.g.shortest_path("a", "c"), ["a", "b", "c"])

    def test_shortest_path_self(self):
        self.assertEqual(self.g.shortest_path("a", "a"), ["a"])

    def test_shortest_path_unreachable(self):
        self.g.add_node("N", node_id="z")
        self.assertIsNone(self.g.shortest_path("a", "z"))


if __name__ == "__main__":
    unittest.main()
