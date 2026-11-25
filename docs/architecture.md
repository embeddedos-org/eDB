# eDB Architecture

## System Overview

```mermaid
graph TB
    Client[Client Application] --> API[REST API - FastAPI]
    Client --> CLI[CLI - edb shell]
    Client --> Embed[Python Embedding - import edb]

    API --> Auth[Auth Layer - JWT + RBAC]
    API --> Ebot[ebot AI - NL Translator]

    Auth --> QP[Query Parser]
    Ebot --> QP

    QP --> Planner[Query Planner]

    Planner --> SQL[Relational Store]
    Planner --> Doc[Document Store]
    Planner --> KV[Key-Value Store]

    SQL --> Engine[Storage Engine - SQLite]
    Doc --> Engine
    KV --> Engine

    Engine --> DB[(SQLite Database File)]

    Audit[Audit Logger] --> Engine
    Encrypt[Encryption Manager] --> Engine

    style API fill:#4CAF50,color:white
    style Engine fill:#2196F3,color:white
    style Auth fill:#FF9800,color:white
    style Ebot fill:#9C27B0,color:white
```

## Components

### Storage Engine (`edb.core.engine`)
The lowest-level component. Manages the SQLite connections (WAL mode for file databases), thread safety, and parameterized query execution.

Connection model: each thread gets its own connection, for files and for `:memory:`. A `:memory:` database is a named in-memory database (SQLite's `memdb` VFS) shared by all of that engine's connections, so it is the same database in every thread, with per-connection transactions. Unlike a file, it has no WAL: while one connection has a write transaction open, the others wait for it, even to read, and raise `database is locked` after the 5 s busy timeout; a file database (WAL) lets readers through. The shared `:memory:` database lives in one process's memory: a child created with `os.fork()` gets a copy, not a shared database, so it must open its own `Database`. `close()` closes every connection the engine has open, in all threads; it should be called once no other thread is using the engine, and the next call in any thread opens a new connection (for `:memory:`, a new, empty database).

### Relational Store (`edb.core.relational`)
SQL CRUD operations (CREATE TABLE, INSERT, SELECT, UPDATE, DELETE) with parameterized queries to prevent injection.

### Document Store (`edb.core.document`)
MongoDB-like JSON document storage. Collections are SQLite tables with `id`, `data` (JSON), `created_at`, `updated_at`. Supports JSON path queries via SQLite's JSON1 extension.

### Key-Value Store (`edb.core.keyvalue`)
Simple key-value operations with optional TTL expiration. Values are JSON-serialized. Expired entries are automatically purged.

### Unified Database (`edb.core.database`)
Single entry point combining all three stores. Provides transaction support via context manager (`with db.transaction()`).

### Query Parser (`edb.query.parser`)
Parses JSON-based query DSL into typed query objects. Validates actions, required fields, and type aliases.

### Query Planner (`edb.query.planner`)
Routes parsed queries to the correct store and executes them. Returns unified results regardless of underlying store type.

### Authentication (`edb.auth`)
- **JWT Handler**: Creates and verifies access/refresh tokens
- **User Manager**: User CRUD with bcrypt password hashing
- **RBAC Manager**: Role-based permission checks (admin, read_write, read_only, custom roles)

### Security (`edb.security`)
- **Encryption**: AES-256-GCM field-level encryption at rest
- **Audit Logger**: Tamper-resistant append-only log with hash chain verification
- **Input Validator**: SQL injection, NoSQL injection, and prompt injection detection

### ebot (`edb.ebot`)
- **Translator**: Natural language → eDB query DSL (rule-based regex patterns)
- **Sanitizer**: Validates translations, enforces RBAC on AI-generated queries

### REST API (`edb.api`)
FastAPI application with routes for SQL, Documents, KV, Auth, Admin, and ebot. All endpoints require JWT authentication and RBAC permission checks.

## Data Flow

1. **Request** → FastAPI endpoint
2. **Auth** → JWT verification → RBAC check
3. **Validation** → Input sanitization
4. **Execution** → Query parser → Planner → Appropriate store
5. **Audit** → Log the operation with hash chain
6. **Response** → Unified result format
