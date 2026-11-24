"""Integration tests for 422 responses (src/edb/api/app.py, eDB#199).

Python's JSON parser accepts the non-standard literals NaN and Infinity. When
such a value is rejected, the 422 response must still be valid JSON instead of
failing to encode and becoming a 500.
"""

import pytest

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", **JSON}


def test_login_with_a_nan_username_returns_422(app_client):
    # No token needed: any client could trigger the 500 before.
    resp = app_client.post(
        "/auth/login", content='{"username": NaN, "password": "x"}', headers=JSON
    )
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["input"] == "nan"


@pytest.mark.parametrize(
    ("method", "path", "body", "shown_as"),
    [
        ("PUT", "/kv/k", '{"value": "v", "ttl": NaN}', "nan"),
        ("POST", "/docs/c/find", '{"limit": NaN}', "nan"),
        ("POST", "/graph/traverse", '{"start_id": "a", "depth": Infinity}', "inf"),
        ("POST", "/docs/c/find", '{"limit": -Infinity}', "-inf"),
    ],
)
def test_non_finite_value_in_a_rejected_field_returns_422(
    app_client, h, method, path, body, shown_as
):
    resp = app_client.request(method, path, content=body, headers=h)
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["input"] == shown_as


def test_ordinary_validation_errors_are_unchanged(app_client, h):
    resp = app_client.post("/docs/c/find", content='{"limit": "abc"}', headers=h)
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["input"] == "abc"
