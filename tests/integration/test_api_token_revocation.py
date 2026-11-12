"""Integration tests for token revocation: logout and single-use refresh tokens."""

ADMIN = {"username": "admin", "password": "Admin@12345678!"}


def _login(client):
    resp = client.post("/auth/login", json=ADMIN)
    assert resp.status_code == 200
    return resp.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_access_and_refresh_tokens(app_client):
    tokens = _login(app_client)
    resp = app_client.post(
        "/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=_auth(tokens["access_token"]),
    )
    assert resp.status_code == 200

    assert app_client.get("/auth/me", headers=_auth(tokens["access_token"])).status_code == 401
    resp = app_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401


def test_logout_leaves_other_sessions_working(app_client):
    first = _login(app_client)
    second = _login(app_client)

    resp = app_client.post("/auth/logout", headers=_auth(first["access_token"]))
    assert resp.status_code == 200

    assert app_client.get("/auth/me", headers=_auth(second["access_token"])).status_code == 200


def test_refresh_token_is_single_use(app_client):
    tokens = _login(app_client)
    body = {"refresh_token": tokens["refresh_token"]}

    assert app_client.post("/auth/refresh", json=body).status_code == 200
    assert app_client.post("/auth/refresh", json=body).status_code == 401
