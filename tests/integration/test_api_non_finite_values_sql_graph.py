"""Integration tests: NaN and Infinity inside SQL and graph writes are rejected (eDB#223).

Step 1 of #223 (API routes only): `POST /sql/tables/{table}/insert`,
`PUT /sql/tables/{table}/update`, `POST /graph/nodes` and `POST /graph/edges`
use the same `FiniteJSON` validator #219 added for the KV and document routes,
so non-finite values are rejected with 422 instead of being stored as invalid
JSON and read back as null. Core-layer writers (library/CLI callers) still
accept them; that is the design question in #223 step 2.
"""

import pytest

NON_FINITE = ["NaN", "Infinity", "-Infinity"]


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture
def numbers(app_client, h):
    """A table ``numbers`` holding one row, id 1 with x 1.5."""
    columns = [
        {"name": "id", "col_type": "INTEGER", "primary_key": True},
        {"name": "x", "col_type": "REAL"},
    ]
    resp = app_client.post("/sql/tables", json={"name": "numbers", "columns": columns}, headers=h)
    assert resp.status_code == 200
    resp = app_client.post(
        "/sql/tables/numbers/insert", json={"data": {"id": 1, "x": 1.5}}, headers=h
    )
    assert resp.status_code == 200
    return "numbers"


@pytest.mark.parametrize("literal", NON_FINITE)
def test_sql_insert_rejects_non_finite_values(app_client, h, numbers, literal):
    body = '{"data": {"id": 2, "x": VALUE}}'.replace("VALUE", literal)
    resp = app_client.post(f"/sql/tables/{numbers}/insert", content=body, headers=h)
    assert resp.status_code == 422
    rows = app_client.get(f"/sql/tables/{numbers}", headers=h).json()["rows"]
    assert [row["id"] for row in rows] == [1]


@pytest.mark.parametrize("literal", NON_FINITE)
def test_sql_update_rejects_non_finite_values(app_client, h, numbers, literal):
    body = '{"data": {"x": VALUE}, "where": {"id": 1}}'.replace("VALUE", literal)
    resp = app_client.put(f"/sql/tables/{numbers}/update", content=body, headers=h)
    assert resp.status_code == 422
    rows = app_client.get(f"/sql/tables/{numbers}", headers=h).json()["rows"]
    assert rows == [{"id": 1, "x": 1.5}]


@pytest.mark.parametrize("literal", NON_FINITE)
def test_graph_node_rejects_non_finite_properties(app_client, h, literal):
    body = '{"label": "P", "properties": {"x": VALUE}}'.replace("VALUE", literal)
    assert app_client.post("/graph/nodes", content=body, headers=h).status_code == 422
    assert app_client.get("/graph/nodes", headers=h).json()["count"] == 0


@pytest.mark.parametrize("literal", NON_FINITE)
def test_graph_edge_rejects_non_finite_properties(app_client, h, literal):
    app_client.post("/graph/nodes", json={"label": "P", "node_id": "a"}, headers=h)
    app_client.post("/graph/nodes", json={"label": "P", "node_id": "b"}, headers=h)
    body = (
        '{"source_id": "a", "target_id": "b", "relationship": "R", '
        '"properties": {"w": VALUE}}'
    ).replace("VALUE", literal)
    assert app_client.post("/graph/edges", content=body, headers=h).status_code == 422
    assert app_client.get("/graph/nodes/a/edges", headers=h).json()["count"] == 0


def test_finite_values_are_still_stored(app_client, h, numbers):
    assert (
        app_client.post(
            f"/sql/tables/{numbers}/insert", json={"data": {"id": 2, "x": 2.5}}, headers=h
        ).status_code
        == 200
    )
    resp = app_client.post(
        "/graph/nodes", json={"label": "P", "properties": {"x": 1.5}}, headers=h
    )
    assert resp.status_code == 201
    assert resp.json()["properties"] == {"x": 1.5}
