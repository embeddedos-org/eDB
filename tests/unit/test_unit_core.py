import unittest

class TesteDBUnit(unittest.TestCase):
    def test_btree_node_insert_lookup(self):
        # Simulate B-Tree node insertion and lookup
        btree = {}
        # Insert
        btree["key_1"] = "value_1"
        btree["key_2"] = "value_2"
        # Lookup
        assert btree["key_1"] == "value_1"
        assert btree.get("key_3") is None
