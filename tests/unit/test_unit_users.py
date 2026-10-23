# SPDX-License-Identifier: MIT
"""Unit tests for the user manager (issue #88 coverage drive).

Covers edb/auth/users.py — measured at 61.79% by the unit suite
before this file: password-strength policy, user creation
(duplicate / weak-password / skip-check paths), authentication
(success, unknown, wrong password, deactivated), lookups, listing,
role updates, deactivation, the ensure-admin bootstrap (both
branches), and password changes.
"""

import pytest

from edb.auth.models import Role, UserCreate
from edb.auth.users import MIN_PASSWORD_LENGTH, UserManager, validate_password_strength
from edb.core.engine import StorageEngine

STRONG = "Str0ng!Passw0rd"
STRONG2 = "An0ther!Str0ng"


def make_manager() -> UserManager:
    return UserManager(StorageEngine(":memory:"))


def make_user(manager: UserManager, username: str = "alice", password: str = STRONG, **kw):
    return manager.create_user(UserCreate(username=username, password=password, **kw))


class TestValidatePasswordStrength:
    def test_strong_password_passes(self):
        validate_password_strength(STRONG)

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="at least"):
            validate_password_strength("Aa1!short")

    def test_missing_uppercase_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_password_strength("str0ng!passw0rd")

    def test_missing_lowercase_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_password_strength("STR0NG!PASSW0RD")

    def test_missing_digit_raises(self):
        with pytest.raises(ValueError, match="digit"):
            validate_password_strength("Strong!Password")

    def test_missing_special_raises(self):
        with pytest.raises(ValueError, match="special"):
            validate_password_strength("Str0ngPassw0rdX")

    def test_multiple_weaknesses_are_all_named(self):
        with pytest.raises(ValueError) as excinfo:
            validate_password_strength("weak")
        message = str(excinfo.value)
        assert "uppercase" in message
        assert "digit" in message
        assert "special" in message
        assert str(MIN_PASSWORD_LENGTH) in message


class TestCreateUser:
    def test_create_returns_response_and_persists(self):
        manager = make_manager()
        resp = make_user(manager, role=Role.READ_WRITE)
        assert resp.username == "alice"
        assert resp.role is Role.READ_WRITE
        assert resp.is_active is True
        assert resp.id
        stored = manager.get_by_username("alice")
        assert stored is not None
        assert stored.id == resp.id
        assert stored.password_hash != STRONG
        assert stored.password_hash.startswith("$2")

    def test_default_role_is_read_only(self):
        manager = make_manager()
        assert make_user(manager).role is Role.READ_ONLY

    def test_duplicate_username_raises(self):
        manager = make_manager()
        make_user(manager)
        with pytest.raises(ValueError, match="already exists"):
            make_user(manager)

    def test_weak_password_rejected(self):
        manager = make_manager()
        with pytest.raises(ValueError, match="too weak"):
            make_user(manager, password="weakpass")

    def test_skip_password_check_allows_weak_password(self):
        manager = make_manager()
        resp = manager.create_user(
            UserCreate(username="bob", password="weakpass"), skip_password_check=True
        )
        assert resp.username == "bob"
        assert manager.authenticate("bob", "weakpass") is not None


class TestAuthenticate:
    def test_success_returns_user(self):
        manager = make_manager()
        make_user(manager)
        user = manager.authenticate("alice", STRONG)
        assert user is not None
        assert user.username == "alice"

    def test_unknown_user_returns_none(self):
        assert make_manager().authenticate("ghost", STRONG) is None

    def test_wrong_password_returns_none(self):
        manager = make_manager()
        make_user(manager)
        assert manager.authenticate("alice", STRONG2) is None

    def test_deactivated_user_returns_none(self):
        manager = make_manager()
        resp = make_user(manager)
        assert manager.deactivate_user(resp.id) is True
        assert manager.authenticate("alice", STRONG) is None


class TestLookupsAndList:
    def test_get_by_id_found_and_missing(self):
        manager = make_manager()
        resp = make_user(manager)
        found = manager.get_by_id(resp.id)
        assert found is not None
        assert found.username == "alice"
        assert manager.get_by_id("no-such-id") is None

    def test_get_by_username_missing(self):
        assert make_manager().get_by_username("ghost") is None

    def test_list_users_empty_then_populated(self):
        manager = make_manager()
        assert manager.list_users() == []
        make_user(manager, "alice")
        make_user(manager, "bob")
        users = manager.list_users()
        assert [u.username for u in users] == ["alice", "bob"]
        assert all(not hasattr(u, "password_hash") for u in users)


class TestUpdateRoleAndDeactivate:
    def test_update_role_existing(self):
        manager = make_manager()
        resp = make_user(manager)
        assert manager.update_role(resp.id, Role.ADMIN) is True
        stored = manager.get_by_id(resp.id)
        assert stored is not None
        assert stored.role is Role.ADMIN

    def test_update_role_missing_returns_false(self):
        assert make_manager().update_role("no-such-id", Role.ADMIN) is False

    def test_deactivate_missing_returns_false(self):
        assert make_manager().deactivate_user("no-such-id") is False


class TestEnsureAdminExists:
    def test_creates_admin_when_none_exist(self):
        manager = make_manager()
        manager.ensure_admin_exists("root", STRONG)
        admin = manager.get_by_username("root")
        assert admin is not None
        assert admin.role is Role.ADMIN
        assert manager.authenticate("root", STRONG) is not None

    def test_second_call_does_not_create_another_admin(self):
        manager = make_manager()
        manager.ensure_admin_exists("root", STRONG)
        manager.ensure_admin_exists("other", STRONG2)
        assert manager.get_by_username("other") is None
        assert len(manager.list_users()) == 1

    def test_weak_admin_password_rejected(self):
        manager = make_manager()
        with pytest.raises(ValueError, match="too weak"):
            manager.ensure_admin_exists("root", "weakpass")
        assert manager.list_users() == []


class TestChangePassword:
    def test_unknown_user_returns_false(self):
        assert make_manager().change_password("no-such-id", STRONG, STRONG2) is False

    def test_wrong_current_password_returns_false(self):
        manager = make_manager()
        resp = make_user(manager)
        assert manager.change_password(resp.id, STRONG2, "N3w!Str0ngPass") is False

    def test_weak_new_password_raises(self):
        manager = make_manager()
        resp = make_user(manager)
        with pytest.raises(ValueError, match="too weak"):
            manager.change_password(resp.id, STRONG, "weakpass")

    def test_success_rotates_the_password(self):
        manager = make_manager()
        resp = make_user(manager)
        assert manager.change_password(resp.id, STRONG, STRONG2) is True
        assert manager.authenticate("alice", STRONG) is None
        assert manager.authenticate("alice", STRONG2) is not None


class TestHashing:
    def test_hash_verify_round_trip(self):
        manager = make_manager()
        digest = manager._hash_password(STRONG)
        assert manager._verify_password(STRONG, digest) is True
        assert manager._verify_password(STRONG2, digest) is False

    def test_same_password_hashes_differently_each_time(self):
        manager = make_manager()
        assert manager._hash_password(STRONG) != manager._hash_password(STRONG)
