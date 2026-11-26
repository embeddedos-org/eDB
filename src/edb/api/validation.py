"""Validators shared by the API request models."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import AfterValidator


def _reject_non_finite(value: Any) -> Any:
    # Python's JSON parser accepts NaN and Infinity, but they are not valid JSON.
    # Stored as-is, they were written to the database as invalid JSON and read
    # back as null, so a request containing one is rejected with 422 instead.
    #
    # The walk is iterative on purpose. Recursing once per nesting level blew the
    # interpreter's recursion limit a few hundred levels down, which raises
    # RecursionError inside request-model validation and reaches the client as a
    # 500. CPython's JSON scanner accepts far deeper input than that, so a
    # recursive walk here turned a well-formed request into a server error.
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("NaN and Infinity are not valid JSON numbers")
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return value


# Any JSON value, with NaN and Infinity rejected at any depth.
FiniteJSON = Annotated[Any, AfterValidator(_reject_non_finite)]
