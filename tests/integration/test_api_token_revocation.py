"""Integration tests for token revocation: logout, single-use refresh tokens and
password changes."""

from datetime import datetime, timedelta

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


NEW_PASSWORD = "Admin@NewPass9876!"


class _FiveSecondsAgo(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.now(tz) - timedelta(seconds=5)


def _login_earlier(client, monkeypatch):
    """Log in with tokens issued 5 seconds ago.

    A token issued in the same second as a password change is kept (iat has
    whole-second precision), so the sessions that must be cut off are issued
    earlier on purpose; otherwise these tests would depend on timing.
    """
    with monkeypatch.context() as m:
        m.setattr("edb.auth.jwt_handler.datetime", _FiveSecondsAgo)
        return _login(client)


def _change_password(client, tokens, current_password):
    body = {"current_password": current_password, "new_password": NEW_PASSWORD}
    return client.post("/auth/password", json=body, headers=_auth(tokens["access_token"]))


def test_password_change_signs_out_every_existing_session(app_client, monkeypatch):
    other = _login_earlier(app_client, monkeypatch)
    own = _login_earlier(app_client, monkeypatch)

    assert _change_password(app_client, own, ADMIN["password"]).status_code == 200

    for tokens in (other, own):
        assert app_client.get("/auth/me", headers=_auth(tokens["access_token"])).status_code == 401
        resp = app_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 401


def test_login_after_a_password_change_works(app_client, monkeypatch):
    old = _login_earlier(app_client, monkeypatch)
    assert _change_password(app_client, old, ADMIN["password"]).status_code == 200

    resp = app_client.post("/auth/login", json={"username": "admin", "password": NEW_PASSWORD})
    assert resp.status_code == 200
    fresh = resp.json()
    assert app_client.get("/auth/me", headers=_auth(fresh["access_token"])).status_code == 200
    body = {"refresh_token": fresh["refresh_token"]}
    assert app_client.post("/auth/refresh", json=body).status_code == 200


def test_failed_password_change_signs_nobody_out(app_client, monkeypatch):
    tokens = _login_earlier(app_client, monkeypatch)
    assert _change_password(app_client, tokens, "wrong-password").status_code == 400
    assert app_client.get("/auth/me", headers=_auth(tokens["access_token"])).status_code == 200
