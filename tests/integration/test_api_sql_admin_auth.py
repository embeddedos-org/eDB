"""Integration tests for the SQL, admin and auth API routes (#88).

Covers the success and error paths of ``edb.api.routes.sql``,
``edb.api.routes.admin`` and ``edb.api.routes.auth`` that
``test_api.py`` does not exercise.
"""

import pytest

READER_PASSWORD = "Reader@12345678!"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, username, password):
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()


def _register(client, username, password, role):
    resp = client.post(
        "/auth/register",
        json={"username": username, "password": password, "role": role},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
def h(admin_token):
    return _auth(admin_token)


@pytest.fixture
def items_table(app_client, h):
    """An ``items`` table holding two rows."""
    resp = app_client.post(
        "/sql/tables",
        json={
            "name": "items",
            "columns": [
                {"name": "id", "col_type": "INTEGER", "primary_key": True},
                {"name": "name", "col_type": "TEXT"},
                {"name": "qty", "col_type": "INTEGER"},
            ],
        },
        headers=h,
    )
    assert resp.status_code == 200
    for row in ({"id": 1, "name": "bolt", "qty": 10}, {"id": 2, "name": "nut", "qty": 5}):
        resp = app_client.post("/sql/tables/items/insert", json={"data": row}, headers=h)
        assert resp.status_code == 200
    return "items"


@pytest.fixture
def reader(app_client):
    """A registered read-only user and their access token."""
    user = _register(app_client, "reader", READER_PASSWORD, "read_only")
    tokens = _login(app_client, "reader", READER_PASSWORD)
    return user, tokens["access_token"]


# ── SQL routes ────────────────────────────────────────────────────────────


class TestSQLExecute:
    def test_select_returns_result(self, app_client, h, items_table):
        resp = app_client.post(
            "/sql/execute",
            json={"sql": "SELECT name FROM items WHERE qty > ?", "params": [6]},
            headers=h,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["columns"] == ["name"]
        assert body["rows"] == [{"name": "bolt"}]

    def test_execute_is_audited(self, app_client, h, items_table):
        app_client.post("/sql/execute", json={"sql": "SELECT 1"}, headers=h)
        logs = app_client.get("/admin/audit?event_type=query", headers=h).json()["logs"]
        assert any(entry["action"] == "sql_execute" for entry in logs)

    def test_injection_pattern_rejected(self, app_client, h, items_table):
        resp = app_client.post(
            "/sql/execute",
            json={"sql": "SELECT * FROM items; DROP TABLE items"},
            headers=h,
        )
        assert resp.status_code == 400
        assert any("SQL injection" in w for w in resp.json()["detail"])
        # The table must survive the rejected statement.
        assert "items" in app_client.get("/sql/tables", headers=h).json()["tables"]

    def test_invalid_sql_returns_400(self, app_client, h):
        resp = app_client.post("/sql/execute", json={"sql": "SELEC nonsense"}, headers=h)
        assert resp.status_code == 400

    def test_read_only_user_forbidden(self, app_client, reader):
        _, token = reader
        resp = app_client.post("/sql/execute", json={"sql": "SELECT 1"}, headers=_auth(token))
        assert resp.status_code == 403

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE _edb_users SET role='admin' WHERE username='writer'",
            "DELETE FROM _edb_audit_log",
        ],
    )
    def test_read_write_user_forbidden(self, app_client, h, sql):
        user = _register(app_client, "writer", READER_PASSWORD, "read_only")
        resp = app_client.put(
            f"/admin/users/{user['id']}/role", json={"role": "read_write"}, headers=h
        )
        assert resp.status_code == 200
        token = _login(app_client, "writer", READER_PASSWORD)["access_token"]

        resp = app_client.post("/sql/execute", json={"sql": sql}, headers=_auth(token))
        assert resp.status_code == 403

        users = {u["username"]: u for u in app_client.get("/admin/users", headers=h).json()}
        assert users["writer"]["role"] == "read_write"


