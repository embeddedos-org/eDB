"""eDB CLI entry point.

Provides commands: serve, init, shell, backup, restore, admin, version
"""

from __future__ import annotations

import argparse
import getpass


def main() -> None:
    parser = argparse.ArgumentParser(prog="edb", description="eDB: Unified Multi-Model Database")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    serve_p = subparsers.add_parser("serve", help="Start the eDB API server")
    # No defaults here: an omitted flag falls back to EDB_API_HOST, EDB_API_PORT
    # and EDB_DB_PATH (environment or .env), then to the EDBConfig defaults.
    serve_p.add_argument("--host", default=None, help="Default: EDB_API_HOST or 127.0.0.1")
    serve_p.add_argument("--port", type=int, default=None, help="Default: EDB_API_PORT or 8000")
    serve_p.add_argument("--reload", action="store_true")
    serve_p.add_argument("--db", default=None, help="Default: EDB_DB_PATH or edb_data.db")

    init_p = subparsers.add_parser("init", help="Initialize a new eDB database")
    init_p.add_argument("--db", default="edb_data.db")

    shell_p = subparsers.add_parser("shell", help="Open interactive SQL shell")
    shell_p.add_argument("--db", default="edb_data.db")

    backup_p = subparsers.add_parser("backup", help="Backup the database")
    backup_p.add_argument("--db", default="edb_data.db")
    backup_p.add_argument("--dest", required=True, help="Backup destination path")

    restore_p = subparsers.add_parser("restore", help="Restore database from backup")
    restore_p.add_argument("--source", required=True, help="Backup file to restore from")
    restore_p.add_argument("--db", default="edb_data.db", help="Target database path")

    admin_p = subparsers.add_parser("admin", help="Admin user management")
    admin_sub = admin_p.add_subparsers(dest="admin_command", help="Admin commands")
    admin_create_p = admin_sub.add_parser("create", help="Create an admin user")
    admin_create_p.add_argument("--username", required=True, help="Admin username")
    admin_create_p.add_argument("--password", default=None, help="Admin password (prompted if omitted)")
    admin_create_p.add_argument("--db", default="edb_data.db")

    subparsers.add_parser("version", help="Show eDB version")

    args = parser.parse_args()

    if args.command == "serve":
        _cmd_serve(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "shell":
        _cmd_shell(args)
    elif args.command == "backup":
        _cmd_backup(args)
    elif args.command == "restore":
        _cmd_restore(args)
    elif args.command == "admin":
        if args.admin_command == "create":
            _cmd_admin_create(args)
        else:
            admin_p.print_help()
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()


def _cmd_serve(args: argparse.Namespace) -> None:
    import os

    from edb.config import EDBConfig

    # A flag on the command line wins; otherwise use what the app itself would
    # read (EDB_* environment variables, then .env, then the defaults). The
    # secrets are passed in only so that this lookup does not generate and log
    # throwaway ones; the server loads its own configuration.
    config = EDBConfig(jwt_secret="unused", encryption_key="unused")
    host = args.host if args.host is not None else config.api_host
    port = args.port if args.port is not None else config.api_port
    db_path = args.db if args.db is not None else config.db_path

    # create_app() builds its EDBConfig from the environment, so pass the
    # resolved values on; an exported EDB_DB_PATH must not override --db.
    os.environ["EDB_DB_PATH"] = db_path
    os.environ["EDB_API_HOST"] = host
    os.environ["EDB_API_PORT"] = str(port)

    import uvicorn

    print(f"🚀 Starting eDB API server on {host}:{port}")
    print(f"📁 Database: {db_path}")
    print(f"📖 API docs: http://{host}:{port}/docs")
    uvicorn.run(
        "edb.api.app:create_app",
        host=host,
        port=port,
        reload=args.reload,
        factory=True,
    )


def _cmd_init(args: argparse.Namespace) -> None:
    from edb.core.database import Database
    from edb.security.audit import AuditLogger

    print(f"📦 Initializing eDB database at: {args.db}")
    db = Database(args.db)
    AuditLogger(db.engine)
    db.close()
    print("✅ Database initialized successfully")
    print("   Run 'edb admin create --username <name>' to create an admin user.")


def _cmd_admin_create(args: argparse.Namespace) -> None:
    from edb.auth.users import UserManager, validate_password_strength
    from edb.core.database import Database

    password = args.password
    if password is None:
        password = getpass.getpass("Enter admin password: ")
        password_confirm = getpass.getpass("Confirm admin password: ")
        if password != password_confirm:
            print("❌ Passwords do not match.")
            return

    try:
        validate_password_strength(password)
    except ValueError as e:
        print(f"❌ {e}")
        return

    db = Database(args.db)
    try:
        um = UserManager(db.engine)
        if um.ensure_admin_exists(username=args.username, password=password):
            print(f"✅ Admin user '{args.username}' created successfully.")
        else:
            print(f"❌ An admin user already exists; '{args.username}' was not created.")
    except ValueError as e:
        print(f"❌ {e}")
    finally:
        db.close()


def _cmd_shell(args: argparse.Namespace) -> None:
    from edb.core.database import Database

    db = Database(args.db)
    print(f"🔗 Connected to: {args.db}")
    print("   Type SQL or 'exit'. Use '.tables', '.collections', '.graph'")
    print()

    try:
        while True:
            try:
                query = input("edb> ").strip()
            except EOFError:
                break

            if not query:
                continue
            if query.lower() in ("exit", "quit", "\\q"):
                break
            if query == ".tables":
                for t in db.sql.list_tables():
                    print(f"  {t}")
                continue
            if query == ".collections":
                for c in db.docs.list_collections():
                    print(f"  {c}")
                continue
            if query == ".graph":
                print(f"  Nodes: {db.graph.node_count()}, Edges: {db.graph.edge_count()}")
                continue

            try:
                result = db.sql.execute_raw(query)
                # A statement that returns rows has columns even when no row
                # matched, so print the header and "(0 rows)" for it.
                if result.rows or result.columns:
                    if result.columns:
                        print("  " + " | ".join(result.columns))
                        print("  " + "-+-".join("-" * max(len(c), 8) for c in result.columns))
                    for row in result.rows:
                        print("  " + " | ".join(str(v) for v in row.values()))
                    print(f"  ({result.row_count} rows)")
                else:
                    # sqlite3 reports rowcount -1 for DDL such as CREATE TABLE.
                    print(f"  OK (affected: {max(result.affected_rows, 0)})")
            except Exception as e:
                print(f"  Error: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        db.close()
        print("\n👋 Bye!")


def _cmd_backup(args: argparse.Namespace) -> None:
    from edb.core.database import Database

    db = Database(args.db)
    db.engine.backup(args.dest)
    db.close()
    print(f"✅ Backup created: {args.dest}")


def _cmd_restore(args: argparse.Namespace) -> None:
    import os
    import shutil

    # Copy to a temporary file next to the target first: if the copy fails, the old
    # database (including writes still in its -wal) is left untouched.
    tmp_path = args.db + ".restore-tmp"
    try:
        shutil.copy2(args.source, tmp_path)
        os.replace(tmp_path, args.db)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    # A -wal/-shm left by the old database would be replayed on top of the restored
    # file the next time it is opened, so remove them only now that it is in place.
    for suffix in ("-wal", "-shm"):
        if os.path.exists(args.db + suffix):
            os.remove(args.db + suffix)
    print(f"✅ Database restored from {args.source} to {args.db}")


def _cmd_version() -> None:
    from edb import __version__

    print(f"eDB v{__version__}")


if __name__ == "__main__":
    main()

