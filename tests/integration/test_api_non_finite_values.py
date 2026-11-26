"""Integration tests: NaN and Infinity inside stored values are rejected (eDB#201).

Python's JSON parser accepts NaN and Infinity. The KV and document routes used to
store them as invalid JSON and read them back as null; they now return 422.
"""

import pytest

NON_FINITE = ["NaN", "Infinity", "-Infinity"]


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# In each body, VALUE is replaced by one of NON_FINITE.
@pytest.mark.parametrize("literal", NON_FINITE)
@pytest.mark.parametrize("body", ['{"value": VALUE}', '{"value": {"a": [1, {"b": VALUE}]}}'])
def test_kv_set_rejects_non_finite_values(app_client, h, body, literal):
    resp = app_client.put("/kv/k", content=body.replace("VALUE", literal), headers=h)
    assert resp.status_code == 422
    assert app_client.get("/kv/k", headers=h).status_code == 404


@pytest.mark.parametrize("literal", NON_FINITE)
@pytest.mark.parametrize("body", ['{"data": {"x": VALUE}}', '{"data": {"x": [1, {"y": VALUE}]}}'])
def test_document_insert_rejects_non_finite_values(app_client, h, body, literal):
    resp = app_client.post("/docs/c", content=body.replace("VALUE", literal), headers=h)
    assert resp.status_code == 422
    assert app_client.post("/docs/c/find", json={}, headers=h).json()["count"] == 0


@pytest.mark.parametrize("literal", NON_FINITE)
def test_document_update_rejects_non_finite_values(app_client, h, literal):
    doc_id = app_client.post("/docs/c", json={"data": {"x": 1}}, headers=h).json()["id"]
    body = '{"data": {"x": VALUE}}'.replace("VALUE", literal)
    assert app_client.put(f"/docs/c/{doc_id}", content=body, headers=h).status_code == 422
    assert app_client.get(f"/docs/c/{doc_id}", headers=h).json()["data"] == {"x": 1}


def test_finite_values_are_still_stored(app_client, h):
    value = {"a": [1.5, -2, {"b": 0.0}]}
    assert app_client.put("/kv/k", json={"value": value}, headers=h).status_code == 200
    assert app_client.get("/kv/k", headers=h).json()["value"] == value
    resp = app_client.post("/docs/c", json={"data": value}, headers=h)
    assert resp.status_code == 201
    assert app_client.get(f"/docs/c/{resp.json()['id']}", headers=h).json()["data"] == value
