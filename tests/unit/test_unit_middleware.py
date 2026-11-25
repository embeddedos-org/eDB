"""
tests/unit/test_unit_middleware.py — eDB API middleware unit tests

Exercises RateLimitMiddleware (src/edb/api/middleware.py) by calling
dispatch() directly with a fake clock, so no server or sleeping is needed.
"""

import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import Response

from edb.api import middleware


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(middleware.time, "time", lambda: now[0])
    return now


def _request(ip):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": (ip, 1)})


async def _ok(request):
    return Response("ok")


def _send(limiter, ip):
    return asyncio.run(limiter.dispatch(_request(ip), _ok))


def test_limit_is_enforced_per_client(clock):
    limiter = middleware.RateLimitMiddleware(app=None, max_requests=2, window_seconds=60)
    assert [_send(limiter, "1.1.1.1").status_code for _ in range(3)] == [200, 200, 429]
    assert _send(limiter, "2.2.2.2").status_code == 200


def test_clients_idle_for_a_window_are_forgotten(clock):
    limiter = middleware.RateLimitMiddleware(app=None, max_requests=100, window_seconds=60)
    for i in range(50):
        _send(limiter, f"10.0.0.{i}")
    assert len(limiter._requests) == 50

    clock[0] += 61
    _send(limiter, "1.1.1.1")
    assert list(limiter._requests) == ["1.1.1.1"]
