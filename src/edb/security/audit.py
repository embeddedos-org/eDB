"""Tamper-resistant audit logging for eDB.

Records all queries, auth events, and admin actions with hash-chain
verification to detect tampering.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from edb.core.engine import StorageEngine

AUDIT_TABLE = "_edb_audit_log"

# How entry_hash is computed; stored per entry so older logs still verify.
# 1: "|"-joined text without username and ip_address (logs written before 2).
# 2: a JSON array of every stored field, so none can be changed unnoticed.
HASH_VERSION = 2
_HASHED_FIELDS = (
    "timestamp",
    "event_type",
    "user_id",
    "username",
    "action",
    "details",
    "ip_address",
)


class AuditLogger:
    """Append-only audit log with hash chain verification."""

    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine
        # FastAPI runs sync routes in a thread pool, so two requests can log at
        # once. Reading the last hash and inserting the next entry must not
        # interleave, or both entries chain to the same predecessor and
        # verify_chain() reports the log as tampered.
        self._lock = threading.Lock()
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._engine.execute(f"""
            CREATE TABLE IF NOT EXISTS "{AUDIT_TABLE}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_id TEXT,
                username TEXT,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL,
                hash_version INTEGER NOT NULL DEFAULT 1
            )
        """)
        columns = {
            row["name"] for row in self._engine.fetchall(f'PRAGMA table_info("{AUDIT_TABLE}")')
        }
        if "hash_version" not in columns:
            # A log created before hash_version existed: its entries are version 1.
            try:
                self._engine.execute(
                    f'ALTER TABLE "{AUDIT_TABLE}" ADD COLUMN hash_version INTEGER NOT NULL DEFAULT 1'
                )
            except sqlite3.OperationalError as e:
                # Another process opening the same log added it in the meantime.
                if "duplicate column name" not in str(e):
                    raise
        self._engine.commit()

    def log(
        self,
        event_type: str,
        action: str,
        user_id: str | None = None,
        username: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> int:
        """Log an audit event. Returns the entry ID."""
        details_json = json.dumps(details) if details else None
        with self._lock:
            timestamp = datetime.now(UTC).isoformat()
            prev_hash = self._get_last_hash()
            entry = {
                "timestamp": timestamp,
                "event_type": event_type,
                "user_id": user_id,
                "username": username,
                "action": action,
                "details": details_json,
                "ip_address": ip_address,
            }
            entry_hash = self._hash(entry, prev_hash, HASH_VERSION)

            cursor = self._engine.execute(
                f"""INSERT INTO "{AUDIT_TABLE}"
                (timestamp, event_type, user_id, username, action,
                 details, ip_address, prev_hash, entry_hash, hash_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    event_type,
                    user_id,
                    username,
                    action,
                    details_json,
                    ip_address,
                    prev_hash,
                    entry_hash,
                    HASH_VERSION,
                ),
            )
            self._engine.commit()
            return cursor.lastrowid or 0

    def get_logs(
        self,
        event_type: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries with optional filtering."""
        sql = f'SELECT * FROM "{AUDIT_TABLE}"'
        params: list[Any] = []
        conditions = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._engine.fetchall(sql, tuple(params))
        return [self._row_to_dict(row) for row in rows]

    def verify_chain(self) -> tuple[bool, str]:
        """Verify the integrity of the audit log hash chain.

        Returns (is_valid, message).
        """
        rows = self._engine.fetchall(f'SELECT * FROM "{AUDIT_TABLE}" ORDER BY id ASC')
        if not rows:
            return True, "Audit log is empty"

        prev_hash = "genesis"
        for row in rows:
            version = row["hash_version"]
            if version not in (1, HASH_VERSION):
                return False, f"Tampered entry detected at ID {row['id']}: hash_version {version}"
            if row["prev_hash"] != prev_hash:
                return False, f"Chain broken at entry {row['id']}: prev_hash mismatch"
            if row["entry_hash"] != self._hash(row, prev_hash, version):
                return False, f"Tampered entry detected at ID {row['id']}"

            prev_hash = row["entry_hash"]

        return True, f"Audit chain verified: {len(rows)} entries intact"

    def count(self) -> int:
        """Count total audit log entries."""
        row = self._engine.fetchone(f'SELECT COUNT(*) as cnt FROM "{AUDIT_TABLE}"')
        return row["cnt"] if row else 0

    @staticmethod
    def _hash(entry: Any, prev_hash: str, version: int) -> str:
        """Hash an entry (a dict or a row) the way its hash_version says."""
        if version == 1:
            data = (
                f"{entry['timestamp']}|{entry['event_type']}|{entry['user_id']}|"
                f"{entry['action']}|{entry['details']}|{prev_hash}"
            )
        else:
            # log() never stores a BLOB; one written into a hashed column is
            # hashed as {"bytes": hex}, so it is reported as tampered instead of
            # making json.dumps() raise.
            data = json.dumps(
                [entry[field] for field in _HASHED_FIELDS] + [prev_hash],
                default=lambda value: {"bytes": value.hex()},
            )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _get_last_hash(self) -> str:
        row = self._engine.fetchone(
            f'SELECT entry_hash FROM "{AUDIT_TABLE}" ORDER BY id DESC LIMIT 1'
        )
        return row["entry_hash"] if row else "genesis"

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "event_type": row["event_type"],
            "user_id": row["user_id"],
            "username": row["username"],
            "action": row["action"],
            "details": json.loads(row["details"]) if row["details"] else None,
            "ip_address": row["ip_address"],
            "entry_hash": row["entry_hash"],
        }
