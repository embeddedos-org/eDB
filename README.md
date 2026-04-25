# eDB: Unified Multi-Model Database Ecosystem

[![CI](https://github.com/embeddedos-org/eDB/actions/workflows/ci.yml/badge.svg)](https://github.com/embeddedos-org/eDB/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> Part of the [EmbeddedOS](https://github.com/embeddedos-org) ecosystem.

**eDB** is a unified multi-model database that combines **SQL**, **Document/NoSQL**, and **Key-Value** storage in a single embedded engine. It includes a Python backend (FastAPI + SQLite), a React/TypeScript frontend with SQL editor and AI-powered query assistance, and a standalone browser version.

## Features

| Feature | Description |
|---------|-------------|
| 🗃️ **Multi-Model Storage** | SQL tables, JSON documents, and key-value pairs — all in one database |
| 🔐 **JWT Authentication** | Access and refresh tokens with configurable expiration |
| 👥 **RBAC** | Admin, read_write, read_only roles with granular permissions |
| 🔒 **AES-256 Encryption** | Field-level encryption at rest using AES-256-GCM |
| 📋 **Audit Logging** | Tamper-resistant logs with hash chain verification |
| 🤖 **eBot AI** | Natural language → SQL/NoSQL translation |
| 🌐 **REST API** | Full CRUD via FastAPI with auto-generated OpenAPI docs |
| 🛡️ **Input Sanitization** | SQL injection, NoSQL injection, and prompt injection detection |
| ⚡ **Zero Dependencies** | Core engine runs on SQLite — no external database needed |
| 📦 **Embeddable** | Use as a Python library or standalone server |
| 🖥️ **React Frontend** | Table management, inline editing, SQL query editor, eBot sidebar |
| 🌐 **Browser Standalone** | Self-contained single-file HTML version with localStorage persistence |

## Quick Start

### Backend (Python API Server)

```bash
git clone https://github.com/embeddedos-org/eDB.git
cd eDB
pip install -e ".[dev]"

# Initialize database
edb init

# Create admin user (interactive password prompt)
edb admin create --username admin

# Start the server
edb serve --port 8000

# API docs at http://localhost:8000/docs
```

### Frontend (React UI)

```bash
npm install
npm run dev
```

The React UI runs at [http://localhost:5178](http://localhost:5178).

### Browser Standalone

Open `browser/edb.html` directly in any browser for a zero-install experience with localStorage persistence.

### As a Python Library

```python
from edb.core.database import Database
from edb.core.models import ColumnDefinition, ColumnType, TableSchema

db = Database("my_app.db")

# SQL
schema = TableSchema(name="users", columns=[
    ColumnDefinition(name="id", col_type=ColumnType.INTEGER, primary_key=True),
    ColumnDefinition(name="name", col_type=ColumnType.TEXT),
])
db.sql.create_table(schema)
db.sql.insert("users", {"id": 1, "name": "Alice"})

# Documents
db.docs.insert("logs", {"event": "login", "user": "Alice"})

# Key-Value
db.kv.set("session:abc", {"user_id": 1}, ttl=3600)
```

### Interactive Shell

```bash
edb shell
# edb> SELECT * FROM users
# edb> .tables
# edb> .collections
```

## Architecture

```
eDB/
├── src/
│   ├── edb/                  # Python backend
│   │   ├── api/              # FastAPI routes and dependencies
│   │   ├── auth/             # JWT, users, RBAC
│   │   ├── ebot/             # AI/NLP query interface
│   │   ├── query/            # Query parser and planner
│   │   ├── security/         # Encryption, audit, input validation
│   │   ├── config.py         # Pydantic Settings configuration
│   │   └── cli.py            # CLI entry point
│   ├── App.tsx               # React main component
│   ├── main.tsx              # React entry point
│   ├── styles.css            # Full application styles
│   ├── components/           # React UI components
│   │   ├── TopBar.tsx        # App header with controls
│   │   ├── TableList.tsx     # Sidebar table navigator
│   │   ├── TableView.tsx     # Data grid with inline editing
│   │   ├── QueryEditor.tsx   # SQL query editor panel
│   │   ├── EBotSidebar.tsx   # AI assistant sidebar
│   │   └── StatusBar.tsx     # Bottom status bar
│   └── hooks/                # React hooks
│       ├── useDatabase.ts    # In-memory database with CRUD
│       └── useEBot.ts        # eBot AI integration
├── browser/
│   └── edb.html              # Standalone browser version
├── tests/                    # Python tests
├── docs/                     # Documentation
├── examples/                 # Runnable examples
├── package.json              # Node.js project manifest
├── pyproject.toml            # Python project metadata
├── vite.config.ts            # Vite configuration
└── tsconfig.json             # TypeScript configuration
```

## Configuration

Configure via environment variables (prefix `EDB_`) or `.env` file:

```bash
EDB_DB_PATH=my_data.db
EDB_API_HOST=0.0.0.0
EDB_API_PORT=8000
EDB_JWT_SECRET=your-strong-secret-here
EDB_ENCRYPTION_KEY=your-encryption-key
EDB_CORS_ORIGINS=http://localhost:3000,https://yourdomain.com
```

## Security

### Required Environment Variables for Production

| Variable | Description |
|----------|-------------|
| `EDB_JWT_SECRET` | **Required.** Secret key for JWT signing. If not set, a random key is generated per session (tokens won't persist across restarts). |
| `EDB_ENCRYPTION_KEY` | **Required.** Key for AES-256-GCM encryption at rest. If not set, a random key is generated (encrypted data won't be recoverable after restart). |
| `EDB_CORS_ORIGINS` | Comma-separated allowed origins. Defaults to `http://localhost:3000`. |

### Admin User Setup

Admin users are **not** auto-created. Use the CLI to create one:

```bash
edb admin create --username admin
# You'll be prompted for a password interactively.
# Password must be 12+ chars with uppercase, lowercase, digit, and special char.
```

### Security Best Practices

- Always set `EDB_JWT_SECRET` and `EDB_ENCRYPTION_KEY` in production
- Use strong, unique values (e.g., `openssl rand -base64 48`)
- Never commit `.env` files to version control
- Restrict CORS origins to your actual frontend domains
- Review audit logs regularly via `/admin/audit` endpoint

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Development

### Python Backend

```bash
pip install -e ".[dev]"
pytest
ruff check src/ tests/
ruff format src/ tests/
```

### React Frontend

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server (port 5178) |
| `npm run build` | Type-check and build for production |
| `npm run preview` | Preview production build |

## Roadmap

- [x] Core multi-model engine (SQL, Document, KV)
- [x] Query DSL with parser and planner
- [x] JWT authentication and RBAC
- [x] AES-256 encryption at rest
- [x] Tamper-resistant audit logging
- [x] REST API (FastAPI)
- [x] eBot rule-based NL queries
- [x] CLI (serve, init, shell)
- [x] React frontend with SQL editor
- [x] Browser standalone version
- [x] CI/CD pipeline
- [ ] LLM-powered eBot (OpenAI/local models)
- [ ] Graph data model (Neo4j-style)
- [ ] Multi-node clustering (eDBE)
- [ ] GraphQL and gRPC interfaces
- [ ] File/blob storage with indexing
- [ ] Predictive analytics integration

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.


---
Part of the [EmbeddedOS Organization](https://embeddedos-org.github.io).
