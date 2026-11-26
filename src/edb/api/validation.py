"""Validators shared by the API request models."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import AfterValidator

# A value nested deeper than this is rejected with 422 (eDB#220). Past about
# 300 levels FastAPI/Pydantic fails serializing the response, so the write
# succeeded and every response containing the value returned 500 — a value
# eDB could store but never return. 100 is far below the failure band and far
# above any value a client should be sending as one JSON document.
MAX_JSON_DEPTH = 100


def _reject_non_finite(value: Any) -> Any:
    # Python's JSON parser accepts NaN and Infinity, but they are not valid JSON.
    # Stored as-is, they were written to the database as invalid JSON and read
    # back as null, so a request containing one is rejected with 422 instead.
    # Iterative, not recursive: a value nested ~1000 deep must not blow the
    # stack while being rejected. Depth counts enclosing containers; the root
    # is 0, so a value wrapped in 100 lists is accepted and 101 is rejected.
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError(
                f"JSON values nested more than {MAX_JSON_DEPTH} levels deep "
                "are not accepted"
            )
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("NaN and Infinity are not valid JSON numbers")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return value


# Any JSON value, with NaN and Infinity rejected at any depth.
FiniteJSON = Annotated[Any, AfterValidator(_reject_non_finite)]

# A whole JSON object, validated as one value so the enclosing mapping counts
# toward the depth limit. Annotating the *values* of a mapping instead
# (dict[str, FiniteJSON]) restarts the count at 0 for each field and ignores
# the mapping holding them, so such a request could nest one level deeper than
# a bare FiniteJSON value before being rejected.
FiniteJSONObject = Annotated[dict[str, Any], AfterValidator(_reject_non_finite)]
