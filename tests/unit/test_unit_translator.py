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

    def test_gibberish_errors_with_hint(self):
        r = self.t.translate("florp the wobble")
        assert r.error is not None
        assert "show all users" in r.error

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
    setattr(fake, "OpenAI", lambda **kwargs: FakeOpenAIClient(content, **kwargs))
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

        setattr(fake, "OpenAI", boom)
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
