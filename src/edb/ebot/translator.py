"""Natural language to query translation for ebot.

Uses a rule-based approach by default, with an optional LLM backend.
"""

from __future__ import annotations

import re
from typing import Any

from edb.ebot.models import TranslationResult

# The only raw SQL eBot ever emits ("list tables"). Internal "_" tables are
# hidden, as in RelationalStore.list_tables(); the sanitizer rejects any other
# raw SQL.
LIST_TABLES_SQL = (
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
)

# Quote characters a value may be wrapped in ("get key 'a b'").
_VALUE_QUOTES = "'\""


def _extract_value(raw: str) -> str | None:
    """Trim a captured trailing value: surrounding whitespace, then one quote.

    The patterns below used to end in ``['\"]?(.+?)['\"]?\\s*$``. That tail is
    ambiguous: the lazy ``.+?`` also matches whitespace, so it overlaps the
    neighbouring ``\\s*``/``\\s+``. On input such as ``find a where b=`` plus a
    long run of spaces the engine retried every split of that run, which is
    quadratic in its length (CodeQL ``py/polynomial-redos``).

    The patterns now capture the rest of the line with a single unambiguous
    ``(.*)$`` group and the trimming happens here, in linear time. ``None``
    means "no usable value", and the caller falls through to the next rule
    exactly as a failed regex match used to.
    """
    value = raw.strip()
    # ``len(value) > 1`` mirrors the old ``.+?``, which always kept at least
    # one character and so never consumed a lone quote as a delimiter.
    if len(value) > 1 and value[0] in _VALUE_QUOTES:
        value = value[1:]
    if len(value) > 1 and value[-1] in _VALUE_QUOTES:
        value = value[:-1]
    return value or None


