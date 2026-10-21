"""
tests/unit/test_unit_fts.py — eDB full-text search unit tests
SPDX-License-Identifier: MIT  Copyright (c) 2026 EmbeddedOS Foundation

Exercises src/edb/core/fts.py (FullTextSearch over SQLite FTS5, eDB#88):
index creation and listing, document indexing, ranked search, the
missing-index and malformed-query paths, re-index replacement,
deletion, and index dropping. Fresh tests written against the current
source; tests_backup/test_fts.py (never collected — pyproject sets
testpaths = ["tests"]) served as an oracle for intent only.
"""

import pytest

from edb.core.fts import FullTextSearch, SearchResult


@pytest.fixture
def fts(engine):
    return FullTextSearch(engine)


@pytest.fixture
def articles(fts):
    fts.create_index("articles", ["title", "body"])
    return fts


class TestIndexLifecycle:
    def test_list_indexes_empty_on_fresh_engine(self, fts):
        assert fts.list_indexes() == []

    def test_create_and_list_indexes(self, fts):
        fts.create_index("articles", ["title", "body"])
        fts.create_index("notes", ["text"])
        assert fts.list_indexes() == ["articles", "notes"]

    def test_create_index_twice_keeps_single_entry(self, fts):
        fts.create_index("articles", ["title"])
        fts.create_index("articles", ["title"])
        assert fts.list_indexes() == ["articles"]

    def test_drop_index_removes_it_from_listing(self, articles):
        articles.drop_index("articles")
        assert articles.list_indexes() == []

    def test_drop_index_removes_meta_so_search_returns_empty(self, articles):
        articles.index_document("articles", "1", {"title": "Python", "body": "code"})
        articles.drop_index("articles")
        assert articles.search("articles", "Python") == []

    def test_drop_missing_index_does_not_raise(self, fts):
        fts.drop_index("never_existed")
        assert fts.list_indexes() == []


class TestIndexing:
    def test_index_document_on_missing_index_raises(self, fts):
        with pytest.raises(ValueError, match="does not exist"):
            fts.index_document("missing", "1", {"title": "x"})

    def test_missing_fields_default_to_empty_string(self, articles):
        articles.index_document("articles", "1", {"title": "Only Title"})
        results = articles.search("articles", "Title")
        assert len(results) == 1
        assert results[0].fields == {"title": "Only Title", "body": ""}

    def test_reindexing_same_doc_replaces_rather_than_duplicates(self, articles):
        articles.index_document("articles", "1", {"title": "Draft", "body": "alpha"})
        articles.index_document("articles", "1", {"title": "Final", "body": "omega"})
        assert articles.search("articles", "alpha") == []
        results = articles.search("articles", "omega")
        assert len(results) == 1
        assert results[0].fields["title"] == "Final"


class TestSearch:
    def test_search_returns_matching_docs_with_fields_and_score(self, articles):
        articles.index_document(
            "articles", "1", {"title": "Python Programming", "body": "Learn Python basics"}
        )
        articles.index_document(
            "articles", "2", {"title": "Database Design", "body": "SQL and NoSQL patterns"}
        )
        articles.index_document(
            "articles", "3", {"title": "Python Advanced", "body": "Async and concurrency"}
        )
        results = articles.search("articles", "Python")
        assert {r.doc_id for r in results} == {"1", "3"}
        for r in results:
            assert isinstance(r, SearchResult)
            assert set(r.fields) == {"title", "body"}
            assert r.score >= 0

    def test_search_no_match_returns_empty(self, articles):
        articles.index_document("articles", "1", {"title": "Hello World", "body": "hi"})
        assert articles.search("articles", "nonexistent") == []

    def test_search_on_missing_index_returns_empty(self, fts):
        assert fts.search("missing_index", "query") == []

    def test_malformed_query_returns_empty_via_exception_path(self, articles):
        articles.index_document("articles", "1", {"title": "Hello", "body": "world"})
        assert articles.search("articles", '"unclosed') == []

    def test_search_respects_limit(self, articles):
        for i in range(5):
            articles.index_document(
                "articles", str(i), {"title": f"Python part {i}", "body": "Python"}
            )
        assert len(articles.search("articles", "Python", limit=2)) == 2


class TestDeleteDocument:
    def test_delete_returns_true_then_false(self, articles):
        articles.index_document("articles", "1", {"title": "Python", "body": "code"})
        assert articles.delete_document("articles", "1") is True
        assert articles.delete_document("articles", "1") is False

    def test_deleted_document_no_longer_searchable(self, articles):
        articles.index_document("articles", "1", {"title": "Python", "body": "code"})
        articles.delete_document("articles", "1")
        assert articles.search("articles", "Python") == []
