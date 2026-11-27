# SPDX-License-Identifier: MIT
"""Unit tests for the tamper-evident audit log (issue #88 coverage drive).

Covers edb/security/audit.py — previously at ~26% with no dedicated
test module. Pins the hash-chain contract end to end: entries link
to their predecessor (genesis for the first), verification detects
both edited payloads and broken links, and retrieval filters and
pagination behave as the API layer expects.
"""

import hashlib
import sqlite3
import threading

import pytest

from edb.core.engine import StorageEngine
from edb.security.audit import AUDIT_TABLE, AuditLogger


@pytest.fixture
def engine() -> StorageEngine:
    return StorageEngine(":memory:")


@pytest.fixture
def audit(engine) -> AuditLogger:
    return AuditLogger(engine)


def _log_three(audit: AuditLogger) -> list[int]:
    ids = []
    ids.append(audit.log("auth", "login", user_id="u1", username="alice",
                         details={"ip": "10.0.0.1"}, ip_address="10.0.0.1"))
    ids.append(audit.log("query", "select", user_id="u1", username="alice"))
    ids.append(audit.log("admin", "create_user", user_id="root",
                         username="root", details={"target": "bob"}))
    return ids


class TestLogging:
    def test_log_returns_increasing_ids(self, audit):
        ids = _log_three(audit)
        assert ids[0] >= 1
        assert ids[0] < ids[1] < ids[2]

    def test_count_tracks_entries(self, audit):
        assert audit.count() == 0
        _log_three(audit)
        assert audit.count() == 3

    def test_first_entry_links_to_genesis(self, audit, engine):
        _log_three(audit)
        rows = engine.fetchall(
            f'SELECT prev_hash FROM "{AUDIT_TABLE}" ORDER BY id ASC')
        assert rows[0]["prev_hash"] == "genesis"
        # Every later row links to an actual entry hash (checked in
        # full by verify_chain); here: none of them is genesis.
        assert all(r["prev_hash"] != "genesis" for r in rows[1:])


class TestRetrieval:
    def test_get_logs_newest_first_with_fields(self, audit):
        _log_three(audit)
        logs = audit.get_logs()
        assert [entry["action"] for entry in logs] == [
            "create_user", "select", "login"]
        first = logs[-1]
        assert first["event_type"] == "auth"
        assert first["username"] == "alice"
        assert first["details"] == {"ip": "10.0.0.1"}
        assert first["ip_address"] == "10.0.0.1"
        assert len(first["entry_hash"]) == 64
        assert first["hash_version"] == 2

    def test_details_round_trip_and_absence(self, audit):
        _log_three(audit)
        by_action = {e["action"]: e for e in audit.get_logs()}
        assert by_action["create_user"]["details"] == {"target": "bob"}
        assert by_action["select"]["details"] is None
        assert by_action["select"]["ip_address"] is None

    def test_filter_by_event_type(self, audit):
        _log_three(audit)
        logs = audit.get_logs(event_type="auth")
        assert len(logs) == 1
        assert logs[0]["action"] == "login"

    def test_filter_by_user(self, audit):
        _log_three(audit)
        assert len(audit.get_logs(user_id="u1")) == 2
        assert len(audit.get_logs(user_id="root")) == 1
        assert audit.get_logs(user_id="nobody") == []

    def test_filter_by_both(self, audit):
        _log_three(audit)
        logs = audit.get_logs(event_type="query", user_id="u1")
        assert len(logs) == 1
        assert logs[0]["action"] == "select"

    def test_limit_and_offset(self, audit):
        _log_three(audit)
        page1 = audit.get_logs(limit=2, offset=0)
        page2 = audit.get_logs(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 1
        assert page1[-1]["id"] > page2[0]["id"]


class TestVerifyChain:
    def test_empty_log_verifies(self, audit):
        ok, message = audit.verify_chain()
        assert ok is True
        assert "empty" in message

    def test_intact_chain_verifies(self, audit):
        _log_three(audit)
        ok, message = audit.verify_chain()
        assert ok is True
        assert "3 entries" in message

    def test_tampered_payload_detected(self, audit, engine):
        _log_three(audit)
        engine.execute(
            f'UPDATE "{AUDIT_TABLE}" SET action = ? WHERE id = 2',
            ("drop_table",))
        engine.commit()
        ok, message = audit.verify_chain()
        assert ok is False
        assert "Tampered" in message

    def test_tampered_details_detected(self, audit, engine):
        _log_three(audit)
        engine.execute(
            f'UPDATE "{AUDIT_TABLE}" SET details = ? WHERE id = 1',
            ('{"ip": "6.6.6.6"}',))
        engine.commit()
        ok, _ = audit.verify_chain()
        assert ok is False

    def test_broken_link_detected(self, audit, engine):
        _log_three(audit)
        engine.execute(
            f'UPDATE "{AUDIT_TABLE}" SET prev_hash = ? WHERE id = 3',
            ("deadbeef",))
        engine.commit()
        ok, message = audit.verify_chain()
        assert ok is False
        assert "prev_hash mismatch" in message

    def test_deleted_middle_entry_breaks_chain(self, audit, engine):
        _log_three(audit)
        engine.execute(f'DELETE FROM "{AUDIT_TABLE}" WHERE id = 2')
        engine.commit()
        ok, _ = audit.verify_chain()
        assert ok is False

    @pytest.mark.parametrize(
        ("column", "value"), [("username", "admin"), ("ip_address", "6.6.6.6")]
    )
    def test_tampered_username_or_ip_address_detected(self, audit, engine, column, value):
        _log_three(audit)
        engine.execute(f'UPDATE "{AUDIT_TABLE}" SET {column} = ? WHERE id = 1', (value,))
        engine.commit()
        ok, message = audit.verify_chain()
        assert ok is False
        assert "Tampered entry detected at ID 1" in message

    def test_unknown_hash_version_detected(self, audit, engine):
        _log_three(audit)
        engine.execute(f'UPDATE "{AUDIT_TABLE}" SET hash_version = 3 WHERE id = 2')
        engine.commit()
        assert audit.verify_chain() == (False, "Tampered entry detected at ID 2: hash_version 3")

    def test_blob_in_hashed_column_reported_as_tampered(self, audit, engine):
        _log_three(audit)
        engine.execute(f"UPDATE \"{AUDIT_TABLE}\" SET username = X'00' WHERE id = 1")
        engine.commit()
        assert audit.verify_chain() == (False, "Tampered entry detected at ID 1")

    def test_old_format_entry_after_new_ones_still_verifies(self, audit, engine):
        # An older eDB sharing the database still writes version 1 entries.
        _log_three(audit)
        last = engine.fetchone(f'SELECT entry_hash FROM "{AUDIT_TABLE}" ORDER BY id DESC LIMIT 1')
        row = {"timestamp": "2026-01-01T00:00:00+00:00", "event_type": "auth",
               "user_id": "u2", "action": "login", "details": None}
        engine.execute(
            f'INSERT INTO "{AUDIT_TABLE}" (timestamp, event_type, user_id, username, '
            "action, details, ip_address, prev_hash, entry_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["timestamp"], "auth", "u2", "bob", "login", None, None,
             last["entry_hash"], _version_1_hash(row, last["entry_hash"])),
        )
        engine.commit()
        assert audit.verify_chain() == (True, "Audit chain verified: 4 entries intact")


