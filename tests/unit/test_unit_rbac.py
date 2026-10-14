# SPDX-License-Identifier: MIT
"""Unit tests for role-based access control (issue #88 coverage drive).

Covers edb/auth/rbac.py — previously without a dedicated test module —
pinning the ROLE_PERMISSIONS matrix from edb/auth/models.py, the
string-role resolution path, custom roles, and the
PermissionDeniedError contract of check_permission.
"""

import pytest

from edb.auth.models import ROLE_PERMISSIONS, Permission, Role
from edb.auth.rbac import PermissionDeniedError, RBACManager


@pytest.fixture
def rbac() -> RBACManager:
    return RBACManager()


class TestBuiltinMatrix:
    def test_admin_has_every_permission(self, rbac):
        for permission in Permission:
            assert rbac.has_permission(Role.ADMIN, permission) is True

    def test_read_write_matrix(self, rbac):
        granted = {
            Permission.DB_READ,
            Permission.DB_WRITE,
            Permission.DB_DELETE,
            Permission.DB_CREATE_TABLE,
            Permission.EBOT_QUERY,
        }
        for permission in Permission:
            assert rbac.has_permission(Role.READ_WRITE, permission) is (
                permission in granted
            )

    def test_read_only_matrix(self, rbac):
        assert rbac.has_permission(Role.READ_ONLY, Permission.DB_READ) is True
        assert rbac.has_permission(Role.READ_ONLY, Permission.EBOT_QUERY) is True
        for permission in (
            Permission.DB_WRITE,
            Permission.DB_DELETE,
            Permission.DB_CREATE_TABLE,
            Permission.DB_DROP_TABLE,
            Permission.ADMIN_USERS,
        ):
            assert rbac.has_permission(Role.READ_ONLY, permission) is False

    def test_get_permissions_matches_the_matrix(self, rbac):
        for role, expected in ROLE_PERMISSIONS.items():
            assert rbac.get_permissions(role) == expected


class TestStringRoles:
    def test_builtin_names_resolve_from_strings(self, rbac):
        assert rbac.has_permission("admin", Permission.ADMIN_ROLES) is True
        assert rbac.has_permission("read_only", Permission.DB_WRITE) is False
        assert rbac.get_permissions("read_write") == ROLE_PERMISSIONS[Role.READ_WRITE]

    def test_unknown_string_role_has_nothing(self, rbac):
        assert rbac.has_permission("no-such-role", Permission.DB_READ) is False
        assert rbac.get_permissions("no-such-role") == set()


class TestCustomRoles:
    def test_custom_role_grants_and_denies(self, rbac):
        rbac.create_custom_role("auditor", {Permission.DB_READ, Permission.ADMIN_AUDIT})
        assert rbac.has_permission("auditor", Permission.DB_READ) is True
        assert rbac.has_permission("auditor", Permission.ADMIN_AUDIT) is True
        assert rbac.has_permission("auditor", Permission.DB_WRITE) is False
        assert rbac.get_permissions("auditor") == {
            Permission.DB_READ,
            Permission.ADMIN_AUDIT,
        }

    def test_custom_role_named_like_a_builtin_is_shadowed(self, rbac):
        # Role("admin") parses before the custom-role lookup, so a
        # custom "admin" can never narrow the builtin admin.
        rbac.create_custom_role("admin", set())
        assert rbac.has_permission("admin", Permission.ADMIN_USERS) is True


class TestCheckPermission:
    def test_allowed_check_is_silent(self, rbac):
        rbac.check_permission(Role.READ_ONLY, Permission.DB_READ)

    def test_denied_check_raises_with_context(self, rbac):
        with pytest.raises(PermissionDeniedError) as excinfo:
            rbac.check_permission(Role.READ_ONLY, Permission.DB_DROP_TABLE)
        message = str(excinfo.value)
        assert "read_only" in message
        assert Permission.DB_DROP_TABLE.value in message


class TestConvenienceChecks:
    def test_can_read_write_delete(self, rbac):
        assert rbac.can_read(Role.READ_ONLY) is True
        assert rbac.can_write(Role.READ_ONLY) is False
        assert rbac.can_delete(Role.READ_ONLY) is False
        assert rbac.can_write(Role.READ_WRITE) is True
        assert rbac.can_delete(Role.READ_WRITE) is True

    def test_is_admin(self, rbac):
        assert rbac.is_admin(Role.ADMIN) is True
        assert rbac.is_admin("admin") is True
        assert rbac.is_admin(Role.READ_WRITE) is False
