# Repository Guidance for Agents

## Scope and architecture

eDB combines a Python 3.11+ multi-model database and API with a React 19 and
TypeScript database-manager UI. Python packages live in `src/edb/`: storage
engines in `core/`, query handling in `query/`, HTTP endpoints in `api/`, access
control in `auth/`, security controls in `security/`, and query assistance in
`ebot/`. The web UI uses top-level TypeScript sources under `src/`. Examples,
documentation, and tests live in `examples/`, `docs/`, and `tests/`.

Follow the specialist role briefs in [`.ai/`](./.ai/) and the handoff protocol in
[`HANDOFF.md`](./HANDOFF.md). The implementer must not act as the approving
reviewer. Keep storage, API, and UI changes independently reviewable unless the
same contract changes end to end.

## Build and validation

- Install Python development dependencies with `pip install -e ".[dev]"`.
- Run Python tests with `pytest` and lint Python with `ruff check .`.
- Install UI dependencies with `npm ci`.
- Run UI tests with `npm test` and build with `npm run build`.
- For schema, transaction, backup, migration, authentication, or query changes,
  add regression coverage for rollback, malformed input, authorization failure,
  and persistence across a reopen when applicable.

Use temporary databases in tests. Never point validation at production or
personal data.

## Change discipline

Preserve the public Python API, CLI behavior, HTTP schemas, and multi-model
transaction semantics. Treat SQL construction, JWT/RBAC behavior, encryption,
backup/restore, and LLM-provider boundaries as security-sensitive. Do not commit
database files, environment files, tokens, model credentials, or generated web
artifacts.

Every human-authored pull request must use a GitHub-recognized closing keyword
for an issue in this repository, for example `Fixes #123`. Cross-repository
issues and plain issue mentions do not satisfy the linked-issue policy. Follow
[`.github/PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md), and
keep the published Wiki snapshot in [`docs/wiki/`](./docs/wiki/) synchronized
when Wiki content changes.