def _version_1_hash(row, prev_hash: str) -> str:
    data = (
        f"{row['timestamp']}|{row['event_type']}|{row['user_id']}|"
        f"{row['action']}|{row['details']}|{prev_hash}"
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class TestLogWrittenBeforeHashVersion:
    def test_old_log_still_verifies_and_new_entries_chain_onto_it(self, engine):
        # The table as it was before hash_version, with two version 1 entries.
        engine.execute(f"""
            CREATE TABLE "{AUDIT_TABLE}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
                user_id TEXT, username TEXT, action TEXT NOT NULL,
                details TEXT, ip_address TEXT,
                prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
            )
        """)
        prev_hash = "genesis"
        for action in ("login", "logout"):
            row = {"timestamp": "2026-01-01T00:00:00+00:00", "event_type": "auth",
                   "user_id": "u1", "action": action, "details": None}
            entry_hash = _version_1_hash(row, prev_hash)
            engine.execute(
                f'INSERT INTO "{AUDIT_TABLE}" (timestamp, event_type, user_id, username, '
                "action, details, ip_address, prev_hash, entry_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["timestamp"], "auth", "u1", "alice", action, None, None,
                 prev_hash, entry_hash),
            )
            prev_hash = entry_hash
        engine.commit()

        audit = AuditLogger(engine)
        assert audit.verify_chain() == (True, "Audit chain verified: 2 entries intact")
        audit.log("auth", "login", user_id="u1", username="alice")
        assert audit.verify_chain() == (True, "Audit chain verified: 3 entries intact")
        versions = engine.fetchall(f'SELECT hash_version FROM "{AUDIT_TABLE}" ORDER BY id')
        assert [row["hash_version"] for row in versions] == [1, 1, 2]

    def test_column_added_by_another_process_meanwhile_is_ignored(self, engine, monkeypatch):
        # Another process adds hash_version between this one's check and its
        # ALTER TABLE, so ALTER TABLE fails with "duplicate column name".
        AuditLogger(engine)
        _hide_hash_version_column(engine, monkeypatch)
        audit = AuditLogger(engine)
        audit.log("auth", "login", user_id="u1")
        assert audit.count() == 1

    def test_other_errors_adding_the_column_are_raised(self, engine, monkeypatch):
        AuditLogger(engine)
        _hide_hash_version_column(engine, monkeypatch)
        execute = engine.execute

        def locked_alter_table(sql, params=()):
            if sql.startswith("ALTER TABLE"):
                raise sqlite3.OperationalError("database is locked")
            return execute(sql, params)

        monkeypatch.setattr(engine, "execute", locked_alter_table)
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            AuditLogger(engine)


def _hide_hash_version_column(engine, monkeypatch):
    """Make the column check miss hash_version, as if it were not added yet."""
    fetchall = engine.fetchall

    def columns_without_hash_version(sql, params=()):
        rows = fetchall(sql, params)
        if sql.startswith("PRAGMA table_info"):
            rows = [row for row in rows if row["name"] != "hash_version"]
        return rows

    monkeypatch.setattr(engine, "fetchall", columns_without_hash_version)


class TestReopen:
    def test_second_logger_sees_existing_chain(self, engine):
        first = AuditLogger(engine)
        first.log("auth", "login", user_id="u1")
        # Constructing a second logger over the same engine (as the
        # API dependencies module does per app state) must neither
        # wipe nor fork the chain.
        second = AuditLogger(engine)
        assert second.count() == 1
        second.log("auth", "logout", user_id="u1")
        ok, _ = second.verify_chain()
        assert ok is True
        assert second.count() == 2


class TestConcurrentLogging:
    def test_concurrent_writers_keep_a_single_chain(self, tmp_path):
        # A file database, because each thread opens its own connection and
        # every thread's ":memory:" database would be a different, empty one.
        audit = AuditLogger(StorageEngine(str(tmp_path / "audit.db")))

        def write():
            for _ in range(50):
                audit.log("query", "select")

        threads = [threading.Thread(target=write) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert audit.count() == 400
        assert audit.verify_chain() == (True, "Audit chain verified: 400 entries intact")
