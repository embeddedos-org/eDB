# Development

## Contribution source of truth

[CONTRIBUTING](https://github.com/embeddedos-org/eDB/blob/master/CONTRIBUTING.md)

Before proposing a change, also review the [README](https://github.com/embeddedos-org/eDB/blob/master/README.md). Keep changes scoped, add tests appropriate to the affected behavior, and follow the repository's current automation and review requirements.

## Build and dependency inputs found

`Dockerfile`, `docker-compose.yml`, `package-lock.json`, `package.json`, `pyproject.toml`.

## Tests found in the default-branch tree

`src/__tests__/smoke.test.tsx`, `tests/__init__.py`, `tests/conftest.py`, `tests/conftest.py.bak`, `tests/functional/__init__.py`, `tests/functional/test_functional_e2e.py`, `tests/integration/__init__.py`, `tests/integration/test_api.py`, `tests/performance/__init__.py`, `tests/performance/test_performance_benchmarks.py`, `tests/simulation/__init__.py`, `tests/simulation/test_emulation_simulation.py`, and 3 more.

## Documented test commands

These commands are reproduced from the inspected root README or contributing guide:

```bash
pytest
```

```bash
pytest --cov=edb --cov-report=html
```

## Verification baseline

This inventory comes from `master` at [`0457c0ace631`](https://github.com/embeddedos-org/eDB/commit/0457c0ace631cd540529a53f6c63c37fed467286) and found 15 test-related paths among 173 files. Re-check the source tree when that commit is no longer current.
