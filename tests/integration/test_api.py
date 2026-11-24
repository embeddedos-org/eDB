"""Integration tests for the REST API."""


def test_health(app_client):
    resp = app_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_register_and_login(app_client):
    resp = app_client.post("/auth/register", json={
        "username": "testuser", "password": "TestUser@12345!", "role": "read_write",
    })
    assert resp.status_code == 201
    assert resp.json()["username"] == "testuser"

    resp = app_client.post("/auth/login", json={"username": "testuser", "password": "TestUser@12345!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(app_client):
    resp = app_client.post("/auth/login", json={"username": "admin", "password": "wrongpass"})
    assert resp.status_code == 401


def test_get_me(app_client, admin_token):
    resp = app_client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_change_password(app_client, admin_token):
    resp = app_client.post("/auth/password", json={
        "current_password": "Admin@12345678!", "new_password": "Admin@NewPass99!",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200

    resp = app_client.post("/auth/login", json={"username": "admin", "password": "Admin@NewPass99!"})
    assert resp.status_code == 200


def test_logout(app_client, admin_token):
    resp = app_client.post("/auth/logout", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


def test_unauthorized_without_token(app_client):
    resp = app_client.get("/sql/tables")
    assert resp.status_code == 401


def test_sql_crud(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}

    resp = app_client.post("/sql/tables", json={
        "name": "products",
        "columns": [
            {"name": "id", "col_type": "INTEGER", "primary_key": True},
            {"name": "name", "col_type": "TEXT"},
        ],
    }, headers=h)
    assert resp.status_code == 200

    resp = app_client.post("/sql/tables/products/insert", json={
        "data": {"id": 1, "name": "Widget"},
    }, headers=h)
    assert resp.status_code == 200

    resp = app_client.get("/sql/tables/products", headers=h)
    assert resp.status_code == 200
    assert resp.json()["row_count"] == 1

    resp = app_client.get("/sql/tables", headers=h)
    assert resp.status_code == 200
    assert "products" in resp.json()["tables"]


def test_document_crud(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}

    resp = app_client.post(
        "/docs/logs", json={"data": {"event": "test", "level": "info"}}, headers=h
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    resp = app_client.get(f"/docs/logs/{doc_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["data"]["event"] == "test"

    resp = app_client.put(
        f"/docs/logs/{doc_id}",
        json={"data": {"level": "warn"}, "merge": True},
        headers=h,
    )
    assert resp.status_code == 200

    resp = app_client.delete(f"/docs/logs/{doc_id}", headers=h)
    assert resp.status_code == 200


def test_document_find_rejects_negative_limit_or_offset(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    for body in ({"limit": -1}, {"offset": -1}):
        resp = app_client.post("/docs/logs/find", json=body, headers=h)
        assert resp.status_code == 422, body


def test_kv_crud(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}

    resp = app_client.put("/kv/config/theme", json={"value": "dark"}, headers=h)
    assert resp.status_code == 200

    resp = app_client.get("/kv/config/theme", headers=h)
    assert resp.status_code == 200
    assert resp.json()["value"] == "dark"

    resp = app_client.delete("/kv/config/theme", headers=h)
    assert resp.status_code == 200


def test_kv_list_keys_prefix_is_literal(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    for key in ["user_1", "userX", "User_2"]:
        resp = app_client.put(f"/kv/{key}", json={"value": 1}, headers=h)
        assert resp.status_code == 200

    resp = app_client.get("/kv/keys", params={"prefix": "user_"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["keys"] == ["user_1"]


def test_kv_get_returns_a_stored_null(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = app_client.put("/kv/flag", json={"value": None}, headers=h)
    assert resp.status_code == 200

    resp = app_client.get("/kv/flag", headers=h)
    assert resp.status_code == 200
    assert resp.json() == {"key": "flag", "value": None}

    assert app_client.get("/kv/missing", headers=h).status_code == 404


def test_kv_ttl_accepts_fractional_seconds(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = app_client.put("/kv/session", json={"value": "s", "ttl": 1.5}, headers=h)
    assert resp.status_code == 200
    assert app_client.get("/kv/session", headers=h).json()["value"] == "s"


def test_kv_ttl_rejects_zero_and_negative(app_client, admin_token):
    # Before, these returned 200 but stored a key that was already expired.
    h = {"Authorization": f"Bearer {admin_token}"}
    for ttl in (0, -1):
        resp = app_client.put("/kv/lost", json={"value": "v", "ttl": ttl}, headers=h)
        assert resp.status_code == 422, ttl
    assert app_client.get("/kv/lost", headers=h).status_code == 404


def test_admin_stats(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = app_client.get("/admin/stats", headers=h)
    assert resp.status_code == 200
    assert "tables" in resp.json()


def test_admin_audit(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = app_client.get("/admin/audit", headers=h)
    assert resp.status_code == 200
    assert "logs" in resp.json()


def test_admin_audit_verify(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = app_client.get("/admin/audit/verify", headers=h)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_ebot_query(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    resp = app_client.post("/ebot/query", json={"text": "list tables"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_graph_crud(app_client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}

    resp = app_client.post(
        "/graph/nodes",
        json={"label": "Person", "properties": {"name": "Alice"}},
        headers=h,
    )
    assert resp.status_code == 201
    node_id = resp.json()["id"]

    resp = app_client.get(f"/graph/nodes/{node_id}", headers=h)
    assert resp.status_code == 200

    resp = app_client.post(
        "/graph/nodes",
        json={"label": "Person", "properties": {"name": "Bob"}},
        headers=h,
    )
    bob_id = resp.json()["id"]

    resp = app_client.post("/graph/edges", json={
        "source_id": node_id, "target_id": bob_id, "relationship": "KNOWS",
    }, headers=h)
    assert resp.status_code == 201

    resp = app_client.get("/graph/stats", headers=h)
    assert resp.json()["node_count"] == 2
    assert resp.json()["edge_count"] == 1


def test_rbac_read_only_cannot_write(app_client, admin_token):
    app_client.post("/auth/register", json={
        "username": "reader", "password": "Reader@12345!", "role": "read_only",
    })
    resp = app_client.post("/auth/login", json={"username": "reader", "password": "Reader@12345!"})
    reader_token = resp.json()["access_token"]
    rh = {"Authorization": f"Bearer {reader_token}"}

    resp = app_client.post("/sql/tables", json={
        "name": "forbidden", "columns": [{"name": "id", "col_type": "INTEGER"}],
    }, headers=rh)
    assert resp.status_code == 403


def test_create_app_uses_the_given_config(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from edb.api.app import create_app
    from edb.config import EDBConfig

    monkeypatch.chdir(tmp_path)
    config = EDBConfig(
        db_path=str(tmp_path / "custom.db"),
        jwt_secret="test-secret-key-minimum-32-bytes-ok!",
    )
    app = create_app(config)

    with TestClient(app):
        assert app.state.edb.config is config

    assert (tmp_path / "custom.db").exists()
    assert not (tmp_path / "edb_data.db").exists()
