"""Integration tests for the graph routes (src/edb/api/routes/graph.py, eDB#88).

test_api.py::test_graph_crud covers adding nodes and edges, reading one node
and the stats; these cover the remaining routes and their 404 paths.
"""

import pytest


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def graph(app_client, h):
    """Nodes a, b (Person) and c (Company); edges a-KNOWS->b, b-KNOWS->c, c-LIKES->a.
    c is two KNOWS hops from a, so a depth-1 traversal must not reach it.
    """
    for node_id, label in (("a", "Person"), ("b", "Person"), ("c", "Company")):
        resp = app_client.post("/graph/nodes", json={"label": label, "node_id": node_id}, headers=h)
        assert resp.status_code == 201
    for src, dst, rel in (("a", "b", "KNOWS"), ("b", "c", "KNOWS"), ("c", "a", "LIKES")):
        resp = app_client.post(
            "/graph/edges",
            json={"source_id": src, "target_id": dst, "relationship": rel},
            headers=h,
        )
        assert resp.status_code == 201
    return app_client


def _ids(items):
    return sorted(item["id"] for item in items)


def _pairs(edges):
    return sorted((e["source_id"], e["target_id"]) for e in edges)


def test_get_missing_node_returns_404(app_client, h):
    resp = app_client.get("/graph/nodes/nope", headers=h)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Node not found"


def test_find_nodes_by_label_and_limit(graph, h):
    resp = graph.get("/graph/nodes", params={"label": "Person"}, headers=h)
    assert resp.status_code == 200
    assert _ids(resp.json()["nodes"]) == ["a", "b"]
    assert resp.json()["count"] == 2

    resp = graph.get("/graph/nodes", params={"limit": 1}, headers=h)
    assert resp.json()["count"] == 1


def test_delete_node_then_missing(graph, h):
    assert graph.delete("/graph/nodes/b", headers=h).json() == {"deleted": True}
    assert graph.get("/graph/nodes/b", headers=h).status_code == 404

    resp = graph.delete("/graph/nodes/b", headers=h)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Node not found"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"direction": "out"}, [("a", "b")]),
        ({"direction": "in"}, [("c", "a")]),
        ({}, [("a", "b"), ("c", "a")]),
        ({"relationship": "KNOWS"}, [("a", "b")]),
    ],
)
def test_get_edges_by_direction_and_relationship(graph, h, query, expected):
    resp = graph.get("/graph/nodes/a/edges", params=query, headers=h)
    assert resp.status_code == 200
    assert _pairs(resp.json()["edges"]) == expected
    assert resp.json()["count"] == len(expected)


def test_traverse_follows_relationship_up_to_depth(graph, h):
    body = {"start_id": "a", "relationship": "KNOWS", "depth": 1}
    resp = graph.post("/graph/traverse", json=body, headers=h)
    assert resp.status_code == 200
    assert _ids(resp.json()["nodes"]) == ["a", "b"]  # c is a second hop away

    body["depth"] = 2
    resp = graph.post("/graph/traverse", json=body, headers=h)
    assert _ids(resp.json()["nodes"]) == ["a", "b", "c"]
    assert resp.json()["count"] == 3
