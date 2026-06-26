"""Translation of PostgREST horizontal-filter operators into Django ``Q`` objects.

A filter arrives as ``?column=operator.value`` (optionally ``not.`` prefixed),
e.g. ``?age=gte.18``, ``?name=ilike.*foo*``, ``?id=in.(1,2,3)``,
``?active=is.true``, ``?tags=cs.{a,b}``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.postgres.search import SearchQuery
from django.db.models import Q

from .exceptions import PostgrestError

# Operators that map directly onto a Django field lookup, taking the value as-is.
SIMPLE_LOOKUPS: dict[str, str] = {
    "eq": "exact",
    "neq": "exact",  # negated below
    "gt": "gt",
    "gte": "gte",
    "lt": "lt",
    "lte": "lte",
    "like": "like",
    "ilike": "ilike",
    "match": "regex",
    "imatch": "iregex",
}

# Array / range operators (PostgreSQL-specific; best-effort).
SET_LOOKUPS: dict[str, str] = {
    "cs": "contains",
    "cd": "contained_by",
    "ov": "overlap",
}

FTS_OPERATORS = {"fts", "plfts", "phfts", "wfts"}

# PostgREST search-type -> Django SearchQuery ``search_type``.
FTS_SEARCH_TYPE = {
    "fts": "plain",
    "plfts": "plain",
    "phfts": "phrase",
    "wfts": "websearch",
}


def _split_op(token: str) -> tuple[bool, str, str | None, str]:
    """Split an operator token into ``(negate, op, modifier, value)``.

    Examples::

        "eq.foo"          -> (False, "eq", None, "foo")
        "not.ilike.*x*"   -> (True, "ilike", None, "*x*")
        "fts(english).cat"-> (False, "fts", "english", "cat")
        "is.null"         -> (False, "is", None, "null")
    """
    negate = False
    if token.startswith("not."):
        negate = True
        token = token[4:]

    op_part, sep, value = token.partition(".")
    if not sep:
        raise PostgrestError(
            f"Malformed filter operator: {token!r}",
            code="PGRST-100",
            hint="Expected the form 'operator.value', e.g. 'eq.123'.",
        )

    modifier: str | None = None
    if "(" in op_part and op_part.endswith(")"):
        op_part, _, mod = op_part[:-1].partition("(")
        modifier = mod

    return negate, op_part, modifier, value


def _parse_list(value: str) -> list[str]:
    """Parse a PostgREST list literal ``(a,b,c)`` or ``{a,b,c}``."""
    inner = value.strip()
    if inner and inner[0] in "({" and inner[-1] in ")}":
        inner = inner[1:-1]
    if not inner:
        return []
    # Minimal handling of double-quoted members containing commas.
    out: list[str] = []
    buf = ""
    in_quote = False
    for ch in inner:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch == "," and not in_quote:
            out.append(buf)
            buf = ""
            continue
        buf += ch
    out.append(buf)
    return [item.strip() for item in out]


def _coerce_is_value(value: str) -> Any:
    mapping = {"null": None, "true": True, "false": False, "unknown": None}
    key = value.lower()
    if key not in mapping:
        raise PostgrestError(
            f"Invalid 'is' value: {value!r}",
            code="PGRST-100",
            hint="Use is.null, is.true, is.false or is.unknown.",
        )
    return mapping[key]


def build_q(column: str, token: str) -> Q:
    """Build a ``Q`` object for a single ``column=token`` filter."""
    negate, op, modifier, value = _split_op(token)
    q = _build_q_inner(column, op, modifier, value)
    return ~q if negate else q


def _build_q_inner(column: str, op: str, modifier: str | None, value: str) -> Q:
    if op in SIMPLE_LOOKUPS:
        lookup = SIMPLE_LOOKUPS[op]
        parsed: Any = value
        if op in ("like", "ilike"):
            parsed = value.replace("*", "%")
        q = Q(**{f"{column}__{lookup}": parsed})
        return ~q if op == "neq" else q

    if op == "in":
        return Q(**{f"{column}__in": _parse_list(value)})

    if op == "is":
        coerced = _coerce_is_value(value)
        if coerced is None:
            return Q(**{f"{column}__isnull": True})
        return Q(**{f"{column}__exact": coerced})

    if op == "isdistinct":
        # DISTINCT FROM: differs from the value, including across NULLs.
        return ~Q(**{f"{column}__exact": value})

    if op in SET_LOOKUPS:
        return Q(**{f"{column}__{SET_LOOKUPS[op]}": _parse_list(value)})

    if op in FTS_OPERATORS:
        # ``field__search`` accepts a SearchQuery directly, generating
        # ``to_tsvector(field) @@ <query>`` on PostgreSQL. Best-effort: requires
        # a PostgreSQL backend (no-op/raises on SQLite).
        query = SearchQuery(
            value,
            config=modifier or None,
            search_type=FTS_SEARCH_TYPE[op],
        )
        return Q(**{f"{column}__search": query})

    raise PostgrestError(
        f"Unknown operator {op!r}",
        code="PGRST-100",
        hint=f"Supported: {sorted(set(SIMPLE_LOOKUPS) | set(SET_LOOKUPS) | {'in', 'is', 'isdistinct'} | FTS_OPERATORS)}",
    )
