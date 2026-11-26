# SPDX-License-Identifier: MIT
"""Unit tests for edb.api.validation, the shared request-body validator.

Pure-logic module: walks a decoded JSON value, rejects NaN/Infinity at any
depth so writes return 422 instead of storing invalid JSON that reads back as
null (#219, #223), and rejects values nested past MAX_JSON_DEPTH (#220).
"""
import json
import math
from typing import Any

import pytest

from edb.api.validation import MAX_JSON_DEPTH, _reject_non_finite


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_scalar(bad):
    with pytest.raises(ValueError, match="not valid JSON numbers"):
        _reject_non_finite(bad)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_rejects_non_finite_nested_in_dict_and_list(bad):
    value = json.loads('{"a": [{"b": [' + bad + "]}]}")
    with pytest.raises(ValueError, match="not valid JSON numbers"):
        _reject_non_finite(value)


def test_accepts_finite_values_and_returns_them_unchanged():
    value = {"a": [1, 2.5, "x", None, True, {"b": -0.0}]}
    assert _reject_non_finite(value) is value


def test_accepts_special_but_finite_floats():
    for ok in (0.0, -0.0, 1e308, -1e308, 5e-324):
        assert math.isfinite(ok)
        assert _reject_non_finite(ok) == ok


# Depth counts enclosing containers and the root is 0, so a value wrapped in
# MAX_JSON_DEPTH lists is the deepest accepted shape.


@pytest.mark.parametrize("open_, close", [("[", "]"), ('{"a":', "}")])
def test_accepts_a_value_at_exactly_the_depth_limit(open_, close):
    value = json.loads(open_ * MAX_JSON_DEPTH + "1.5" + close * MAX_JSON_DEPTH)
    assert _reject_non_finite(value) is value


@pytest.mark.parametrize("open_, close", [("[", "]"), ('{"a":', "}")])
def test_rejects_a_value_one_level_past_the_limit(open_, close):
    depth = MAX_JSON_DEPTH + 1
    value = json.loads(open_ * depth + "1.5" + close * depth)
    with pytest.raises(ValueError, match="levels deep"):
        _reject_non_finite(value)


def test_depth_rejection_does_not_recurse():
    # The walk has to stay iterative: it must reject deep input rather than
    # raise RecursionError out of request-model validation, which would reach
    # the client as a 500. Built in Python rather than parsed from text,
    # because how deep json.loads itself goes before raising RecursionError
    # varies by interpreter build and stack size; this test is about the
    # validator, not the parser.
    value: Any = 1.5
    for _ in range(20000):
        value = [value]
    with pytest.raises(ValueError, match="levels deep"):
        _reject_non_finite(value)


def test_a_wide_shallow_value_is_not_treated_as_deep():
    # Depth is per branch, not a count of visited nodes.
    value = {str(i): [i, {"k": i}] for i in range(5000)}
    assert _reject_non_finite(value) is value


def test_non_finite_is_still_found_below_a_shallow_prefix():
    value = json.loads("[" * 50 + "NaN" + "]" * 50)
    with pytest.raises(ValueError, match="not valid JSON numbers"):
        _reject_non_finite(value)
