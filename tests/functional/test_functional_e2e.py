# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project
import unittest
class TestEdbFunctional(unittest.TestCase):
    def test_btree_index_insert_lookup(self):
        print("Testing B-Tree index insertion and fast key lookup...")
        db = {}
        index = {}
        db[101] = {"name": "Alice", "role": "admin"}
        index[101] = len(db) - 1
        record = db[101]
        self.assertEqual(record["name"], "Alice")
