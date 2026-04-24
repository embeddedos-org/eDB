"""eDB configuration management.

Uses Pydantic Settings to load configuration from environment variables and .env files.
"""

from __future__ import annotations

import logging
import os
import secrets

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger("edb.config")


def _generate_random_secret(name: str) -> str:
    """Generate a cryptographically secure random secret and log a CRITICAL warning."""
    secret = secrets.token_urlsafe(48)
    logger.critical(
        "⚠️  No %s configured! A random secret was generated for this session. "
        "Set the %s environment variable for production use. "
        "Tokens/data from previous sessions will be INVALID.",
        name,
        name,
    )
    return secret


class EDBConfig(BaseSettings):
    """eDB configuration loaded from environment variables."""

    db_path: str = Field(default="edb_data.db", description="Path to the SQLite database file")
    api_host: str = Field(default="127.0.0.1", description="API server host")
    api_port: int = Field(default=8000, description="API server port")
    api_reload: bool = Field(default=False, description="Enable auto-reload for development")

    jwt_secret: str = Field(
        default="",
        description="Secret key for JWT token signing (REQUIRED for production)",
    )
    jwt_access_expire_minutes: int = Field(
        default=60, description="Access token expiration in minutes"
    )
    jwt_refresh_expire_days: int = Field(default=7, description="Refresh token expiration in days")

    encryption_key: str = Field(
        default="",
        description="Encryption key for data at rest (REQUIRED for production)",
    )

    log_level: str = Field(default="INFO", description="Logging level")
    audit_enabled: bool = Field(default=True, description="Enable audit logging")
    create_admin: bool = Field(default=False, description="Auto-create admin user on first run")

    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )

    rate_limit_enabled: bool = Field(default=True, description="Enable API rate limiting")
    rate_limit_requests: int = Field(default=100, description="Max requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window in seconds")

    ebot_enabled: bool = Field(default=True, description="Enable ebot AI query interface")
    ebot_provider: str = Field(
        default="rule_based", description="ebot provider: rule_based or openai"
    )
    ebot_openai_api_key: str = Field(default="", description="OpenAI API key for ebot LLM mode")
    ebot_openai_model: str = Field(default="gpt-3.5-turbo", description="OpenAI model for ebot")

    @model_validator(mode="after")
    def _ensure_secrets(self) -> "EDBConfig":
        if not self.jwt_secret:
            self.jwt_secret = _generate_random_secret("EDB_JWT_SECRET")
        if not self.encryption_key:
            self.encryption_key = _generate_random_secret("EDB_ENCRYPTION_KEY")
        return self

    model_config = {
        "env_prefix": "EDB_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }
