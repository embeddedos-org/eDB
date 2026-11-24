"""Integration tests for graph route parameter validation (src/edb/api/routes/graph.py, eDB#197).

Out-of-range or unknown values used to be accepted and silently changed the
result (limit=-1 returned every node; direction=outgoing meant "both").
"""

import pytest


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.mark.parametrize("limit", [-1, 0, 1001, 2**63])
def test_find_nodes_rejects_a_limit_outside_1_to_1000(app_client, h, limit):
    resp = app_client.get("/graph/nodes", params={"limit": limit}, headers=h)
    assert resp.status_code == 422


def test_get_edges_rejects_an_unknown_direction(app_client, h):
    resp = app_client.get("/graph/nodes/a/edges", params={"direction": "outgoing"}, headers=h)
    assert resp.status_code == 422


@pytest.mark.parametrize("depth", [0, -1])
def test_traverse_rejects_a_depth_below_one(app_client, h, depth):
    resp = app_client.post("/graph/traverse", json={"start_id": "a", "depth": depth}, headers=h)
    assert resp.status_code == 422


def test_valid_values_still_work(app_client, h):
    for node_id in ("a", "b", "c"):
        app_client.post("/graph/nodes", json={"label": "N", "node_id": node_id}, headers=h)
    for src, dst in (("a", "b"), ("b", "c")):
        edge = {"source_id": src, "target_id": dst, "relationship": "NEXT"}
        app_client.post("/graph/edges", json=edge, headers=h)

    assert app_client.get("/graph/nodes", params={"limit": 2}, headers=h).json()["count"] == 2
    expected = {"out": [("a", "b")], "in": [], "both": [("a", "b")]}
    for direction, pairs in expected.items():
        resp = app_client.get("/graph/nodes/a/edges", params={"direction": direction}, headers=h)
        assert [(e["source_id"], e["target_id"]) for e in resp.json()["edges"]] == pairs, direction
    resp = app_client.post("/graph/traverse", json={"start_id": "a", "depth": 2}, headers=h)
    assert sorted(n["id"] for n in resp.json()["nodes"]) == ["a", "b", "c"]
