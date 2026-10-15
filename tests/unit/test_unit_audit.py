# SPDX-License-Identifier: MIT
"""Unit tests for the tamper-evident audit log (issue #88 coverage drive).

Covers edb/security/audit.py — previously at ~26% with no dedicated
test module. Pins the hash-chain contract end to end: entries link
to their predecessor (genesis for the first), verification detects
both edited payloads and broken links, and retrieval filters and
pagination behave as the API layer expects.
"""

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
