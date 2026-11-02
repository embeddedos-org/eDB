<!-- generated: eos-ai-scaffold -->
# Tasks

Working ledger for `eDB`. The planner writes entries; each owning role
updates its own row. Roles are in [AGENTS.md](./AGENTS.md), the workflow in
[ORCHESTRATION.md](./ORCHESTRATION.md), the gate in [VERIFY.md](./VERIFY.md).

Status is one of: `todo`, `in-progress`, `blocked`, `review`, `done`.

## Active

| ID | Task | Owner | Mode | Status | Depends on |
|----|------|-------|------|--------|------------|
| —  | No active tasks. | — | — | — | — |

## Completed

| ID | Task | Owner | Verified by | Evidence |
|----|------|-------|-------------|----------|
| T-001 | Fix the query planner treating `QueryResult` objects as raw values | backend | reviewer | `RelationalStore.select/insert/update/delete` all return `QueryResult`, but `src/edb/query/planner.py` used the return values directly: `rows[0].keys()` raised `'QueryResult' object is not subscriptable`, which `execute()` caught and turned into `success=False` — so **every SQL query through the planner failed silently**. `insert` stored the whole `QueryResult` under `data["last_row_id"]`, and `update`/`delete` passed one as `row_count`. All four paths now read `.rows`, `.columns`, `.affected_rows` and `.last_row_id`. eDB's own 39 tests never covered the planner's SQL path; the vendored suite in eApps did. Now 5/5 planner tests and 150 vendored tests pass, eDB's own 39 still pass. |
| T-002 | Make `last_row_id` report an actual row id | backend | reviewer | `QueryResult.last_row_id` returned `affected_rows`, a count. Measured: inserting three rows that receive ids 1, 2, 3 reported `last_row_id` 1, 1, 1 — and `src/edb/api/routes/sql.py:163` returns that value to HTTP clients as `last_row_id`. `cur.lastrowid` was never captured. Added a `last_insert_id` field populated from the driver; the same three inserts now report 1, 2, 3. |

---

## Task template

```markdown
### T-000 — <short title>

Owner: <role>
Mode: <see MODES.md>
Status: todo
Depends on: <task ids, or none>

Goal
: <one sentence: what is true afterwards that is not true now>

Acceptance criteria
: - <observable, checkable statement>
  - <observable, checkable statement>

Files in scope
: <paths the owner is expected to touch>

Out of scope
: <what this task deliberately does not change>

Risks
: <what could break, and what would reveal it>

Verification
: | Check | Command | Result |
  |-------|---------|--------|
  | <name> | `<command>` | `NOT RUN` |
```

## Verification commands for this repository

These commands were derived from the manifests at the repository root. Confirm one works before relying on it; a listed script may still be a stub.

| Check | Command | Default state |
|-------|---------|---------------|
| Unit tests | `npm run test` | `NOT RUN` |
| Build | `npm run build` | `NOT RUN` |

## Rules

- One task per unit of work that can be verified on its own.
- Acceptance criteria are written before work starts and are not edited to match
  what was built. If they were wrong, say so and rewrite them explicitly.
- A task reaches `done` only when the definition of done in
  [ORCHESTRATION.md](./ORCHESTRATION.md) is met and the verification commands
  were actually run.
- `blocked` requires a note naming what it is blocked on and who can unblock it.
