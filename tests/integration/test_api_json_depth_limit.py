"""Integration tests: deeply nested JSON values are rejected, not stored-then-500 (eDB#220).

A KV value or document nested ~300+ levels deep used to be stored, but every
response containing it returned 500 (FastAPI/Pydantic could not serialize the
response), and past ~480 levels even the 422 error path failed the same way.
Values nested more than 100 levels are now rejected with 422 before anything
is stored, and the 422 itself is returned even for a ~500-level input.
"""

from typing import Any

import pytest


def _nested(levels: int) -> Any:
    """Return ``1`` wrapped in ``levels`` nested lists."""
    value: Any = 1
    for _ in range(levels):
        value = [value]
    return value


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def test_kv_set_rejects_values_nested_over_100_levels(app_client, h):
    resp = app_client.put("/kv/deep", json={"value": _nested(101)}, headers=h)
    assert resp.status_code == 422
    assert app_client.get("/kv/deep", headers=h).status_code == 404


def test_kv_set_accepts_values_nested_100_levels(app_client, h):
    value = _nested(100)
    assert app_client.put("/kv/deep", json={"value": value}, headers=h).status_code == 200
    assert app_client.get("/kv/deep", headers=h).json()["value"] == value


def test_document_insert_rejects_values_nested_over_100_levels(app_client, h):
    resp = app_client.post("/docs/c", json={"data": {"x": _nested(101)}}, headers=h)
    assert resp.status_code == 422
    assert app_client.post("/docs/c/find", json={}, headers=h).json()["count"] == 0


def test_document_depth_counts_the_enclosing_data_mapping(app_client, h):
    # The `data` mapping is part of the stored document, so it counts toward the
    # limit: a field value nested 100 levels sits at depth 101 and is rejected.
    # Validating each field value separately would restart the count at 0 and
    # let a document nest one level deeper than a KV value.
    resp = app_client.post("/docs/c", json={"data": {"x": _nested(100)}}, headers=h)
    assert resp.status_code == 422
    assert app_client.post("/docs/c/find", json={}, headers=h).json()["count"] == 0


def test_document_accepts_value_at_the_depth_limit(app_client, h):
    value = _nested(99)
    assert app_client.post("/docs/c", json={"data": {"x": value}}, headers=h).status_code == 201
    found = app_client.post("/docs/c/find", json={}, headers=h).json()
    assert found["count"] == 1
    assert found["documents"][0]["data"]["x"] == value


def test_very_deep_value_returns_422_not_500(app_client, h):
    # ~500 levels: the rejected input is echoed in the 422 body, and encoding
    # that echo used to recurse past the limit and turn the 422 into a 500.
    resp = app_client.put("/kv/deep", json={"value": _nested(500)}, headers=h)
    assert resp.status_code == 422
    assert app_client.get("/kv/deep", headers=h).status_code == 404