class TestSQLTables:
    def test_create_table_invalid_column_returns_400(self, app_client, h):
        resp = app_client.post(
            "/sql/tables",
            json={"name": "bad", "columns": [{"name": "x", "not_a_field": True}]},
            headers=h,
        )
        assert resp.status_code == 400

    def test_get_missing_table_returns_400(self, app_client, h):
        resp = app_client.get("/sql/tables/does_not_exist", headers=h)
        assert resp.status_code == 400

    def test_get_table_paginates(self, app_client, h, items_table):
        resp = app_client.get("/sql/tables/items?limit=1&offset=1", headers=h)
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 1
        assert resp.json()["rows"][0]["id"] == 2

    def test_read_only_user_can_list(self, app_client, reader, items_table):
        _, token = reader
        resp = app_client.get("/sql/tables", headers=_auth(token))
        assert resp.status_code == 200
        assert "items" in resp.json()["tables"]


class TestSQLSelect:
    def test_select_with_filters(self, app_client, h, items_table):
        resp = app_client.post(
            "/sql/tables/items/select",
            json={"columns": ["name"], "order_by": "qty", "limit": 10, "offset": 0},
            headers=h,
        )
        assert resp.status_code == 200
        assert [r["name"] for r in resp.json()["rows"]] == ["nut", "bolt"]

    def test_select_where(self, app_client, h, items_table):
        resp = app_client.post(
            "/sql/tables/items/select", json={"where": {"name": "nut"}}, headers=h
        )
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 1
        assert resp.json()["rows"][0]["qty"] == 5

    def test_select_missing_table_returns_400(self, app_client, h):
        resp = app_client.post("/sql/tables/nope/select", json={}, headers=h)
        assert resp.status_code == 400


class TestSQLMutations:
    def test_insert_returns_row_id(self, app_client, h, items_table):
        resp = app_client.post(
            "/sql/tables/items/insert",
            json={"data": {"id": 3, "name": "washer", "qty": 1}},
            headers=h,
        )
        assert resp.status_code == 200
        assert resp.json() == {"last_row_id": 3, "affected_rows": 1}

    def test_insert_duplicate_key_returns_400(self, app_client, h, items_table):
        resp = app_client.post(
            "/sql/tables/items/insert",
            json={"data": {"id": 1, "name": "dup", "qty": 0}},
            headers=h,
        )
        assert resp.status_code == 400

    def test_update_rows(self, app_client, h, items_table):
        resp = app_client.put(
            "/sql/tables/items/update",
            json={"data": {"qty": 99}, "where": {"id": 1}},
            headers=h,
        )
        assert resp.status_code == 200
        assert resp.json()["affected_rows"] == 1
        rows = app_client.post(
            "/sql/tables/items/select", json={"where": {"id": 1}}, headers=h
        ).json()["rows"]
        assert rows[0]["qty"] == 99

    def test_update_missing_table_returns_400(self, app_client, h):
        resp = app_client.put(
            "/sql/tables/nope/update",
            json={"data": {"qty": 1}, "where": {"id": 1}},
            headers=h,
        )
        assert resp.status_code == 400

    def test_delete_rows(self, app_client, h, items_table):
        resp = app_client.request(
            "DELETE", "/sql/tables/items/delete", json={"where": {"id": 2}}, headers=h
        )
        assert resp.status_code == 200
        assert resp.json()["affected_rows"] == 1
        assert app_client.get("/sql/tables/items", headers=h).json()["row_count"] == 1

    def test_delete_missing_table_returns_400(self, app_client, h):
        resp = app_client.request(
            "DELETE", "/sql/tables/nope/delete", json={"where": {"id": 1}}, headers=h
        )
        assert resp.status_code == 400

    def test_read_only_user_cannot_delete(self, app_client, reader, items_table):
        _, token = reader
        resp = app_client.request(
            "DELETE",
            "/sql/tables/items/delete",
            json={"where": {"id": 1}},
            headers=_auth(token),
        )
        assert resp.status_code == 403


# ── Admin routes ──────────────────────────────────────────────────────────


