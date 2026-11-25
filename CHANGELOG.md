# Changelog

## [Unreleased]

### Added

- `GET /graph/nodes` and `GraphStore.find_nodes()` take an `offset`, so nodes past the 1000-node
  `limit` can be read. Nodes are returned in the order they were added.

### Fixed

- `edb serve` reads `EDB_DB_PATH`, `EDB_API_HOST` and `EDB_API_PORT` from the environment and `.env`
  when `--db`, `--host` or `--port` is not given, and a flag that is given wins. Before, `--host` and
  `--port` always fell back to `127.0.0.1:8000`, a `.env` database path was replaced by `edb_data.db`,
  and an exported `EDB_DB_PATH` silently overrode `--db` while the startup banner showed the `--db` path.
- `RelationalStore.insert_many()` binds every row's values by column name. It used each row's own
  key order with the first row's column list, so `[{"a": 1, "b": 2}, {"b": 3, "a": 4}]` stored the
  second row as `a=3, b=4`. A row whose columns differ from the first row's now raises `ValueError`
  instead of binding values to the wrong columns.
- `KeyValueStore.list_keys(prefix)` (and `GET /kv/keys?prefix=`, the `kv list` query) now matches the
  prefix literally. It used SQL `LIKE`, so `_` and `%` in the prefix acted as wildcards and ASCII
  letters matched case-insensitively: `user_` also returned `userX`, `users` and `User_2`. The scan is
  now a key range (`key >= prefix AND key < next`), which also uses the key index.
- `FullTextSearch.index_document()` indexes a field that holds `None` as empty text. It used `str()`,
  so the field was stored as the word `None`: a search for `none` matched the document and its result
  reported the field as `"None"` instead of `""`.
- `GraphStore.add_node()` for an existing `node_id` updates the node in place. It used
  `INSERT OR REPLACE`, which gave the node a new rowid and moved it to the end of `find_nodes()`, so a
  client paging through it could skip one node and see another twice.
- `RelationalStore.create_table()` (and `POST /sql/tables`, the `sql create_table` query) now writes
  `ColumnDefinition.default` into the table as a `DEFAULT` clause. It was ignored, so a row inserted
  without that column got `NULL` instead of the default. Text, numbers, booleans and bytes are
  accepted; any other default is rejected with `ValueError` before the table is created.
- `RelationalStore.select()`, `update()` and `delete()` (and the `/sql` table routes and `sql` queries
  that use them) now match a `None` value in `where` against `NULL`. They wrote `col = ?` with a
  `None` parameter, which is never true in SQL, so `where={"age": None}` matched no rows. A `None`
  value is now written as `col IS NULL`.
- `edb shell` prints the column header and `(0 rows)` for a query that matches no rows, and
  `OK (affected: 0)` for statements such as `CREATE TABLE`. Both printed `OK (affected: -1)`, sqlite3's
  rowcount for statements it does not count.

### Changed

- **Behavior change: prefix matching is now case-sensitive and literal** in `list_keys`,
  `GET /kv/keys?prefix=` and the `kv list` query, like `get()` and `delete()`. `prefix=user` no longer returns
  `User_2`, and `_` and `%` match only themselves. Callers that relied on ASCII case folding must
  pass the exact case.

## [3.0.1] - 2026-05-16

### Production Release — Unified EmbeddedOS-org v3.0.1

This is the synchronized production release across all 18 EmbeddedOS-org repos.

- Refreshed governance: LICENSE, NOTICE, CITATION.cff, SECURITY.md
- CI/CD pipelines hardened: release.yml, book-build.yml, video-build.yml, deploy-pages.yml
- Release artifacts produced for: Linux x64/arm64, macOS x64/arm64, Windows x64, Docker, plus per-repo embedded/mobile/extension targets
- mdBook documentation built and deployed to GitHub Pages
- Promo video rendered and attached as a release asset

## [3.0.0] - 2026-05-13

### Production Release — Unified EmbeddedOS-org v3.0.0

This is the synchronized production release across all 18 EmbeddedOS-org repos.

- Refreshed governance: LICENSE, NOTICE, CITATION.cff, SECURITY.md
- CI/CD pipelines hardened: release.yml, book-build.yml, video-build.yml, deploy-pages.yml
- Release artifacts produced for: Linux x64/arm64, macOS x64/arm64, Windows x64, Docker, plus per-repo embedded/mobile/extension targets
- mdBook documentation built and deployed to GitHub Pages
- Promo video rendered and attached as a release asset

All notable changes to eDB will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-03

### Added
- Core multi-model storage engine (relational, document, key-value) on SQLite
- JSON-based query DSL with parser and planner
- JWT authentication with access and refresh tokens
- Role-Based Access Control (RBAC) with admin, read_write, read_only roles
- AES-256 encryption at rest for sensitive fields
- Tamper-resistant audit logging with hash chain
- Input sanitization and SQL injection prevention
- REST API via FastAPI with endpoints for SQL, documents, key-value, auth, and admin
- AI/ebot natural language query translation (rule-based + optional LLM)
- Prompt injection detection for AI queries
- CLI with `serve`, `init`, `shell`, and `version` commands
- Pydantic-based configuration with environment variable support
- Comprehensive test suite (unit + integration)
- GitHub Actions CI pipeline
- Architecture documentation and API reference
- Contributing guidelines and security policy
