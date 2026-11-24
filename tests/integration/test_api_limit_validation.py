"""Integration tests for limit/offset validation on the paged GET routes (eDB#210).

GET /sql/tables/{table} and GET /admin/audit used to pass any integer to
SQLite: limit=-1 returned every row, and a value past the 64-bit range raised
OverflowError (a 500 on /admin/audit).
"""

import pytest

PATHS = ["/sql/tables/numbers", "/admin/audit"]
OUT_OF_RANGE = [
    {"limit": -1},
    {"limit": 0},
    {"limit": 1001},
    {"limit": 2**63},
    {"offset": -1},
    {"offset": 2**63},
]


@pytest.fixture
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def numbers(app_client, h):
    """A table ``numbers`` holding ids 1, 2 and 3."""
    columns = [{"name": "id", "col_type": "INTEGER", "primary_key": True}]
    resp = app_client.post("/sql/tables", json={"name": "numbers", "columns": columns}, headers=h)
    assert resp.status_code == 200
    for i in (1, 2, 3):
        app_client.post("/sql/tables/numbers/insert", json={"data": {"id": i}}, headers=h)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("params", OUT_OF_RANGE)
def test_out_of_range_limit_or_offset_returns_422(app_client, h, numbers, path, params):
    assert app_client.get(path, params=params, headers=h).status_code == 422


def test_table_rows_can_still_be_paged(app_client, h, numbers):
    resp = app_client.get("/sql/tables/numbers", params={"limit": 2, "offset": 1}, headers=h)
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()["rows"]] == [2, 3]


def test_audit_log_can_still_be_paged(app_client, h, numbers):
    newest = app_client.get("/admin/audit", params={"limit": 1}, headers=h).json()["logs"]
    second = app_client.get("/admin/audit", params={"limit": 1, "offset": 1}, headers=h).json()[
        "logs"
    ]
    assert len(newest) == 1
    assert len(second) == 1
    assert second[0]["id"] < newest[0]["id"]
