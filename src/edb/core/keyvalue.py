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
        if prefix:
            rows = self._e.execute(
                "SELECT key, expires_at FROM _kv WHERE key LIKE ?",
                (prefix + "%",),
            ).fetchall()
        else:
            rows = self._e.execute(
                "SELECT key, expires_at FROM _kv"
            ).fetchall()
        return [
            r["key"] for r in rows if not self._is_expired(r["expires_at"])
        ]

    def count(self) -> int:
        return len(self.list_keys())

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        result = {}
        for k in keys:
            v = self.get(k)
            if v is not None:
                result[k] = v
        return result

    def set_many(self, mapping: dict[str, Any], ttl: float | None = None) -> list[KVEntry]:
        return [self.set(k, v, ttl) for k, v in mapping.items()]

    def clear(self) -> int:
        cur = self._e.execute("DELETE FROM _kv")
        self._e.commit()
        return cur.rowcount
