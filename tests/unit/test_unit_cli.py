# SPDX-License-Identifier: MIT
"""Unit tests for the eDB CLI (issue #99 coverage drive).

Covers edb/cli.py — previously 0% covered — including every subcommand's
happy path and the main error branches (password mismatch, weak password,
missing required args).
"""

import os
import sqlite3
import sys

import pytest

import edb.cli as cli_mod
from edb import __version__


def run_cli(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["edb", *argv])
    cli_mod.main()


class TestVersionAndHelp:
    def test_version_prints(self, monkeypatch, capsys):
        run_cli(monkeypatch, ["version"])
        out = capsys.readouterr().out
        assert f"eDB v{__version__}" in out

    def test_no_command_prints_help(self, monkeypatch, capsys):
        run_cli(monkeypatch, [])
        out = capsys.readouterr().out
        assert "usage: edb" in out

    def test_admin_without_subcommand_prints_help(self, monkeypatch, capsys):
        run_cli(monkeypatch, ["admin"])
        out = capsys.readouterr().out
        assert "create" in out

    def test_backup_requires_dest(self, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, ["backup", "--db", "x.db"])
        assert exc.value.code == 2

    def test_restore_requires_source(self, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, ["restore", "--db", "x.db"])
        assert exc.value.code == 2


class TestInit:
    def test_init_creates_database(self, monkeypatch, tmp_path, capsys):
        db_path = str(tmp_path / "fresh.db")
        run_cli(monkeypatch, ["init", "--db", db_path])
        out = capsys.readouterr().out
        assert "Database initialized successfully" in out
        assert os.path.exists(db_path)
        # The Database facade tables were created.
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert tables, "init should create the subsystem tables"


class TestServe:
    def test_serve_invokes_uvicorn_with_args(self, monkeypatch, tmp_path, capsys):
        captured = {}

        class FakeUvicorn:
            @staticmethod
            def run(app, **kwargs):
                captured["app"] = app
                captured.update(kwargs)

        monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
        for key in ("EDB_DB_PATH", "EDB_API_HOST", "EDB_API_PORT"):
            monkeypatch.delenv(key, raising=False)
        db_path = str(tmp_path / "srv.db")
        run_cli(monkeypatch, ["serve", "--host", "0.0.0.0", "--port", "9000", "--db", db_path])
        assert captured["app"] == "edb.api.app:create_app"
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 9000
        assert captured["factory"] is True
        assert os.environ["EDB_DB_PATH"] == db_path
        assert os.environ["EDB_API_HOST"] == "0.0.0.0"
        assert os.environ["EDB_API_PORT"] == "9000"
        assert "Starting eDB API server on 0.0.0.0:9000" in capsys.readouterr().out

    def test_serve_defaults(self, monkeypatch, tmp_path):
        captured = {}

        class FakeUvicorn:
            @staticmethod
            def run(app, **kwargs):
                captured.update(kwargs)

        monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
        for key in ("EDB_DB_PATH", "EDB_API_HOST", "EDB_API_PORT"):
            monkeypatch.delenv(key, raising=False)
        run_cli(monkeypatch, ["serve"])
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8000
        assert captured["reload"] is False


class TestShell:
    def test_shell_exits_on_eof(self, monkeypatch, tmp_db_path, capsys):
        def fake_input(prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", fake_input)
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        out = capsys.readouterr().out
        assert f"Connected to: {tmp_db_path}" in out
        assert "Bye!" in out

    def test_shell_handles_dot_commands_and_sql(self, monkeypatch, tmp_db_path, capsys):
        inputs = iter([".tables", "SELECT 1", "exit"])

        def fake_input(prompt=""):
            return next(inputs)

        monkeypatch.setattr("builtins.input", fake_input)
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        out = capsys.readouterr().out
        assert "1" in out  # SELECT 1 result row printed

    def test_shell_reports_sql_errors(self, monkeypatch, tmp_db_path, capsys):
        inputs = iter(["SELECT * FROM no_such_table_xyz", "quit"])

        def fake_input(prompt=""):
            return next(inputs)

        monkeypatch.setattr("builtins.input", fake_input)
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        assert "Error:" in capsys.readouterr().out


class TestBackupRestore:
    def test_backup_and_restore_round_trip(self, monkeypatch, tmp_db_path, tmp_path, capsys):
        from edb.core.database import Database

        db = Database(tmp_db_path)
        db.kv.set("k", "v")
        db.close()

        dest = str(tmp_path / "backup.db")
        run_cli(monkeypatch, ["backup", "--db", tmp_db_path, "--dest", dest])
        assert f"Backup created: {dest}" in capsys.readouterr().out
        assert os.path.exists(dest)

        restored = str(tmp_path / "restored.db")
        run_cli(monkeypatch, ["restore", "--source", dest, "--db", restored])
        assert "Database restored" in capsys.readouterr().out
        db2 = Database(restored)
        assert db2.kv.get("k") == "v"
        db2.close()


class TestAdminCreate:
    def test_admin_create_with_password_flag(self, monkeypatch, tmp_db_path, capsys):
        run_cli(
            monkeypatch,
            ["admin", "create", "--username", "root", "--password", "Str0ng!Pass1", "--db", tmp_db_path],
        )
        out = capsys.readouterr().out
        assert "Admin user 'root' created successfully" in out

    def test_admin_create_prompts_when_no_password(self, monkeypatch, tmp_db_path, capsys):
        import getpass

        monkeypatch.setattr(getpass, "getpass", lambda prompt="": "Str0ng!Pass1")
        run_cli(monkeypatch, ["admin", "create", "--username", "prompted", "--db", tmp_db_path])
        assert "Admin user 'prompted' created successfully" in capsys.readouterr().out

    def test_admin_create_password_mismatch(self, monkeypatch, tmp_db_path, capsys):
        import getpass

        answers = iter(["Str0ng!Pass1", "Different!Pass2"])
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
        run_cli(monkeypatch, ["admin", "create", "--username", "nope", "--db", tmp_db_path])
        assert "Passwords do not match" in capsys.readouterr().out

    def test_admin_create_weak_password_rejected(self, monkeypatch, tmp_db_path, capsys):
        run_cli(
            monkeypatch,
            ["admin", "create", "--username", "weak", "--password", "password", "--db", tmp_db_path],
        )
        out = capsys.readouterr().out
        assert "Password too weak" in out
