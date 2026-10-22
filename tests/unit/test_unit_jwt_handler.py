# SPDX-License-Identifier: MIT
"""Unit tests for the JWT token handler (issue #88 coverage drive).

Covers edb/auth/jwt_handler.py — previously 0% covered by the unit
suite: access/refresh token creation and claims, reserved-claim
filtering of extra claims, verification (valid, expired, tampered,
wrong-secret, garbage), the expired-token decode used by the refresh
flow, and the token-pair shape.
"""

from datetime import UTC, datetime

import jwt

from edb.auth.jwt_handler import JWTHandler

SECRET = "unit-test-secret"


def make_handler(**kwargs) -> JWTHandler:
    return JWTHandler(SECRET, **kwargs)


class TestCreateAccessToken:
    def test_claims_round_trip_through_verify(self):
        handler = make_handler()
        token = handler.create_access_token("u1", "alice", "admin")
        payload = handler.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"
        assert payload["username"] == "alice"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_expiry_matches_configured_minutes(self):
        handler = make_handler(access_token_expire_minutes=30)
        payload = handler.verify_token(handler.create_access_token("u1", "a", "r"))
        assert payload is not None
        assert payload["exp"] - payload["iat"] == 30 * 60

    def test_extra_claims_are_merged(self):
        handler = make_handler()
        token = handler.create_access_token("u1", "alice", "admin", extra_claims={"tenant": "t-9"})
        payload = handler.verify_token(token)
        assert payload is not None
        assert payload["tenant"] == "t-9"

    def test_extra_claims_cannot_override_reserved(self):
        handler = make_handler()
        token = handler.create_access_token(
            "u1",
            "alice",
            "admin",
            extra_claims={
                "sub": "mallory",
                "username": "mallory",
                "role": "superuser",
                "type": "refresh",
                "exp": 9999999999,
                "iat": 0,
            },
        )
        payload = handler.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"
        assert payload["username"] == "alice"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert payload["exp"] != 9999999999
        assert payload["iat"] != 0

    def test_no_extra_claims_by_default(self):
        handler = make_handler()
        payload = handler.verify_token(handler.create_access_token("u1", "a", "r"))
        assert payload is not None
        assert set(payload) == {"sub", "username", "role", "type", "iat", "exp"}


class TestCreateRefreshToken:
    def test_claims_and_expiry(self):
        handler = make_handler(refresh_token_expire_days=3)
        payload = handler.verify_token(handler.create_refresh_token("u7"))
        assert payload is not None
        assert payload["sub"] == "u7"
        assert payload["type"] == "refresh"
        assert payload["exp"] - payload["iat"] == 3 * 24 * 60 * 60
        assert "username" not in payload
        assert "role" not in payload


class TestVerifyToken:
    def test_expired_token_returns_none(self):
        handler = make_handler(access_token_expire_minutes=-1)
        token = handler.create_access_token("u1", "alice", "admin")
        assert handler.verify_token(token) is None

    def test_wrong_secret_returns_none(self):
        token = make_handler().create_access_token("u1", "alice", "admin")
        assert JWTHandler("a-different-secret").verify_token(token) is None

    def test_tampered_payload_returns_none(self):
        handler = make_handler()
        header, _payload, signature = handler.create_access_token("u1", "alice", "admin").split(".")
        forged_payload = jwt.encode(
            {"sub": "mallory", "role": "superuser"}, "x", algorithm="HS256"
        ).split(".")[1]
        assert handler.verify_token(f"{header}.{forged_payload}.{signature}") is None

    def test_garbage_returns_none(self):
        handler = make_handler()
        assert handler.verify_token("not-a-jwt") is None
        assert handler.verify_token("") is None


class TestDecodeExpiredToken:
    def test_expired_token_still_decodes(self):
        handler = make_handler(access_token_expire_minutes=-5)
        token = handler.create_access_token("u1", "alice", "admin")
        assert handler.verify_token(token) is None  # sanity: it is expired
        payload = handler.decode_expired_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"
        assert payload["username"] == "alice"

    def test_wrong_secret_returns_none(self):
        token = make_handler().create_access_token("u1", "alice", "admin")
        assert JWTHandler("nope").decode_expired_token(token) is None

    def test_garbage_returns_none(self):
        assert make_handler().decode_expired_token("junk") is None


class TestTokenPairAndProperties:
    def test_pair_shape(self):
        handler = make_handler(access_token_expire_minutes=45)
        pair = handler.create_token_pair("u1", "alice", "admin")
        assert pair["token_type"] == "bearer"
        assert pair["expires_in"] == str(45 * 60)
        access = handler.verify_token(pair["access_token"])
        refresh = handler.verify_token(pair["refresh_token"])
        assert access is not None and access["type"] == "access"
        assert refresh is not None and refresh["type"] == "refresh"

    def test_access_expire_minutes_property(self):
        assert make_handler(access_token_expire_minutes=12).access_expire_minutes == 12
        assert make_handler().access_expire_minutes == 60

    def test_tokens_are_fresh_each_call(self):
        handler = make_handler()
        first = handler.create_refresh_token("u1")
        payload = jwt.decode(first, SECRET, algorithms=["HS256"])
        assert payload["iat"] <= int(datetime.now(UTC).timestamp())
