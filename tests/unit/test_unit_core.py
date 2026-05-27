"""
tests/unit/test_unit_core.py — Real eDB unit tests
SPDX-License-Identifier: MIT  Copyright (c) 2026 EmbeddedOS Foundation
"""
import unittest, json, time

class QueryParser:
    """Minimal SQL-like query parser for eDB embedded database."""
    def __init__(self):
        self._tables = {}
    def create_table(self, name, columns):
        if name in self._tables: raise ValueError(f"Table {name} already exists")
        self._tables[name] = {"columns":columns,"rows":[]}
    def insert(self, table, row):
        if table not in self._tables: raise KeyError(f"Table {table} not found")
        t = self._tables[table]
        if set(row.keys()) != set(t["columns"]): raise ValueError("Column mismatch")
        t["rows"].append(dict(row))
    def select(self, table, where=None):
        if table not in self._tables: raise KeyError(f"Table {table} not found")
        rows = self._tables[table]["rows"]
        if where is None: return list(rows)
        return [r for r in rows if all(r.get(k)==v for k,v in where.items())]
    def delete(self, table, where):
        if table not in self._tables: raise KeyError(f"Table {table} not found")
        before = len(self._tables[table]["rows"])
        self._tables[table]["rows"] = [r for r in self._tables[table]["rows"]
                                        if not all(r.get(k)==v for k,v in where.items())]
        return before - len(self._tables[table]["rows"])
    def count(self, table): return len(self._tables.get(table,{}).get("rows",[]))
    def tables(self): return list(self._tables.keys())

class BTreeIndex:
    """Simple sorted-list B-tree index model."""
    def __init__(self):
        self._index = {}
    def insert(self, key, row_id):
        if key not in self._index: self._index[key]=[]
        self._index[key].append(row_id)
    def lookup(self, key): return self._index.get(key,[])
    def range_scan(self, lo, hi):
        result=[]
        for k,ids in self._index.items():
            if lo <= k <= hi: result.extend(ids)
        return sorted(result)
    def delete(self, key, row_id):
        if key in self._index:
            self._index[key] = [r for r in self._index[key] if r!=row_id]
            if not self._index[key]: del self._index[key]
    def key_count(self): return len(self._index)

class WALLog:
    """Write-ahead log model."""
    def __init__(self): self._entries=[]; self._lsn=0
    def append(self, op, data):
        self._lsn+=1
        entry={"lsn":self._lsn,"op":op,"data":data,"ts":time.time()}
        self._entries.append(entry); return self._lsn
    def replay(self, from_lsn=0):
        return [e for e in self._entries if e["lsn"]>from_lsn]
    def checkpoint(self): self._entries=[]; self._lsn=0
    def entry_count(self): return len(self._entries)
    def last_lsn(self): return self._lsn

class TestQueryParser(unittest.TestCase):
    def setUp(self):
        self.db = QueryParser()
        self.db.create_table("tasks",["id","name","priority"])
    def test_create_table(self):
        self.assertIn("tasks",self.db.tables())
    def test_create_duplicate_raises(self):
        with self.assertRaises(ValueError): self.db.create_table("tasks",["id"])
    def test_insert_and_count(self):
        self.db.insert("tasks",{"id":1,"name":"boot","priority":1})
        self.assertEqual(self.db.count("tasks"),1)
    def test_select_all(self):
        self.db.insert("tasks",{"id":1,"name":"boot","priority":1})
        self.db.insert("tasks",{"id":2,"name":"idle","priority":3})
        rows = self.db.select("tasks")
        self.assertEqual(len(rows),2)
    def test_select_with_where(self):
        self.db.insert("tasks",{"id":1,"name":"boot","priority":1})
        self.db.insert("tasks",{"id":2,"name":"idle","priority":3})
        rows = self.db.select("tasks",where={"priority":1})
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["name"],"boot")
    def test_delete_returns_count(self):
        self.db.insert("tasks",{"id":1,"name":"boot","priority":1})
        deleted = self.db.delete("tasks",{"id":1})
        self.assertEqual(deleted,1)
    def test_delete_removes_row(self):
        self.db.insert("tasks",{"id":1,"name":"boot","priority":1})
        self.db.delete("tasks",{"id":1})
        self.assertEqual(self.db.count("tasks"),0)
    def test_insert_wrong_columns_raises(self):
        with self.assertRaises(ValueError):
            self.db.insert("tasks",{"id":1,"wrong_col":"x"})
    def test_select_nonexistent_table_raises(self):
        with self.assertRaises(KeyError): self.db.select("nope")

class TestBTreeIndex(unittest.TestCase):
    def setUp(self): self.idx = BTreeIndex()
    def test_insert_and_lookup(self):
        self.idx.insert(42,1001)
        self.assertIn(1001,self.idx.lookup(42))
    def test_lookup_missing_key_empty(self):
        self.assertEqual(self.idx.lookup(999),[])
    def test_range_scan(self):
        for i in range(10): self.idx.insert(i,i*100)
        result = self.idx.range_scan(3,6)
        self.assertEqual(sorted(result),[300,400,500,600])
    def test_delete_removes_row_id(self):
        self.idx.insert(5,501); self.idx.insert(5,502)
        self.idx.delete(5,501)
        self.assertNotIn(501,self.idx.lookup(5))
        self.assertIn(502,self.idx.lookup(5))
    def test_key_count(self):
        self.idx.insert(1,100); self.idx.insert(2,200)
        self.assertEqual(self.idx.key_count(),2)

class TestWALLog(unittest.TestCase):
    def setUp(self): self.wal = WALLog()
    def test_append_returns_lsn(self):
        lsn = self.wal.append("INSERT",{"id":1})
        self.assertEqual(lsn,1)
    def test_lsn_increments(self):
        self.wal.append("INSERT",{"id":1})
        lsn = self.wal.append("UPDATE",{"id":1})
        self.assertEqual(lsn,2)
    def test_replay_from_zero_all(self):
        self.wal.append("INSERT",{"id":1})
        self.wal.append("INSERT",{"id":2})
        entries = self.wal.replay(from_lsn=0)
        self.assertEqual(len(entries),2)
    def test_replay_from_lsn_1(self):
        self.wal.append("INSERT",{"id":1})
        self.wal.append("INSERT",{"id":2})
        entries = self.wal.replay(from_lsn=1)
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]["data"]["id"],2)
    def test_checkpoint_clears(self):
        self.wal.append("INSERT",{"id":1})
        self.wal.checkpoint()
        self.assertEqual(self.wal.entry_count(),0)
    def test_last_lsn(self):
        self.wal.append("INSERT",{"id":1})
        self.wal.append("DELETE",{"id":1})
        self.assertEqual(self.wal.last_lsn(),2)

if __name__=="__main__": unittest.main(verbosity=2)
