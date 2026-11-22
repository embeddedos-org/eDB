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


class TestServeConfig:
    """edb serve takes a flag first, then EDB_* variables / .env, then the defaults."""

    @staticmethod
    def _serve(monkeypatch, tmp_path, argv, env=None, dotenv=None):
        captured = {}

        class FakeUvicorn:
            @staticmethod
            def run(app, **kwargs):
                captured.update(kwargs)

        monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
        monkeypatch.chdir(tmp_path)  # .env is read from the working directory
        for key in ("EDB_DB_PATH", "EDB_API_HOST", "EDB_API_PORT"):
            # setenv first so monkeypatch restores the key after the CLI sets it
            monkeypatch.setenv(key, "")
            monkeypatch.delenv(key)
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        if dotenv is not None:
            (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
        run_cli(monkeypatch, ["serve", *argv])
        return captured

    def test_flag_db_wins_over_exported_env(self, monkeypatch, tmp_path, capsys):
        self._serve(monkeypatch, tmp_path, ["--db", "from_flag.db"],
                    env={"EDB_DB_PATH": "from_env.db"})
        assert os.environ["EDB_DB_PATH"] == "from_flag.db"
        assert "Database: from_flag.db" in capsys.readouterr().out

    def test_env_used_when_no_flags(self, monkeypatch, tmp_path, capsys):
        captured = self._serve(monkeypatch, tmp_path, [], env={
            "EDB_DB_PATH": "from_env.db", "EDB_API_HOST": "0.0.0.0", "EDB_API_PORT": "9002",
        })
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 9002
        assert os.environ["EDB_DB_PATH"] == "from_env.db"
        out = capsys.readouterr().out
        assert "Starting eDB API server on 0.0.0.0:9002" in out
        assert "Database: from_env.db" in out

    def test_dotenv_used_when_no_flags(self, monkeypatch, tmp_path, capsys):
        captured = self._serve(monkeypatch, tmp_path, [], dotenv=(
            "EDB_DB_PATH=from_dotenv.db\nEDB_API_HOST=0.0.0.0\nEDB_API_PORT=9001\n"
        ))
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 9001
        assert os.environ["EDB_DB_PATH"] == "from_dotenv.db"
        assert "Database: from_dotenv.db" in capsys.readouterr().out

    def test_flags_win_over_dotenv(self, monkeypatch, tmp_path):
        captured = self._serve(
            monkeypatch, tmp_path,
            ["--host", "127.0.0.2", "--port", "9100", "--db", "from_flag.db"],
            dotenv="EDB_DB_PATH=from_dotenv.db\nEDB_API_HOST=0.0.0.0\nEDB_API_PORT=9001\n",
        )
        assert captured["host"] == "127.0.0.2"
        assert captured["port"] == 9100
        assert os.environ["EDB_DB_PATH"] == "from_flag.db"

    def test_defaults_without_flags_env_or_dotenv(self, monkeypatch, tmp_path, capsys):
        captured = self._serve(monkeypatch, tmp_path, [])
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8000
        assert os.environ["EDB_DB_PATH"] == "edb_data.db"
        assert "Database: edb_data.db" in capsys.readouterr().out


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


    @staticmethod
    def _session(monkeypatch, tmp_db_path, capsys, lines):
        inputs = iter([*lines, "exit"])

        def fake_input(prompt=""):
            return next(inputs)

        monkeypatch.setattr("builtins.input", fake_input)
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        return capsys.readouterr().out

    def test_shell_shows_header_and_zero_rows_for_an_empty_select(
        self, monkeypatch, tmp_db_path, capsys
    ):
        out = self._session(monkeypatch, tmp_db_path, capsys, [
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)",
            "SELECT id, name FROM products WHERE id = 2",
        ])
        assert "  id | name\n" in out
        assert "(0 rows)" in out
        assert "affected: -1" not in out

    def test_shell_reports_zero_affected_for_ddl(self, monkeypatch, tmp_db_path, capsys):
        out = self._session(monkeypatch, tmp_db_path, capsys, [
            "CREATE TABLE t (x INTEGER)",
        ])
        assert "OK (affected: 0)" in out
        assert "affected: -1" not in out

    def test_shell_still_reports_rows_and_affected_counts(
        self, monkeypatch, tmp_db_path, capsys
    ):
        out = self._session(monkeypatch, tmp_db_path, capsys, [
            "CREATE TABLE t (x INTEGER)",
            "INSERT INTO t VALUES (1), (2)",
            "SELECT x FROM t ORDER BY x",
            "DELETE FROM t WHERE x = 99",
        ])
        assert "OK (affected: 2)" in out
        assert "  x\n" in out and "  1\n" in out and "  2\n" in out
        assert "(2 rows)" in out
        assert out.count("OK (affected: 0)") == 2  # CREATE TABLE and the DELETE


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

    def test_restore_ignores_a_stale_wal_of_the_old_database(self, monkeypatch, tmp_path):
        from edb.core.database import Database

        backup = str(tmp_path / "backup.db")
        target = str(tmp_path / "live.db")
        db = Database(target)
        db.kv.set("k", "backup value")
        db.engine.backup(backup)
        db.close()

        # Leave a newer write in live.db-wal, as an unclean shutdown would.
        db = Database(target)
        db.kv.set("k", "newer value")
        stale_wal = (tmp_path / "live.db-wal").read_bytes()
        db.close()
        (tmp_path / "live.db-wal").write_bytes(stale_wal)

        run_cli(monkeypatch, ["restore", "--source", backup, "--db", target])
        restored = Database(target)
        assert restored.kv.get("k") == "backup value"
        restored.close()

    def test_failed_restore_leaves_the_old_database_intact(self, monkeypatch, tmp_path):
        from edb.core.database import Database

        target = str(tmp_path / "live.db")
        db = Database(target)
        db.close()

        # Keep a write that exists only in live.db-wal, not yet in live.db.
        db = Database(target)
        db.kv.set("k", "only in the wal")
        main_bytes = (tmp_path / "live.db").read_bytes()
        wal_bytes = (tmp_path / "live.db-wal").read_bytes()
        db.close()
        (tmp_path / "live.db").write_bytes(main_bytes)
        (tmp_path / "live.db-wal").write_bytes(wal_bytes)

        missing = str(tmp_path / "missing.db")
        with pytest.raises(FileNotFoundError):
            run_cli(monkeypatch, ["restore", "--source", missing, "--db", target])

        db = Database(target)
        assert db.kv.get("k") == "only in the wal"
        db.close()
        assert list(tmp_path.glob("*.restore-tmp")) == []


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


