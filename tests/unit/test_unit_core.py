import unittest
class TestEDBUnit(unittest.TestCase):
    def test_btree_insert_lookup(self):
        btree = {}
        btree["key1"] = "val1"
        self.assertEqual(btree["key1"], "val1")
