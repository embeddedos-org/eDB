"""Natural language to query translation for ebot.

Uses a rule-based approach by default, with an optional LLM backend.
"""

from __future__ import annotations

import re
from typing import Any

from edb.ebot.models import TranslationResult

# The only raw SQL eBot ever emits ("list tables"). Internal "_" and "sqlite_"
# tables are hidden, as in RelationalStore.list_tables(); the sanitizer rejects
# any other raw SQL.
LIST_TABLES_SQL = (
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
    " AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
)

# Quote characters a value may be wrapped in ("get key 'a b'").
_VALUE_QUOTES = "'\""

# Rule patterns.
#
# Each one stops at the last character the rule structurally requires -- the
# "=" of a filter, the space after "key", the "into <table>" separator -- and
# the free-form part is sliced out of the text afterwards by _extract_value().
#
# These used to carry the value inline, as ``['\"]?(.+?)['\"]?\s*$`` (and the
# insert rule as ``(.+?)\s+``). A lazy ``.+?`` also matches whitespace, so it
# overlapped the ``\s*``/``\s+`` beside it: a run of spaces had as many valid
# splits as it had characters, and a query that could not match made the engine
# try all of them. That is quadratic in the length of the run -- CodeQL
# py/polynomial-redos, and ~81s of CPU for a 5,000-space "find" query.
#
# Keeping the open-ended tails out of the regexes removes the ambiguity: every
# quantifier below is separated from its neighbour by a character class it
# cannot overlap (``\s`` against ``\w``, or ``\s`` against a literal), so each
# character of the input can be consumed in exactly one way.
_FIND_HEAD = re.compile(r"find\s+(?:in\s+)?(\w+)\s+where\s+(\w+)\s*=", re.IGNORECASE)
_GET_KEY_HEAD = re.compile(r"get\s+key\s", re.IGNORECASE)
_INSERT_HEAD = re.compile(r"(?:insert|add|create)\s+", re.IGNORECASE)
_INSERT_SEP = re.compile(r"\s+(?:into|to|in)\s+(\w+)", re.IGNORECASE)
_DELETE_HEAD = re.compile(
    r"(?:delete|remove)\s+(?:from\s+)?(\w+)\s+where\s+(\w+)\s*=", re.IGNORECASE
)


def _extract_value(raw: str) -> str | None:
    r"""Turn the text following a rule's last fixed character into a value.

    Trims surrounding whitespace, then at most one quote from each end --
    exactly what the old ``['\"]?(.+?)['\"]?\s*$`` tail did, but by slicing
    instead of by backtracking, so it is linear in the length of the input.

    Returns ``None`` where that tail used to fail to match, which leaves the
    caller falling through to the next rule just as it did before.
    """
    # The old tail ended in ``$`` and ``.`` never matches a newline, so a value
    # could not span lines: one trailing newline was fine (``$`` matches before
    # it), an interior newline made the rule fail.
    line = raw[:-1] if raw.endswith("\n") else raw
    if "\n" in line:
        return None
    value = line.strip()
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
        # _FIND_HEAD stops at the "="; the value is whatever follows it.
        match = _FIND_HEAD.match(text)
        if match:
            value = _extract_value(text[match.end() :])
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
        # _GET_KEY_HEAD stops at the one space "key" must be followed by; any
        # further leading whitespace is trimmed by _extract_value().
        match = _GET_KEY_HEAD.match(text)
        if match:
            key = _extract_value(text[match.end() :])
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
        # The old `(.+?)\s+(?:into|to|in)\s+` searched for the first separator
        # by growing the data one character at a time, retrying the whole
        # separator at each step. Searching for the separator directly does the
        # same thing in one left-to-right pass: _INSERT_SEP.search() returns the
        # leftmost separator, which is the split the lazy `.+?` settled on.
        # Starting one character in keeps the data non-empty, as `.+?` required.
        match = _INSERT_HEAD.match(text)
        if match:
            start = match.end()
            sep = _INSERT_SEP.search(text, start + 1)
            # `.+?` never matched a newline, so a newline before the separator
            # made the old rule fail outright.
            if sep is not None and "\n" not in text[start : sep.start()]:
                data_str = text[start : sep.start()]
                table = sep.group(1)
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
        # Same head-plus-slice shape as the find arm.
        match = _DELETE_HEAD.match(text)
        if match:
            value = _extract_value(text[match.end() :])
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
