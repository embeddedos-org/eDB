"""Unit tests for EDBConfig.

`cors_origins` was declared twice in the class body with different types, so the
second declaration silently shadowed the first. These tests pin the surviving
contract — a comma-separated string that `create_app` splits — so a re-introduced
`list[str]` declaration fails here instead of at runtime.
"""

import pytest

from edb.config import EDBConfig


def test_cors_origins_is_a_comma_separated_string() -> None:
    config = EDBConfig()
    assert isinstance(config.cors_origins, str)
    assert config.cors_origins == "http://localhost:3000"


def test_cors_origins_is_declared_once() -> None:
    annotations = EDBConfig.__annotations__
    assert annotations["cors_origins"] is str or annotations["cors_origins"] == "str"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        (
            "http://localhost:3000,https://example.com",
            ["http://localhost:3000", "https://example.com"],
        ),
        (" http://a.test , http://b.test ", ["http://a.test", "http://b.test"]),
    ],
)
def test_cors_origins_splits_the_way_create_app_splits_it(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("EDB_CORS_ORIGINS", raw)
    config = EDBConfig()
    origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
    assert origins == expected
