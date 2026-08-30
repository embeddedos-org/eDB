"""EoS eDB KeyValueStore — persistent KV with TTL, prefix scan, bulk ops."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from typing import Any
from .engine import StorageEngine

_CREATE = """
CREATE TABLE IF NOT EXISTS _kv (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    expires_at REAL
)
"""

_EXPIRE_INDEX = "CREATE INDEX IF NOT EXISTS _kv_expires_at_idx ON _kv(expires_at)"

@dataclass
class KVEntry:
    key: str
    value: Any
    expires_at: float | None = None

    def model_dump(self, mode: str = 'python') -> dict:
        return {'key': self.key, 'value': self.value, 'expires_at': self.expires_at}


class KeyValueStore:
    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine
        self._e.execute(_CREATE)
        self._e.execute(_EXPIRE_INDEX)
        self._e.commit()

    def _encode(self, v: Any) -> str:
        return json.dumps(v)

    def _decode(self, s: str) -> Any:
        return json.loads(s)

    def _is_expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and time.time() > expires_at

    def set(self, key: str, value: Any, ttl: float | None = None) -> KVEntry:
        expires_at = time.time() + ttl if ttl is not None else None
        self._e.execute(
            "INSERT OR REPLACE INTO _kv (key, value, expires_at) VALUES (?, ?, ?)",
            (key, self._encode(value), expires_at),
        )
        self._e.commit()
        return KVEntry(key=key, value=value, expires_at=expires_at)

    def get(self, key: str) -> Any | None:
        row = self._e.execute(
            "SELECT value, expires_at FROM _kv WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        if self._is_expired(row["expires_at"]):
            self.delete(key)
            return None
        return self._decode(row["value"])

    def delete(self, key: str) -> bool:
        cur = self._e.execute("DELETE FROM _kv WHERE key = ?", (key,))
        self._e.commit()
        return cur.rowcount > 0

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def list_keys(self, prefix: str = "") -> list[str]:
        now = time.time()
        if prefix:
            rows = self._e.execute(
                "SELECT key FROM _kv WHERE key LIKE ? AND (expires_at IS NULL OR expires_at >= ?)",
                (prefix + "%", now),
            ).fetchall()
        else:
            rows = self._e.execute(
                "SELECT key FROM _kv WHERE expires_at IS NULL OR expires_at >= ?",
                (now,)
            ).fetchall()
        return [r["key"] for r in rows]

    def count(self) -> int:
        now = time.time()
        row = self._e.execute(
            "SELECT COUNT(*) as c FROM _kv WHERE expires_at IS NULL OR expires_at >= ?", 
            (now,)
        ).fetchone()
        return row["c"] if row else 0

    def prune_expired(self) -> int:
        cur = self._e.execute("DELETE FROM _kv WHERE expires_at < ?", (time.time(),))
        self._e.commit()
        return cur.rowcount
        
    def get_many(self, keys: list[str]) -> dict[str, Any]:
        if not keys:
            return {}
        
        placeholders = ",".join(["?"] * len(keys))
        rows = self._e.execute(
            f"SELECT key, value, expires_at FROM _kv WHERE key IN ({placeholders})", 
            tuple(keys)
        ).fetchall()
        
        result = {}
        keys_to_delete = []
        now = time.time()
        
        for r in rows:
            if r["expires_at"] is not None and now > r["expires_at"]:
                keys_to_delete.append(r["key"])
            else:
                result[r["key"]] = self._decode(r["value"])
                
        if keys_to_delete:
            del_placeholders = ",".join(["?"] * len(keys_to_delete))
            self._e.execute("BEGIN TRANSACTION")
            try:
                self._e.execute(f"DELETE FROM _kv WHERE key IN ({del_placeholders})", tuple(keys_to_delete))
                self._e.commit()
            except Exception:
                self._e.execute("ROLLBACK")
                
        return result

    def set_many(self, mapping: dict[str, Any], ttl: float | None = None) -> list[KVEntry]:
        if not mapping:
            return []

        expires_at = time.time() + ttl if ttl is not None else None
        batch = [(k, self._encode(v), expires_at) for k, v in mapping.items()]
        
        self._e.execute("BEGIN TRANSACTION")
        try:
            for args in batch:
                self._e.execute("INSERT OR REPLACE INTO _kv (key, value, expires_at) VALUES (?, ?, ?)", args)
            self._e.commit()
        except Exception as e:
            self._e.execute("ROLLBACK")
            raise e
            
        return [KVEntry(key=k, value=v, expires_at=expires_at) for k, v in mapping.items()]
        
    def clear(self) -> int:
        cur = self._e.execute("DELETE FROM _kv")
        self._e.commit()
        return cur.rowcount