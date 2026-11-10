"""Prompt sanitizer for ebot queries.

Validates translated queries and detects prompt injection attempts.
"""

from __future__ import annotations

from edb.auth.models import Permission
from edb.auth.rbac import RBACManager
from edb.ebot.models import TranslationResult
from edb.ebot.translator import LIST_TABLES_SQL
from edb.security.input_validation import InputValidator

# The permission each translated action needs. An action missing from this map
# is denied (deny by default), so a new action has to be added deliberately.
_ACTION_PERMISSIONS: dict[str, Permission] = {
    "select": Permission.DB_READ,
    "find": Permission.DB_READ,
    "find_by_id": Permission.DB_READ,
    "count": Permission.DB_READ,
    "get": Permission.DB_READ,
    "list": Permission.DB_READ,
    "exists": Permission.DB_READ,
    "list_collections": Permission.DB_READ,
    "raw": Permission.DB_READ,
    "insert": Permission.DB_WRITE,
    "update": Permission.DB_WRITE,
    "set": Permission.DB_WRITE,
    "delete": Permission.DB_DELETE,
    "create_table": Permission.DB_CREATE_TABLE,
    "drop_table": Permission.DB_DROP_TABLE,
}


class PromptSanitizer:
    """Sanitizes and validates ebot natural language queries and their translations."""

    def __init__(self) -> None:
        self._validator = InputValidator()
        self._rbac = RBACManager()

    def sanitize_input(self, text: str) -> tuple[str, list[str]]:
        """Sanitize user input text.

        Returns (sanitized_text, warnings).
        """
        warnings: list[str] = []

        if self._validator.check_prompt_injection(text):
            warnings.append("Potential prompt injection detected")

        if self._validator.check_sql_injection(text):
            warnings.append("Potential SQL injection in natural language query")

        sanitized = self._validator.sanitize_string(text, max_length=2000)
        return sanitized, warnings

    def validate_translation(
        self, result: TranslationResult, user_role: str = "read_only"
    ) -> TranslationResult:
        """Validate a translated query before execution.

        Checks for injection and enforces role-based restrictions.
        """
        if result.error or result.translated_query is None:
            return result

        query = result.translated_query
        warnings = self._validator.validate_query_input(query)
        if warnings:
            return TranslationResult(
                original_text=result.original_text,
                error=f"Unsafe translated query: {'; '.join(warnings)}",
            )

        # Internal tables (_edb_users, _edb_audit_log, ...) start with "_" and
        # are never reachable from eBot, matching RelationalStore.list_tables().
        for field in ("table", "collection"):
            name = query.get(field)
            if name and (not self._validator.validate_table_name(name) or name.startswith("_")):
                return TranslationResult(
                    original_text=result.original_text,
                    error=f"Invalid or reserved name: '{name}'",
                )

        action = query.get("action", "")
        if action == "raw" and query.get("raw_sql") != LIST_TABLES_SQL:
            return TranslationResult(
                original_text=result.original_text,
                error="Raw SQL is not allowed via eBot; use POST /sql/execute",
            )

        permission = _ACTION_PERMISSIONS.get(action)
        if permission is None or not self._rbac.has_permission(user_role, permission):
            return TranslationResult(
                original_text=result.original_text,
                error=f"Permission denied: role '{user_role}' cannot '{action}'",
            )

        return result