class NLQueryTranslator:
    """Translates natural language queries into eDB query DSL."""

    def __init__(self, provider: str = "rule_based", **kwargs: Any) -> None:
        self._provider = provider
        self._kwargs = kwargs

    def translate(self, text: str, context: dict[str, Any] | None = None) -> TranslationResult:
        """Translate a natural language query to eDB query DSL."""
        text = text.strip()
        if not text:
            return TranslationResult(original_text=text, error="Empty query")

        if self._provider == "rule_based":
            return self._rule_based_translate(text, context)
        else:
            return TranslationResult(
                original_text=text,
                error=f"Provider '{self._provider}' not available. Use 'rule_based'.",
            )

    def _rule_based_translate(
        self, text: str, context: dict[str, Any] | None = None
    ) -> TranslationResult:
        """Rule-based translation using regex patterns.

        Keywords match case-insensitively, but names, keys and values are
        taken from the original text: collection names, KV keys and stored
        values are case-sensitive, so lowercasing them changed the query.
        """
        text_lower = text.lower().strip()

        # "list tables/collections/keys" → metadata queries (must be checked before generic pattern)
        if "list tables" in text_lower or "show tables" in text_lower:
            return TranslationResult(
                original_text=text,
                translated_query={
                    "type": "sql",
                    "action": "raw",
                    "raw_sql": LIST_TABLES_SQL,
                },
                confidence=0.9,
                explanation="List all tables",
            )

        if "list collections" in text_lower:
            return TranslationResult(
                original_text=text,
                translated_query={
                    "type": "document",
                    "action": "list_collections",
                    "collection": "",
                },
                confidence=0.9,
                explanation="List all document collections",
            )

        if "list keys" in text_lower:
            return TranslationResult(
                original_text=text,
                translated_query={"type": "kv", "action": "list"},
                confidence=0.9,
                explanation="List all keys",
            )

        # "find <collection> where <key>=<value>" → DOCUMENT FIND
        # (checked before the generic SELECT arm below, which would
        # otherwise swallow "find <collection>" and drop the filter)
        # The value is captured in one greedy, unambiguous `(.*)$` group and
        # trimmed by _extract_value(); `.` still excludes newlines, so a value
        # may not span lines, as before.
        match = re.match(
            r"find\s+(?:in\s+)?(\w+)\s+where\s+(\w+)\s*=(.*)$",
            text,
            re.IGNORECASE,
        )
        if match:
            value = _extract_value(match.group(3))
            if value is not None:
                collection = match.group(1)
                key = match.group(2)
                return TranslationResult(
                    original_text=text,
                    translated_query={
                        "type": "document",
                        "action": "find",
                        "collection": collection,
                        "filter": {key: value},
                    },
                    confidence=0.6,
                    explanation=f"Find in '{collection}' where {key}={value}",
                )

        # "get key <key>" → KV GET
        # (checked before the generic SELECT arm; the "key" keyword is
        # required so plain "get <table>" keeps its SELECT meaning)
        # A single mandatory `\s` separates "key" from the captured remainder,
        # so no two whitespace quantifiers sit next to each other; any extra
        # leading whitespace is trimmed by _extract_value().
        match = re.match(r"get\s+key\s(.*)$", text, re.IGNORECASE)
        if match:
            key = _extract_value(match.group(1))
            if key is not None:
                return TranslationResult(
                    original_text=text,
                    translated_query={
                        "type": "kv",
                        "action": "get",
                        "key": key,
                    },
                    confidence=0.5,
                    explanation=f"GET key '{key}'",
                )

        # "show all/list <table>" → SELECT
        match = re.match(
            r"(?:show|list|get|display|find)\s+(?:all\s+)?(?:from\s+)?(\w+)",
            text,
            re.IGNORECASE,
        )
        if match:
            table = match.group(1)
            return TranslationResult(
                original_text=text,
                translated_query={
                    "type": "sql",
                    "action": "select",
                    "table": table,
                },
                confidence=0.7,
                explanation=f"SELECT all from '{table}'",
            )

        # "count <collection/table>" → COUNT
        match = re.match(r"(?:count|how many)\s+(\w+)", text, re.IGNORECASE)
        if match:
            target = match.group(1)
            return TranslationResult(
                original_text=text,
                translated_query={
                    "type": "document",
                    "action": "count",
                    "collection": target,
                },
                confidence=0.6,
                explanation=f"Count documents in '{target}'",
            )

        # "insert/add <data> into <table>" → INSERT
        # `(\S(?:.*?\S)?)` pins the data to start and end on a non-space, so it
        # can no longer overlap the surrounding `\s+` separators the way the old
        # `(.+?)` did. The lazy `.*?` is bounded by a `\S` on both sides, so the
        # split point is unambiguous. A whitespace-only capture was the only
        # thing this excludes, and _parse_simple_data() rejected that anyway.
        match = re.match(
            r"(?:insert|add|create)\s+(\S(?:.*?\S)?)\s+(?:into|to|in)\s+(\w+)",
            text,
            re.IGNORECASE,
        )
        if match:
            data_str = match.group(1)
            table = match.group(2)
            data = self._parse_simple_data(data_str)
            if data:
                return TranslationResult(
                    original_text=text,
                    translated_query={
                        "type": "sql",
                        "action": "insert",
                        "table": table,
                        "data": data,
                    },
                    confidence=0.5,
                    explanation=f"INSERT into '{table}'",
                )

        # "delete from <table> where <key>=<value>" → DELETE
        # Same unambiguous `(.*)$` + _extract_value() shape as the find arm.
        match = re.match(
            r"(?:delete|remove)\s+(?:from\s+)?(\w+)\s+where\s+(\w+)\s*=(.*)$",
            text,
            re.IGNORECASE,
        )
        if match:
            value = _extract_value(match.group(3))
            if value is not None:
                table = match.group(1)
                key = match.group(2)
                return TranslationResult(
                    original_text=text,
                    translated_query={
                        "type": "sql",
                        "action": "delete",
                        "table": table,
                        "where": {key: value},
                    },
                    confidence=0.6,
                    explanation=f"DELETE from '{table}' where {key}={value}",
                )

        # "list tables/collections/keys" → metadata queries
        # (already handled at the top of the method; this is unreachable)

        return TranslationResult(
            original_text=text,
            error=(
                "Could not understand the query. Try:"
                " 'show all users', 'count orders', 'list tables'"
            ),
        )

    def _parse_simple_data(self, data_str: str) -> dict[str, str] | None:
        """Parse simple key=value pairs from a string."""
        pairs = re.findall(r"(\w+)\s*=\s*['\"]?([^,'\"\s]+)['\"]?", data_str)
        if pairs:
            return dict(pairs)
        return None
