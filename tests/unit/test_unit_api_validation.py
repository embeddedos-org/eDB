# SPDX-License-Identifier: MIT
"""Unit tests for edb.api.validation (the FiniteJSON request validator).

Pure-logic module: walks a decoded JSON value and rejects NaN/Infinity at any
depth, so SQL, graph, KV and document writes return 422 instead of storing
invalid JSON that reads back as null (#219, #223).
"""
import json
import math

import pytest

from edb.api.validation import _reject_non_finite


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_scalar(bad):
    with pytest.raises(ValueError):
        _reject_non_finite(bad)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_rejects_non_finite_nested_in_dict_and_list(bad):
    value = json.loads('{"a": [{"b": [' + bad + "]}]}")
    with pytest.raises(ValueError):
        _reject_non_finite(value)


def test_accepts_finite_values_and_returns_them_unchanged():
    value = {"a": [1, 2.5, "x", None, True, {"b": -0.0}]}
    assert _reject_non_finite(value) is value


def test_accepts_special_but_finite_floats():
    for ok in (0.0, -0.0, 1e308, -1e308, 5e-324):
        assert math.isfinite(ok)
        assert _reject_non_finite(ok) == ok


# Regression for the recursive walk this validator used to do. Starlette decodes
# the request body with json.loads, whose C scanner accepts ~58k nesting levels,
# far past the interpreter's recursion limit. Recursing once per level therefore
# raised RecursionError inside request-model validation, before the route's
# error handling ran, and the caller got a 500 for a body the parser accepted.
DEEP = 20000


def test_deep_nesting_does_not_raise_recursion_error():
    value = json.loads("[" * DEEP + "1.5" + "]" * DEEP)
    assert _reject_non_finite(value) is value


def test_deep_nesting_still_rejects_a_non_finite_leaf():
    value = json.loads("[" * DEEP + "NaN" + "]" * DEEP)
    with pytest.raises(ValueError):
        _reject_non_finite(value)


def test_deep_dict_nesting_does_not_raise_recursion_error():
    value = json.loads('{"a":' * DEEP + "1.5" + "}" * DEEP)
    assert _reject_non_finite(value) is value
