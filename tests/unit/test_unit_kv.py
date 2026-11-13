import pytest

from edb.core.engine import StorageEngine
from edb.core.keyvalue import KeyValueStore, _prefix_upper_bound


@pytest.fixture
def kv_store():
    # Use the actual production engine in memory to mirror transaction behavior accurately
    engine = StorageEngine(":memory:")
    return KeyValueStore(engine)

def test_set_and_get_many(kv_store):
    data = {"k1": "v1", "k2": "v2", "k3": "v3"}

    inserted = kv_store.set_many(data)
    assert len(inserted) == 3
    assert kv_store.count() == 3

    fetched = kv_store.get_many(["k1", "k3", "k99"])
    assert fetched == {"k1": "v1", "k3": "v3"}
    assert "k99" not in fetched

def test_ttl_expiration_and_filtering(kv_store):
    # Set one key that lasts a while and one that is already expired
    kv_store.set("alive", "yes", ttl=10)
    kv_store.set("dead", "no", ttl=-1)

    assert kv_store.count() == 1

    keys = kv_store.list_keys()
    assert "alive" in keys
    assert "dead" not in keys

    # get_many() should not return the dead key and should physically delete it
    fetched = kv_store.get_many(["alive", "dead"])
    assert "alive" in fetched
    assert "dead" not in fetched

    # Assert row was actually deleted from disk
    cur = kv_store._e.execute("SELECT COUNT(*) as c FROM _kv WHERE key = ?", ("dead",))
    assert cur.fetchone()["c"] == 0

def test_prune_expired(kv_store):
    kv_store.set("k1", "v1", ttl=10)
    kv_store.set("k2", "v2", ttl=-1)
    kv_store.set("k3", "v3", ttl=-10)

    cur = kv_store._e.execute("SELECT COUNT(*) as c FROM _kv")
    assert cur.fetchone()["c"] == 3

    deleted_count = kv_store.prune_expired()
    assert deleted_count == 2

    cur = kv_store._e.execute("SELECT COUNT(*) as c FROM _kv")
    assert cur.fetchone()["c"] == 1


def test_get_expired_key_deletes_and_returns_none(kv_store):
    kv_store.set("ghost", "boo", ttl=-1)

    assert kv_store.get("ghost") is None

    # The expired row is physically removed by the get, not just hidden
    cur = kv_store._e.execute("SELECT COUNT(*) as c FROM _kv WHERE key = ?", ("ghost",))
    assert cur.fetchone()["c"] == 0


def test_get_many_empty_keys(kv_store):
    kv_store.set("k1", "v1")
    assert kv_store.get_many([]) == {}


def test_set_many_empty_mapping(kv_store):
    assert kv_store.set_many({}) == []
    assert kv_store.count() == 0


class _FailingEngine:
    """Engine wrapper that delegates to a real engine but raises on
    statements matching a predicate, recording what it was asked to run."""

    def __init__(self, real, fail_pred):
        self._real = real
        self._fail_pred = fail_pred
        self.seen = []

    def execute(self, sql, params=()):
        self.seen.append(sql)
        if self._fail_pred(sql):
            raise RuntimeError("injected failure")
        return self._real.execute(sql, params)

    def commit(self):
        return self._real.commit()


def test_get_many_delete_failure_rolls_back(kv_store):
    kv_store.set("alive", "yes", ttl=10)
    kv_store.set("dead", "no", ttl=-1)

    failing = _FailingEngine(
        kv_store._e, lambda sql: sql.startswith("DELETE FROM _kv WHERE key IN")
    )
    kv_store._e = failing

    # The expired key is excluded from the result even though its
    # physical deletion failed and the delete transaction rolled back
    fetched = kv_store.get_many(["alive", "dead"])
    assert fetched == {"alive": "yes"}
    assert "ROLLBACK" in failing.seen


def test_set_many_insert_failure_rolls_back_and_raises(kv_store):
    failing = _FailingEngine(
        kv_store._e, lambda sql: sql.startswith("INSERT OR REPLACE")
    )
    kv_store._e = failing

    with pytest.raises(RuntimeError, match="injected failure"):
        kv_store.set_many({"a": 1})
    assert "ROLLBACK" in failing.seen