class TestAdminUsers:
    def test_list_users(self, app_client, h, reader):
        resp = app_client.get("/admin/users", headers=h)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.json()}
        assert {"admin", "reader"} <= names

    def test_list_users_forbidden_for_read_only(self, app_client, reader):
        _, token = reader
        assert app_client.get("/admin/users", headers=_auth(token)).status_code == 403

    def test_update_role(self, app_client, h, reader):
        user, _ = reader
        resp = app_client.put(
            f"/admin/users/{user['id']}/role", json={"role": "read_write"}, headers=h
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Role updated to read_write"
        users = {u["id"]: u for u in app_client.get("/admin/users", headers=h).json()}
        assert users[user["id"]]["role"] == "read_write"

    def test_update_role_unknown_user_returns_404(self, app_client, h):
        resp = app_client.put("/admin/users/no-such-id/role", json={"role": "admin"}, headers=h)
        assert resp.status_code == 404

    def test_update_role_invalid_role_returns_422(self, app_client, h, reader):
        user, _ = reader
        resp = app_client.put(
            f"/admin/users/{user['id']}/role", json={"role": "superuser"}, headers=h
        )
        assert resp.status_code == 422

    def test_deactivate_user(self, app_client, h, reader):
        user, _ = reader
        resp = app_client.delete(f"/admin/users/{user['id']}", headers=h)
        assert resp.status_code == 200
        # A deactivated user can no longer log in.
        resp = app_client.post(
            "/auth/login", json={"username": "reader", "password": READER_PASSWORD}
        )
        assert resp.status_code == 401

    def test_deactivate_self_rejected(self, app_client, h):
        me = app_client.get("/auth/me", headers=h).json()
        resp = app_client.delete(f"/admin/users/{me['id']}", headers=h)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot deactivate yourself"

    def test_deactivate_unknown_user_returns_404(self, app_client, h):
        assert app_client.delete("/admin/users/no-such-id", headers=h).status_code == 404


class TestAdminAudit:
    def test_get_logs_filtered(self, app_client, h):
        resp = app_client.get("/admin/audit?event_type=auth&limit=50", headers=h)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == len(body["logs"])
        assert body["count"] >= 1  # the admin login
        assert all(entry["event_type"] == "auth" for entry in body["logs"])

    def test_verify_chain(self, app_client, h):
        resp = app_client.get("/admin/audit/verify", headers=h)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_audit_forbidden_for_read_only(self, app_client, reader):
        _, token = reader
        assert app_client.get("/admin/audit", headers=_auth(token)).status_code == 403


# ── Auth routes ───────────────────────────────────────────────────────────


class TestAuthRegister:
    def test_duplicate_username_returns_409(self, app_client):
        _register(app_client, "dupe", READER_PASSWORD, "read_only")
        resp = app_client.post(
            "/auth/register",
            json={"username": "dupe", "password": READER_PASSWORD, "role": "read_only"},
        )
        assert resp.status_code == 409

    @pytest.mark.parametrize("requested_role", ["admin", "read_write"])
    def test_caller_supplied_role_is_ignored(self, app_client, requested_role):
        user = _register(app_client, "eve", READER_PASSWORD, requested_role)
        assert user["role"] == "read_only"

        token = _login(app_client, "eve", READER_PASSWORD)["access_token"]
        assert app_client.get("/admin/users", headers=_auth(token)).status_code == 403


class TestAuthRefresh:
    def test_refresh_issues_new_tokens(self, app_client):
        tokens = _login(app_client, "admin", "Admin@12345678!")
        resp = app_client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert resp.status_code == 200
        new = resp.json()
        assert new["token_type"] == "bearer"
        assert app_client.get("/auth/me", headers=_auth(new["access_token"])).status_code == 200

    def test_access_token_rejected_as_refresh(self, app_client, admin_token):
        resp = app_client.post("/auth/refresh", json={"refresh_token": admin_token})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid refresh token"

    def test_garbage_token_rejected(self, app_client):
        resp = app_client.post("/auth/refresh", json={"refresh_token": "not-a-jwt"})
        assert resp.status_code == 401

    def test_missing_token_rejected(self, app_client):
        assert app_client.post("/auth/refresh", json={}).status_code == 401

    def test_inactive_user_rejected(self, app_client, h):
        user = _register(app_client, "leaver", READER_PASSWORD, "read_only")
        tokens = _login(app_client, "leaver", READER_PASSWORD)
        assert app_client.delete(f"/admin/users/{user['id']}", headers=h).status_code == 200
        resp = app_client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not found or inactive"


class TestAuthPassword:
    def test_wrong_current_password_returns_400(self, app_client, h):
        resp = app_client.post(
            "/auth/password",
            json={"current_password": "Wrong@12345678!", "new_password": "Admin@NewPass99!"},
            headers=h,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Wrong current password"
        # The old password still works.
        _login(app_client, "admin", "Admin@12345678!")
