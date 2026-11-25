# SPDX-License-Identifier: MIT
"""Unit tests for the ebot NL translators (issue #99 coverage drive).

Covers edb/ebot/translator.py (rule-based NLQueryTranslator) and
edb/ebot/llm_translator.py (LLMTranslator, with the OpenAI client stubbed —
no network, no API key).
"""

import json
import sys

import pytest

from edb.ebot.llm_translator import LLMTranslator
from edb.ebot.translator import NLQueryTranslator


class TestNLQueryTranslator:
    def setup_method(self):
        self.t = NLQueryTranslator()

    def test_empty_query_errors(self):
        r = self.t.translate("   ")
        assert r.error == "Empty query"

    def test_unknown_provider_errors(self):
        r = NLQueryTranslator(provider="gpt-9").translate("show users")
        assert "not available" in r.error

    def test_list_tables(self):
        r = self.t.translate("list tables")
        assert r.error is None
        assert r.translated_query["type"] == "sql"
        assert "sqlite_master" in r.translated_query["raw_sql"]

    def test_show_tables_alias(self):
        r = self.t.translate("show tables")
        assert r.translated_query["type"] == "sql"

    def test_list_collections(self):
        r = self.t.translate("list collections")
        assert r.translated_query == {
            "type": "document",
            "action": "list_collections",
            "collection": "",
        }

    def test_list_keys(self):
        r = self.t.translate("list keys")
        assert r.translated_query == {"type": "kv", "action": "list"}

    def test_show_all_users_select(self):
        r = self.t.translate("show all users")
        assert r.error is None
        assert r.translated_query["type"] == "sql"
        assert r.translated_query["action"] == "select"
        assert r.translated_query["table"] == "users"

    def test_count_collection(self):
        r = self.t.translate("count orders")
        assert r.translated_query["type"] == "document"
        assert r.translated_query["action"] == "count"
        assert r.translated_query["collection"] == "orders"

    def test_insert_into_table(self):
        r = self.t.translate("insert name=ada into users")
        assert r.error is None
        assert r.translated_query["type"] == "sql"
        assert r.translated_query["action"] == "insert"
        assert r.translated_query["table"] == "users"
        assert r.translated_query["data"] == {"name": "ada"}

    def test_delete_where(self):
        r = self.t.translate("delete from users where name='ada'")
        assert r.translated_query["type"] == "sql"
        assert r.translated_query["action"] == "delete"
        assert r.translated_query["where"] == {"name": "ada"}

    def test_find_documents_where(self):
        r = self.t.translate("find users where name=ada")
        assert r.translated_query["type"] == "document"
        assert r.translated_query["action"] == "find"
        assert r.translated_query["filter"] == {"name": "ada"}

    def test_get_key(self):
        r = self.t.translate("get key session-token")
        assert r.translated_query == {"type": "kv", "action": "get", "key": "session-token"}

    def test_find_keeps_case_of_collection_field_and_value(self):
        r = self.t.translate("find Users where Name=Ada")
        assert r.translated_query == {
            "type": "document",
            "action": "find",
            "collection": "Users",
            "filter": {"Name": "Ada"},
        }

    def test_get_key_keeps_case(self):
        r = self.t.translate("GET KEY Session-Token")
        assert r.translated_query == {"type": "kv", "action": "get", "key": "Session-Token"}

    def test_insert_keeps_case_of_values(self):
        r = self.t.translate("insert name=Ada into users")
        assert r.translated_query["data"] == {"name": "Ada"}

    def test_delete_where_keeps_case_of_value(self):
        r = self.t.translate("Delete from users where name='Ada'")
        assert r.translated_query["where"] == {"name": "Ada"}

    def test_count_keeps_case_of_collection(self):
        r = self.t.translate("How many Orders")
        assert r.translated_query["collection"] == "Orders"

    def test_find_with_mixed_case_value_matches_stored_document(self):
        from edb.core.database import Database
        from edb.query.parser import QueryParser
        from edb.query.planner import QueryPlanner

        db = Database(":memory:")
        try:
            db.docs.insert("users", {"name": "Ada"})
            r = self.t.translate("find users where name=Ada")
            result = QueryPlanner(db).execute(QueryParser().parse(r.translated_query))
            assert result.success
            assert result.row_count == 1
        finally:
            db.close()

    def test_gibberish_errors_with_hint(self):
        r = self.t.translate("florp the wobble")
        assert r.error is not None
        assert "show all users" in r.error

    # ------------------------------------------------------------------
    # ReDoS regression (CodeQL py/polynomial-redos, 4 high alerts).
    #
    # The four patterns below used to pair a lazy `(.+?)` with an adjacent
    # `\s*`/`\s+`, so a long run of spaces made matching quadratic. The
    # patterns are now unambiguous; these tests pin both that each entry
    # point still translates correctly (including runs of internal
    # whitespace and preserved case) and that the blow-up is gone.
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            # find: keywords in any case, names/fields/values keep theirs,
            # and runs of internal whitespace survive inside the value.
            (
                "find Users where Name=Ada   Lovelace",
                {
                    "type": "document",
                    "action": "find",
                    "collection": "Users",
                    "filter": {"Name": "Ada   Lovelace"},
                },
            ),
            (
                "FIND IN Orders WHERE Status='In   Transit'",
                {
                    "type": "document",
                    "action": "find",
                    "collection": "Orders",
                    "filter": {"Status": "In   Transit"},
                },
            ),
            # get key: extra spaces after the keyword are separators, but
            # spaces inside the key are part of the key.
            (
                "get key   Session   Token",
                {"type": "kv", "action": "get", "key": "Session   Token"},
            ),
            (
                'GET KEY "My   Key"',
                {"type": "kv", "action": "get", "key": "My   Key"},
            ),
            # delete: same value handling as find.
            (
                "Delete from Users where Name='Ada   Lovelace'",
                {
                    "type": "sql",
                    "action": "delete",
                    "table": "Users",
                    "where": {"Name": "Ada   Lovelace"},
                },
            ),
        ],
    )
    def test_redos_fix_keeps_translation(self, query, expected):
        r = self.t.translate(query)
        assert r.error is None
        assert r.translated_query == expected

    def test_redos_fix_keeps_insert_with_internal_whitespace(self):
        # The insert data is captured by its own pattern; runs of spaces
        # between the key=value pairs must still parse.
        r = self.t.translate("ADD Name=Ada,   Age=36   INTO   Users")
        assert r.error is None
        assert r.translated_query["type"] == "sql"
        assert r.translated_query["action"] == "insert"
        assert r.translated_query["table"] == "Users"
        assert r.translated_query["data"] == {"Name": "Ada", "Age": "36"}

    @pytest.mark.parametrize(
        "prefix",
        [
            # The prefixes CodeQL named, for each of the four arms.
            "find 0 where 0=",
            "get key ",
            "add ",
            "delete 0 where 0=",
            # ...and the same four with one character of data before the run.
            # These matter on their own: a rule whose leading `\s+` is reached
            # by a *scan* rather than an anchored match re-reads the rest of
            # the run from every offset inside it, which is quadratic even
            # though the bare-prefix form above stays fast (the rule's own
            # greedy `\s+` swallows a run that directly follows the keyword).
            "find 0 where 0=a",
            "get key a",
            "add a",
            "delete 0 where 0=a",
        ],
    )
    def test_redos_adversarial_input_is_linear(self, prefix):
        # The exact prefixes CodeQL reported, plus a long run of spaces. The
        # trailing "x\ny" earns its keep twice: it survives translate()'s
        # .strip(), so the space run really reaches the regexes, and the
        # embedded newline blocks the value capture ("." never matches a
        # newline) so the overall match fails -- a failing match is what made
        # the old patterns retry every split of the space run.
        #
        # Timed rather than asserted on a wall clock budget alone: the old
        # patterns were quadratic, so 8x the input cost ~64x the time. A
        # generous 8x allowance still fails loudly on a quadratic regression
        # while staying stable on slow/loaded CI runners.
        import time

        def elapsed(n):
            text = prefix + " " * n + "x\ny"
            best = float("inf")
            for _ in range(3):
                t0 = time.perf_counter()
                self.t.translate(text)
                best = min(best, time.perf_counter() - t0)
            return best

        small = elapsed(2_000)
        large = elapsed(16_000)

        # Absolute ceiling: the old code needed many seconds here.
        assert large < 1.0, f"{prefix!r} took {large:.3f}s on 16k spaces"
        # Growth check: linear-ish, nowhere near the ~64x of a quadratic scan.
        floor = 1e-4  # ignore timer noise on very fast runs
        assert large <= max(small, floor) * 8, (
            f"{prefix!r} scaled {large / max(small, floor):.1f}x for 8x input"
        )

    def test_kwargs_stored(self):
        t = NLQueryTranslator(provider="rule_based", foo="bar")
        assert t._kwargs == {"foo": "bar"}


class FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        self.kwargs = kwargs

        class Choice:
            class Message:
                def __init__(self, content):
                    self.content = content

            def __init__(self, content):
                self.message = self.Message(content)

        class Response:
            def __init__(self, content):
                self.choices = [Choice(content)]

        return Response(self._content)


class FakeChat:
    def __init__(self, content):
        self.completions = FakeCompletions(content)


class FakeOpenAIClient:
    last_instance = None

    def __init__(self, content='{"type": "kv", "action": "get", "key": "k"}', **kwargs):
        self.kwargs = kwargs
        self.chat = FakeChat(content)
        FakeOpenAIClient.last_instance = self


def install_fake_openai(monkeypatch, content='{"type": "kv", "action": "get", "key": "k"}'):
    import types

    fake = types.ModuleType("openai")
    fake.__dict__["OpenAI"] = lambda **kwargs: FakeOpenAIClient(content, **kwargs)
    monkeypatch.setitem(sys.modules, "openai", fake)


class TestLLMTranslator:
    def test_constructor_stores_settings(self):
        t = LLMTranslator(api_key="k", model="gpt-4o", base_url="https://x/v1")
        assert t._api_key == "k"
        assert t._model == "gpt-4o"
        assert t._base_url == "https://x/v1"

    def test_missing_openai_package_errors(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "openai", None)
        t = LLMTranslator(api_key="k")
        r = t.translate("show users")
        assert "OpenAI package not installed" in r.error

    def test_translate_parses_llm_json(self, monkeypatch):
        install_fake_openai(monkeypatch)
        t = LLMTranslator(api_key="k", model="gpt-4o", base_url="https://x/v1")
        r = t.translate("get the key k")
        assert r.error is None
        assert r.translated_query == {"type": "kv", "action": "get", "key": "k"}
        client = FakeOpenAIClient.last_instance
        assert client.kwargs["api_key"] == "k"
        assert client.kwargs["base_url"] == "https://x/v1"
        create_kwargs = client.chat.completions.kwargs
        assert create_kwargs["model"] == "gpt-4o"
        assert create_kwargs["messages"][0]["role"] == "system"
        assert "get the key k" in create_kwargs["messages"][1]["content"]

    def test_context_appended_to_user_message(self, monkeypatch):
        install_fake_openai(monkeypatch)
        LLMTranslator(api_key="k").translate("show users", context={"table": "users"})
        create_kwargs = FakeOpenAIClient.last_instance.chat.completions.kwargs
        assert json.dumps({"table": "users"}) in create_kwargs["messages"][1]["content"]

    def test_fenced_json_stripped(self, monkeypatch):
        install_fake_openai(monkeypatch, '```json\n{"type": "kv", "action": "list"}\n```')
        r = LLMTranslator(api_key="k").translate("list keys")
        assert r.error is None
        assert r.translated_query == {"type": "kv", "action": "list"}

    def test_invalid_json_errors(self, monkeypatch):
        install_fake_openai(monkeypatch, "not json at all {{{")
        r = LLMTranslator(api_key="k").translate("show users")
        assert "invalid JSON" in r.error

    def test_client_exception_errors(self, monkeypatch):
        import types

        fake = types.ModuleType("openai")

        def boom(**kwargs):
            raise RuntimeError("network down")

        fake.__dict__["OpenAI"] = boom
        monkeypatch.setitem(sys.modules, "openai", fake)
        r = LLMTranslator(api_key="k").translate("show users")
        assert "LLM error" in r.error


@pytest.mark.parametrize(
    "text,expected_type",
    [
        ("list tables", "sql"),
        ("list collections", "document"),
        ("list keys", "kv"),
        ("show all sensors", "sql"),
        ("how many events", "document"),
        ("get key api-token", "kv"),
        ("get users", "sql"),  # plain "get <table>" keeps its SELECT meaning
    ],
)
def test_translator_parametrized_shapes(text, expected_type):
    r = NLQueryTranslator().translate(text)
    assert r.error is None
    assert r.translated_query["type"] == expected_type
