"""Unit tests for edb.core.document — DocumentStore (#88 coverage drive).

Whole-module slice: document.py measured 8 missed statements /
86.32% at a8adc644 (unit scope) — insert_many, the find()
filter_fn / offset / limit lines, count() with a filter, and
drop_collection() had no unit coverage at all. These tests use
the real StorageEngine on an in-memory database, mirroring
test_unit_kv.py's approach.

Behaviour pinned as the code implements it:

- insert() auto-creates its collection and returns a Document
  with the caller's explicit doc_id, or a generated UUID when
  none is given; inserting the same id again replaces the data.
- find() applies filter_dict (equality on every key), then
  filter_fn, then offset, then limit — in that order.
- update() merges by default, replaces with merge=False, and
  returns None for a missing document.
- delete() reports the DELETE rowcount: True exactly when a
  row existed.
- count(filter_dict=...) is defined as len(find(...)).
- drop_collection() removes the documents and the collection
  row; dropping a collection that does not exist is silent.
- created_at is NOT persisted: the _documents table stores only
  (doc_id, collection, data), so every read constructs Documents
  with a fresh created_at = now. Two find() calls for the same
  row therefore return Documents that are not == (their
  created_at differs). Pinned as implemented, not fixed here.
"""

import pytest

from edb.core.document import Document, DocumentStore
from edb.core.engine import StorageEngine


@pytest.fixture
def store():
    engine = StorageEngine(":memory:")
    return DocumentStore(engine)


@pytest.fixture
def populated(store):
    store.insert("users", {"name": "ada", "role": "admin", "age": 36}, doc_id="u1")
    store.insert("users", {"name": "grace", "role": "user", "age": 40}, doc_id="u2")
    store.insert("users", {"name": "alan", "role": "user", "age": 41}, doc_id="u3")
    store.insert("logs", {"msg": "boot"}, doc_id="l1")
    return store


# --- collections & insert ---------------------------------------------------


def test_create_collection_is_idempotent_and_listed(store):
    store.create_collection("a")
    store.create_collection("a")
    store.create_collection("b")

    assert store.list_collections() == ["a", "b"]


def test_insert_with_explicit_id_returns_document(store):
    doc = store.insert("c", {"x": 1}, doc_id="d1")

    assert doc.id == "d1"
    assert doc.collection == "c"
    assert doc.data == {"x": 1}
    assert store.list_collections() == ["c"]  # auto-created


def test_insert_without_id_generates_one(store):
    doc = store.insert("c", {"x": 2})

    assert doc.id
    assert store.find_by_id("c", doc.id).data == {"x": 2}


def test_insert_same_id_replaces_data(store):
    store.insert("c", {"v": 1}, doc_id="d1")
    store.insert("c", {"v": 2}, doc_id="d1")

    assert store.count("c") == 1
    assert store.find_by_id("c", "d1").data == {"v": 2}


def test_insert_many_returns_documents_in_order(store):
    docs = store.insert_many("c", [{"n": 1}, {"n": 2}, {"n": 3}])

    assert [d.data["n"] for d in docs] == [1, 2, 3]
    assert all(d.collection == "c" for d in docs)
    assert store.count("c") == 3


def test_insert_many_empty_list(store):
    assert store.insert_many("c", []) == []
    assert store.count("c") == 0


# --- find_by_id / find -------------------------------------------------------


def test_find_by_id_hit_and_miss(populated):
    assert populated.find_by_id("users", "u2").data["name"] == "grace"
    assert populated.find_by_id("users", "nope") is None
    assert populated.find_by_id("nope", "u1") is None


def test_find_all_in_collection(populated):
    docs = populated.find("users")

    assert {d.id for d in docs} == {"u1", "u2", "u3"}
    assert populated.find("empty") == []


def test_find_filter_dict_requires_every_key(populated):
    assert [d.id for d in populated.find("users", filter_dict={"role": "user"})] == [
        "u2",
        "u3",
    ]
    assert populated.find(
        "users", filter_dict={"role": "user", "name": "ada"}
    ) == []


def test_find_filter_fn(populated):
    docs = populated.find("users", filter_fn=lambda d: d["age"] >= 40)

    assert {d.id for d in docs} == {"u2", "u3"}


def test_find_offset_and_limit(populated):
    # Compare ids: created_at is regenerated on every read (see the
    # module docstring note), so Document equality across two find()
    # calls never holds.
    def ids(docs):
        return [d.id for d in docs]

    assert ids(populated.find("users", offset=1)) == ["u2", "u3"]
    assert ids(populated.find("users", limit=2)) == ["u1", "u2"]
    assert ids(populated.find("users", offset=1, limit=1)) == ["u2"]
    assert populated.find("users", offset=99) == []


def test_find_filters_apply_before_offset_and_limit(populated):
    docs = populated.find(
        "users",
        filter_dict={"role": "user"},
        filter_fn=lambda d: d["age"] >= 40,
        offset=1,
    )

    assert [d.id for d in docs] == ["u3"]


# --- update / delete ----------------------------------------------------------


def test_update_merges_by_default(populated):
    updated = populated.update("users", "u1", {"age": 37})

    assert updated.data == {"name": "ada", "role": "admin", "age": 37}
    assert populated.find_by_id("users", "u1").data["age"] == 37


def test_update_replace_with_merge_false(populated):
    updated = populated.update("users", "u1", {"name": "ada2"}, merge=False)

    assert updated.data == {"name": "ada2"}


def test_update_missing_document_returns_none(populated):
    assert populated.update("users", "nope", {"x": 1}) is None


def test_delete_reports_whether_a_row_existed(populated):
    assert populated.delete("users", "u1") is True
    assert populated.find_by_id("users", "u1") is None
    assert populated.delete("users", "u1") is False


# --- count / drop -------------------------------------------------------------


def test_count_plain_and_filtered(populated):
    assert populated.count("users") == 3
    assert populated.count("users", filter_dict={"role": "user"}) == 2
    assert populated.count("users", filter_dict={"role": "ghost"}) == 0
    assert populated.count("empty") == 0


def test_drop_collection_removes_documents_and_collection(populated):
    populated.drop_collection("users")

    assert populated.count("users") == 0
    assert populated.find("users") == []
    assert "users" not in populated.list_collections()
    # The other collection is untouched.
    assert populated.count("logs") == 1


def test_drop_missing_collection_is_silent(store):
    store.drop_collection("never-existed")
    assert store.list_collections() == []


# --- Document dataclass --------------------------------------------------------


def test_document_model_dump_shape():
    doc = Document(id="d", collection="c", data={"k": "v"}, created_at=123.5)

    assert doc.model_dump() == {
        "id": "d",
        "collection": "c",
        "data": {"k": "v"},
        "created_at": 123.5,
    }
