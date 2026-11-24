"""Validators shared by the API request models."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import AfterValidator


def _reject_non_finite(value: Any) -> Any:
    # Python's JSON parser accepts NaN and Infinity, but they are not valid JSON.
    # Stored as-is, they were written to the database as invalid JSON and read
    # back as null, so a request containing one is rejected with 422 instead.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and Infinity are not valid JSON numbers")
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    return value


# Any JSON value, with NaN and Infinity rejected at any depth.
FiniteJSON = Annotated[Any, AfterValidator(_reject_non_finite)]
