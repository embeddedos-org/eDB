# eDB — Embedded Multi-Model Database

[![CI](https://github.com/embeddedos-org/eDB/actions/workflows/ci.yml/badge.svg)](https://github.com/embeddedos-org/eDB/actions/workflows/ci.yml)
[![CodeQL](https://github.com/embeddedos-org/eDB/actions/workflows/codeql.yml/badge.svg)](https://github.com/embeddedos-org/eDB/actions/workflows/codeql.yml)
[![Scorecard](https://github.com/embeddedos-org/eDB/actions/workflows/scorecard.yml/badge.svg)](https://github.com/embeddedos-org/eDB/actions/workflows/scorecard.yml)
[![Release](https://github.com/embeddedos-org/eDB/actions/workflows/release.yml/badge.svg)](https://github.com/embeddedos-org/eDB/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

eDB is an embedded multi-model database. A Python engine (built on SQLite)
exposes relational (SQL), document, key-value, graph, and full-text-search
interfaces behind one handle, served either as a library, a FastAPI HTTP API, or
through a React/TypeScript database-manager UI. It is part of the
[EmbeddedOS (EoS)](https://github.com/embeddedos-org) ecosystem.

## Features

Observed in the source tree (`src/edb/`):

- **Multi-model core** — relational, document, key-value, graph, and full-text
  search engines (`core/relational.py`, `core/document.py`, `core/keyvalue.py`,
  `core/graph.py`, `core/fts.py`). The engine is backed by SQLite
  (WAL journaling; FTS5 for full-text search).
- **Transactions** — a `db.transaction()` context manager using SQLite
  savepoints, with `commit`/`rollback` (`core/engine.py`, `core/database.py`).
- **HTTP API** — a FastAPI/uvicorn server (`api/app.py`) launched via
  `edb serve`.
- **Auth & security** — JWT handling, RBAC, users, and a token blacklist
  (`auth/`), plus encryption, audit logging, and input validation
  (`security/`).
- **eBot query assistant** — natural-language-to-query translation
  (`ebot/`). The default provider is rule-based; an LLM backend is optional and
  requires the `ebot` extra (`openai`).
- **Web UI** — a React 19 / TypeScript front-end (`src/`, `index.html`) with a
  SQL editor, table browser, and eBot sidebar, built with Vite and tested with
  Vitest.

## What's inside

| Path | Contents |
|------|----------|
| `src/edb/` | Python engine: `core/`, `query/`, `api/`, `auth/`, `security/`, `ebot/`, `cli.py` |
| `src/` (`.tsx`) | React/TypeScript UI: `components/`, `hooks/`, `App.tsx` |
| `browser/` | Standalone `edb.html` browser view |
| `examples/` | `quickstart.py` demonstrating the three data models |
| `docs/` | `getting-started.md` and reference material |
| `tests/` | unit, functional, integration, performance, simulation |

## Install & run (Python engine)

Requires Python 3.11+.

```bash
pip install -e ".[dev]"      # add ",ebot" for the optional LLM backend

edb init                     # initialize a database file (default edb_data.db)
edb serve                    # start the FastAPI server (default 127.0.0.1:8000)
edb shell                    # interactive SQL shell
```

Other CLI commands: `backup`, `restore`, `admin create`, `version`
(run `edb --help`).

### Library use

```python
from edb.core.database import Database
from edb.core.models import ColumnDefinition, ColumnType, TableSchema

db = Database(":memory:")                       # or a file path
db.sql.create_table(TableSchema(
    name="employees",
    columns=[
        ColumnDefinition(name="id", col_type=ColumnType.INTEGER, primary_key=True),
        ColumnDefinition(name="name", col_type=ColumnType.TEXT, nullable=False),
    ],
))
db.sql.insert("employees", {"id": 1, "name": "Alice"})
db.docs.insert("projects", {"name": "eDB", "status": "active"})
db.kv.set("config:version", "3.0.1")
print(db.sql.select("employees", where={"name": "Alice"}).rows)
```

See `examples/quickstart.py` for relational, document, key-value, and
cross-model transaction usage.

## Web UI

Requires Node.js. The UI talks to the eDB HTTP API.

```bash
npm install
npm run dev        # Vite dev server on port 5178
npm run build      # tsc && vite build
npm run preview
```

## Test

```bash
pytest             # Python engine tests (testpaths = tests)
npm test           # UI tests (vitest run)
```

## Documentation

See `docs/getting-started.md` and the rest of `docs/`.

## License

MIT — see [LICENSE](LICENSE).

Part of [embeddedos-org](https://github.com/embeddedos-org).