class _NullRowCursor:
    def fetchone(self):
        return None


class _NullCountEngine:
    """Engine stub whose COUNT query returns no row at all."""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, params=()):
        if sql.startswith("SELECT COUNT(*)"):
            return _NullRowCursor()
        return self._real.execute(sql, params)

    def commit(self):
        return self._real.commit()


def test_count_without_row_is_zero(kv_store):
    kv_store._e = _NullCountEngine(kv_store._e)
    assert kv_store.count() == 0


def test_clear_returns_deleted_count(kv_store):
    kv_store.set_many({"a": 1, "b": 2, "c": 3})
    assert kv_store.clear() == 3
    assert kv_store.count() == 0
    assert kv_store.clear() == 0


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("user_", ["user_1"]),
        ("a%", ["a%b"]),
        ("User", ["User_2"]),
        ("user", ["user_1", "userX", "users"]),
        ("café:", ["café:1"]),
        ("nope", []),
    ],
)
def test_list_keys_prefix_is_literal_and_case_sensitive(kv_store, prefix, expected):
    for key in ["user_1", "userX", "User_2", "users", "a%b", "abc", "café:1", "cafe:1"]:
        kv_store.set(key, 1)

    assert sorted(kv_store.list_keys(prefix)) == sorted(expected)


def test_list_keys_prefix_skips_expired_keys(kv_store):
    kv_store.set("job_live", 1, ttl=10)
    kv_store.set("job_dead", 1, ttl=-1)

    assert kv_store.list_keys("job_") == ["job_live"]


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("a\x00", ["a\x00b"]),
        ("\ud7ff", ["\ud7ffx"]),
        ("\U0010ffff", ["\U0010ffff", "\U0010ffffz"]),
        ("k\U0010ffff", ["k\U0010ffff1"]),
        ("\U0001f600", ["\U0001f600!"]),
        ("\\", ["\\x"]),
    ],
)
def test_list_keys_prefix_edge_characters(kv_store, prefix, expected):
    keys = [
        "a",
        "a\x00b",
        "ab",
        "\ud7ffx",
        "\ue000",
        "\U0010ffff",
        "\U0010ffffz",
        "k\U0010ffff1",
        "l",
        "\U0001f600!",
        "\U0001f601",
        "\\x",
        "]",
    ]
    for key in keys:
        kv_store.set(key, 1)

    assert sorted(kv_store.list_keys(prefix)) == sorted(expected)


def test_list_keys_empty_prefix_lists_every_live_key(kv_store):
    for key in ["a", "B", "\U0010ffff"]:
        kv_store.set(key, 1)
    kv_store.set("gone", 1, ttl=-1)

    assert sorted(kv_store.list_keys("")) == sorted(["a", "B", "\U0010ffff"])


@pytest.mark.parametrize(
    ("prefix", "upper"),
    [
        ("user_", "user`"),
        ("\ud7ff", "\ue000"),
        ("a\U0010ffff", "b"),
        ("\U0010ffff\U0010ffff", None),
    ],
)
def test_prefix_upper_bound(prefix, upper):
    assert _prefix_upper_bound(prefix) == upper


def test_set_many_is_committed(tmp_path):
    path = str(tmp_path / "kv.db")
    engine = StorageEngine(path)
    KeyValueStore(engine).set_many({"a": 1, "b": 2})
    engine.close()

    assert KeyValueStore(StorageEngine(path)).get_many(["a", "b"]) == {"a": 1, "b": 2}


def test_set_many_can_be_called_twice(kv_store):
    kv_store.set_many({"a": 1})
    kv_store.set_many({"b": 2})
    assert kv_store.count() == 2


def test_get_many_expired_delete_is_committed(tmp_path):
    path = str(tmp_path / "kv.db")
    engine = StorageEngine(path)
    kv = KeyValueStore(engine)
    kv.set("alive", "yes", ttl=10)
    kv.set("dead", "no", ttl=-1)
    kv.get_many(["alive", "dead"])
    engine.close()

    rows = StorageEngine(path).fetchall("SELECT key FROM _kv")
    assert [r["key"] for r in rows] == ["alive"]