class TestShellDotCommandsAndEdges:
    """The shell branches the first cli pass left uncovered: the dot
    commands against a populated database, empty input, statements with
    no result rows, rows without columns, and Ctrl-C."""

    def _seeded_db(self, tmp_db_path):
        from edb.core.database import Database

        db = Database(tmp_db_path)
        db.docs.create_collection("notes")
        db.close()

    def test_shell_dot_commands_empty_line_and_ddl(self, monkeypatch, tmp_db_path, capsys):
        self._seeded_db(tmp_db_path)
        inputs = iter(
            [
                "",
                "CREATE TABLE t1 (id INTEGER)",
                ".tables",
                ".collections",
                ".graph",
                "INSERT INTO t1 VALUES (1)",
                "exit",
            ]
        )
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        out = capsys.readouterr().out
        assert "t1" in out  # .tables listed the user table
        assert "notes" in out  # .collections listed the seeded collection
        assert "Nodes: 0, Edges: 0" in out  # .graph summary line
        assert "OK (affected:" in out  # DDL/DML take the no-rows branch

    def test_shell_keyboard_interrupt_exits_cleanly(self, monkeypatch, tmp_db_path, capsys):
        def interrupting_input(prompt=""):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", interrupting_input)
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        out = capsys.readouterr().out
        assert "Bye!" in out  # the finally block still ran

    def test_shell_rows_without_columns_skip_the_header(self, monkeypatch, tmp_db_path, capsys):
        from edb.core.relational import QueryResult

        class FakeSQL:
            @staticmethod
            def execute_raw(query):
                return QueryResult(rows=[{"a": 1}], columns=[])

        class FakeDB:
            sql = FakeSQL()

            def __init__(self, path):
                pass

            def close(self):
                pass

        monkeypatch.setattr("edb.core.database.Database", FakeDB)
        inputs = iter(["SELECT mystery", "exit"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
        run_cli(monkeypatch, ["shell", "--db", tmp_db_path])
        out = capsys.readouterr().out
        assert "  1" in out  # the row printed with no header above it
        assert "(1 rows)" in out


class TestAdminCreateDuplicate:
    def test_admin_create_reports_existing_username(self, monkeypatch, tmp_db_path, capsys):
        from edb.auth.models import Role, UserCreate
        from edb.auth.users import UserManager
        from edb.core.database import Database

        db = Database(tmp_db_path)
        um = UserManager(db.engine)
        um.create_user(
            UserCreate(username="root", password="Str0ng!Pass1", role=Role.READ_ONLY),
            skip_password_check=True,
        )
        db.close()

        run_cli(
            monkeypatch,
            ["admin", "create", "--username", "root", "--password", "Str0ng!Pass1",
             "--db", tmp_db_path],
        )
        out = capsys.readouterr().out
        # ensure_admin_exists -> create_user raises ValueError; the CLI
        # catches it and reports instead of crashing.
        assert "already exists" in out
        assert "created successfully" not in out

    def test_admin_create_when_another_admin_exists(self, monkeypatch, tmp_db_path, capsys):
        from edb.auth.users import UserManager
        from edb.core.database import Database

        db = Database(tmp_db_path)
        UserManager(db.engine).ensure_admin_exists("alice", "Str0ng!Pass1")
        db.close()

        run_cli(
            monkeypatch,
            ["admin", "create", "--username", "bob", "--password", "Str0ng!Pass2",
             "--db", tmp_db_path],
        )
        out = capsys.readouterr().out
        assert "created successfully" not in out
        assert "An admin user already exists; 'bob' was not created." in out


class TestMainGuard:
    def test_module_runs_main_as_script(self, monkeypatch, capsys):
        import runpy

        monkeypatch.setattr(sys, "argv", ["edb", "version"])
        runpy.run_module("edb.cli", run_name="__main__")
        assert f"eDB v{__version__}" in capsys.readouterr().out
