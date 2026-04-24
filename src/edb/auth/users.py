"""User management for eDB."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import bcrypt

from edb.auth.models import Role, User, UserCreate, UserResponse
from edb.core.engine import StorageEngine

USERS_TABLE = "_edb_users"
logger = logging.getLogger("edb.auth.users")

MIN_PASSWORD_LENGTH = 12
PASSWORD_POLICY = (
    "Password must be at least 12 characters and contain uppercase, "
    "lowercase, digit, and special character."
)


def validate_password_strength(password: str) -> None:
    """Enforce password complexity requirements."""
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        errors.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("a lowercase letter")
    if not re.search(r"\d", password):
        errors.append("a digit")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_=+\[\]\\;'/`~]", password):
        errors.append("a special character")
    if errors:
        raise ValueError(f"Password too weak — must contain: {', '.join(errors)}")


class UserManager:
    """Manages eDB users: creation, authentication, password hashing."""

    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._engine.execute(f"""
            CREATE TABLE IF NOT EXISTS "{USERS_TABLE}" (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'read_only',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._engine.commit()

    def create_user(self, user_data: UserCreate, skip_password_check: bool = False) -> UserResponse:
        """Create a new user with hashed password."""
        if self.get_by_username(user_data.username):
            raise ValueError(f"Username '{user_data.username}' already exists")

        if not skip_password_check:
            validate_password_strength(user_data.password)

        user_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        password_hash = self._hash_password(user_data.password)

        self._engine.execute(
            f"""INSERT INTO "{USERS_TABLE}"
            (id, username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (user_id, user_data.username, password_hash, user_data.role.value, now, now),
        )
        self._engine.commit()

        return UserResponse(
            id=user_id,
            username=user_data.username,
            role=user_data.role,
            is_active=True,
            created_at=datetime.fromisoformat(now),
        )

    def authenticate(self, username: str, password: str) -> User | None:
        """Authenticate a user by username and password."""
        user = self.get_by_username(username)
        if user is None or not user.is_active:
            return None
        if not self._verify_password(password, user.password_hash):
            return None
        return user

    def get_by_id(self, user_id: str) -> User | None:
        """Get a user by ID."""
        row = self._engine.fetchone(
            f'SELECT * FROM "{USERS_TABLE}" WHERE id = ?', (user_id,)
        )
        return self._row_to_user(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        """Get a user by username."""
        row = self._engine.fetchone(
            f'SELECT * FROM "{USERS_TABLE}" WHERE username = ?', (username,)
        )
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[UserResponse]:
        """List all users (without passwords)."""
        rows = self._engine.fetchall(f'SELECT * FROM "{USERS_TABLE}" ORDER BY created_at')
        return [
            UserResponse(
                id=row["id"],
                username=row["username"],
                role=Role(row["role"]),
                is_active=bool(row["is_active"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def update_role(self, user_id: str, role: Role) -> bool:
        """Update a user's role."""
        now = datetime.now(UTC).isoformat()
        cursor = self._engine.execute(
            f'UPDATE "{USERS_TABLE}" SET role = ?, updated_at = ? WHERE id = ?',
            (role.value, now, user_id),
        )
        self._engine.commit()
        return cursor.rowcount > 0

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user account."""
        now = datetime.now(UTC).isoformat()
        cursor = self._engine.execute(
            f'UPDATE "{USERS_TABLE}" SET is_active = 0, updated_at = ? WHERE id = ?',
            (now, user_id),
        )
        self._engine.commit()
        return cursor.rowcount > 0

    def ensure_admin_exists(self, username: str, password: str) -> None:
        """Create an admin user with the provided credentials if no admins exist."""
        validate_password_strength(password)
        row = self._engine.fetchone(
            f'SELECT id FROM "{USERS_TABLE}" WHERE role = ?', (Role.ADMIN.value,)
        )
        if row is None:
            self.create_user(
                UserCreate(username=username, password=password, role=Role.ADMIN),
                skip_password_check=True,
            )
            logger.info("Admin user '%s' created.", username)
        else:
            logger.info("Admin user already exists, skipping creation.")

    def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """Change a user password after verifying the current one."""
        user = self.get_by_id(user_id)
        if user is None:
            return False
        if not self._verify_password(current_password, user.password_hash):
            return False
        validate_password_strength(new_password)
        new_hash = self._hash_password(new_password)
        now = datetime.now(UTC).isoformat()
        cursor = self._engine.execute(
            f'UPDATE "{USERS_TABLE}" SET password_hash = ?, updated_at = ? WHERE id = ?',
            (new_hash, now, user_id),
        )
        self._engine.commit()
        return cursor.rowcount > 0

    def _hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    def _row_to_user(self, row: Any) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            role=Role(row["role"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
