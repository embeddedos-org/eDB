"""The version eDB reports must match the released package version."""

import tomllib
from pathlib import Path

from edb import __version__

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _package_version():
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def test_package_version_matches_pyproject():
    assert __version__ == _package_version()


def test_api_reports_the_package_version(app_client):
    assert app_client.get("/health").json()["version"] == _package_version()
    assert app_client.app.openapi()["info"]["version"] == _package_version()
