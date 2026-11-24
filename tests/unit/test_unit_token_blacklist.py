# SPDX-License-Identifier: MIT
"""Unit tests for JWT token revocation (issue #99 coverage drive).

Covers edb/auth/token_blacklist.py — previously 0% covered — using an
in-memory StorageEngine: revoke, is_revoked, revoke_all_for_user and
cleanup_expired.
"""

from datetime import UTC, datetime, timedelta

from edb.auth.token_blacklist import BLACKLIST_TABLE, TokenBlacklist
from edb.core.engine import StorageEngine


def make_blacklist() -> TokenBlacklist:
    return TokenBlacklist(StorageEngine(":memory:"))


class TestRevokeAndCheck:
    def test_revoke_marks_token_revoked(self):
        bl = make_blacklist()
        bl.revoke("jti-abc", user_id="u1")
        assert bl.is_revoked("jti-abc") is True

    def test_unknown_token_not_revoked(self):
        bl = make_blacklist()
        assert bl.is_revoked("jti-never-seen") is False

    def test_revoke_is_idempotent(self):
        bl = make_blacklist()
        bl.revoke("jti-dup", user_id="u1")
        bl.revoke("jti-dup", user_id="u1")
        assert bl.is_revoked("jti-dup") is True

    def test_revoke_stores_metadata(self):
        engine = StorageEngine(":memory:")
        bl = TokenBlacklist(engine)
        bl.revoke("jti-meta", user_id="u9", expires_at="2999-01-01T00:00:00+00:00")
        row = engine.fetchone(
            f'SELECT user_id, expires_at FROM "{BLACKLIST_TABLE}" WHERE token_jti = ?',
            ("jti-meta",),
        )
        assert row is not None
        assert row["user_id"] == "u9"
        assert row["expires_at"] == "2999-01-01T00:00:00+00:00"

    def test_revoke_without_user_id(self):
        bl = make_blacklist()
        bl.revoke("jti-anon")
        assert bl.is_revoked("jti-anon") is True


class TestRevokeAllForUser:
    def test_revoke_all_for_user_returns_count(self):
        bl = make_blacklist()
        count = bl.revoke_all_for_user("u1")
        assert count >= 1


class TestIsRevokedForUser:
    @staticmethod
    def revoke_all(engine: StorageEngine, bl: TokenBlacklist, user_id: str) -> int:
        """Call revoke_all_for_user() and return the second it was recorded in."""
        bl.revoke_all_for_user(user_id)
        row = engine.fetchone(
            f'SELECT revoked_at FROM "{BLACKLIST_TABLE}" WHERE user_id = ?', (user_id,)
        )
        assert row is not None
        return int(datetime.fromisoformat(row["revoked_at"]).timestamp())

    def test_tokens_issued_before_the_cutoff_are_revoked(self):
        engine = StorageEngine(":memory:")
        bl = TokenBlacklist(engine)
        cutoff = self.revoke_all(engine, bl, "u1")
        assert bl.is_revoked_for_user("u1", cutoff - 1) is True

    def test_tokens_issued_in_or_after_the_cutoff_second_are_kept(self):
        engine = StorageEngine(":memory:")
        bl = TokenBlacklist(engine)
        cutoff = self.revoke_all(engine, bl, "u1")
        assert bl.is_revoked_for_user("u1", cutoff) is False
        assert bl.is_revoked_for_user("u1", cutoff + 1) is False

    def test_only_the_named_user_is_affected(self):
        engine = StorageEngine(":memory:")
        bl = TokenBlacklist(engine)
        cutoff = self.revoke_all(engine, bl, "u1")
        assert bl.is_revoked_for_user("u2", cutoff - 1) is False

    def test_revoking_one_token_is_not_a_cutoff(self):
        bl = make_blacklist()
        bl.revoke("jti-one", user_id="u1")
        assert bl.is_revoked_for_user("u1", 0) is False


class TestCleanupExpired:
    def test_cleanup_removes_only_expired(self):
        bl = make_blacklist()
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        bl.revoke("jti-old", expires_at=past)
        bl.revoke("jti-new", expires_at=future)
        bl.revoke("jti-forever")  # no expiry -> never cleaned
        removed = bl.cleanup_expired()
        assert removed == 1
        assert bl.is_revoked("jti-old") is False
        assert bl.is_revoked("jti-new") is True
        assert bl.is_revoked("jti-forever") is True

    def test_cleanup_with_nothing_expired(self):
        bl = make_blacklist()
        assert bl.cleanup_expired() == 0
