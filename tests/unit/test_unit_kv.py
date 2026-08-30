import time
import pytest
from edb.core.keyvalue import KeyValueStore
from edb.core.engine import StorageEngine

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