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
- `POST /auth/password` signs out every session of the user: access and refresh tokens issued before
  the change are rejected, including the one used to make it, and the response says to log in again.
  Before, tokens issued with the old password stayed valid until they expired, because the marker
  `TokenBlacklist.revoke_all_for_user()` records was never checked. Token times are whole seconds, so
  a token issued in the same second as the change is kept for the rest of its lifetime: by default up
  to 60 minutes for an access token and 7 days for a refresh token.
- `POST /auth/refresh` and every route that needs a login reject a token without a `jti` with 401.
  `POST /auth/logout` could not revoke such a token, although it answered `Logged out successfully`, and
  a refresh token without one was not single-use. Every token eDB has issued since logout revocation
  was added carries a `jti`, so only tokens from before then are affected. The same check also
  rejects a token whose `jti` or `sub` is not a non-empty string, or whose `iat` is not a plain
  integer, rather than passing the claim to the blacklist query.
- `RelationalStore.insert_many()` binds every row's values by column name. It used each row's own
  key order with the first row's column list, so `[{"a": 1, "b": 2}, {"b": 3, "a": 4}]` stored the
  second row as `a=3, b=4`. A row whose columns differ from the first row's now raises `ValueError`
  instead of binding values to the wrong columns.
- A KV value or document nested more than 100 levels deep is rejected with 422 instead of being
  stored and then failing every response with 500. Past about 300 levels FastAPI/Pydantic could not
  serialize the response, so the write succeeded and the value could never be read back; the 422
  error path itself is also guarded, so a rejected input nested ~500+ levels deep still returns 422
  rather than a 500.
- `GET /sql/tables/{table_name}` and `GET /admin/audit` reject a `limit` outside 1–1000, and an
  `offset` that is negative or past SQLite's 64-bit range, with 422. A negative `limit` returned every
  row, because SQLite reads it as "no limit", and a value past the 64-bit range failed with a 500 error.
- `KeyValueStore.list_keys(prefix)` (and `GET /kv/keys?prefix=`, the `kv list` query) now matches the
  prefix literally. It used SQL `LIKE`, so `_` and `%` in the prefix acted as wildcards and ASCII
  letters matched case-insensitively: `user_` also returned `userX`, `users` and `User_2`. The scan is
  now a key range (`key >= prefix AND key < next`), which also uses the key index.
- `DocumentStore` now stores each document's `created_at`. It was never saved, so `find()`,
  `find_by_id()`, `update()`, `GET /docs/{collection}/{doc_id}` and the document queries reported the
  time of the read as `created_at`, a different value on every call. `update()` keeps the original
  value. An existing database gains the column on open; documents written before that report
  `created_at: null`.
- `PUT /kv/{key}`, `POST /docs/{collection}` and `PUT /docs/{collection}/{doc_id}` reject `NaN`,
  `Infinity` and `-Infinity` anywhere in the value or document with 422. Python's JSON parser accepts
  them although they are not valid JSON, so they were stored as invalid JSON and read back as `null`.
- `FullTextSearch.index_document()` indexes a field that holds `None` as empty text. It used `str()`,
  so the field was stored as the word `None`: a search for `none` matched the document and its result
  reported the field as `"None"` instead of `""`.
- `DocumentStore.insert()` for an existing `doc_id` updates the document in place. It used
  `INSERT OR REPLACE`, which gave the document a new rowid and moved it to the end of `find()`, so a
  client paging through it could skip one document and see another twice. `find()` also orders by
  `rowid` now, so insertion order is stated by the query rather than left to the planner.
- `GraphStore.add_node()` for an existing `node_id` updates the node in place. It used
  `INSERT OR REPLACE`, which gave the node a new rowid and moved it to the end of `find_nodes()`, so a
  client paging through it could skip one node and see another twice.
- `RelationalStore.create_table()` (and `POST /sql/tables`, the `sql create_table` query) now writes
  `ColumnDefinition.default` into the table as a `DEFAULT` clause. It was ignored, so a row inserted
  without that column got `NULL` instead of the default. Text, numbers, booleans and bytes are
  accepted; any other default is rejected with `ValueError` before the table is created.
- `edb backup` now refuses a `--db` path that does not exist: it prints `No database at <path>` and
  exits 1. It used to open the path with `Database()`, which created a new empty database there, back
  that up to `--dest` and report `Backup created` with exit status 0.
- `RelationalStore.select()`, `update()` and `delete()` (and the `/sql` table routes and `sql` queries
  that use them) now match a `None` value in `where` against `NULL`. They wrote `col = ?` with a
  `None` parameter, which is never true in SQL, so `where={"age": None}` matched no rows. A `None`
  value is now written as `col IS NULL`.
- `edb shell` prints the column header and `(0 rows)` for a query that matches no rows, and
  `OK (affected: 0)` for statements such as `CREATE TABLE`. Both printed `OK (affected: -1)`, sqlite3's
  rowcount for statements it does not count.
- eBot's rule-based translator (`POST /ebot/query`) no longer lowercases names, keys and values.
  It matched its patterns against the lowercased text, so `find users where name=Ada` searched for
  `ada` and found nothing, and `get key Session-Token` looked up `session-token`. Keywords still
  match in any case.
- eBot's rule-based translator (`POST /ebot/query`) no longer degrades to quadratic matching on
  queries containing a long run of spaces (polynomial ReDoS). The `find`, `get key`, `insert` and
  `delete` patterns paired a lazy `(.+?)` with an adjacent `\s*`/`\s+`, so the engine retried every
  split of the run: a 5,000-space `find ... where ... =` query took ~81s of CPU, and `delete` ~160s.
  The patterns are now unambiguous and the same query is handled in well under a millisecond.
  Translation results are unchanged.
- `Database(":memory:")` is one database shared by every thread that uses it. Each thread got its own
  empty database, so data written in one thread was missing in another (`no such table`). This needs
  SQLite 3.36 or newer; with an older SQLite, opening `:memory:` raises `RuntimeError` saying so. It has
  no WAL, so while one thread has a write transaction open, a reader in another thread waits for it and
  raises `database is locked` after 5 seconds. The database belongs to one process: a child created
  with `os.fork()` gets a copy, not a shared database.
- `StorageEngine.close()` (and `Database.close()`) closes the connections of every thread, not only
  the calling thread's. A thread that uses the engine afterwards opens a new connection; for
  `:memory:` that is a new, empty database.

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

