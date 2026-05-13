# Changelog

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
