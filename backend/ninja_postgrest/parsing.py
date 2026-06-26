"""Parse a PostgREST query string into structured pieces.

Produces:
- a combined ``Q`` object from horizontal filters (incl. ``or=()`` / ``and=()``),
- a ``select`` tree (vertical filtering + embeds),
- an ordering spec,
- ``limit`` / ``offset``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q
from django.http import HttpRequest

from .exceptions import PostgrestError
from .operators import build_q

RESERVED_PARAMS = {
    "select",
    "order",
    "limit",
    "offset",
    "and",
    "or",
    "on_conflict",
    "columns",
}


# --------------------------------------------------------------------------- #
# Generic paren-aware splitting
# --------------------------------------------------------------------------- #
def split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split ``s`` on ``sep`` ignoring separators nested in (), [] or {}."""
    parts: list[str] = []
    depth = 0
    buf = ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf or parts:
        parts.append(buf)
    return parts


# --------------------------------------------------------------------------- #
# select tree
# --------------------------------------------------------------------------- #
@dataclass
class SelectField:
    column: str  # base column name (model field)
    alias: str | None = None  # output key override
    cast: str | None = None  # PostgREST ::type cast (best-effort, informational)
    json_path: list[str] = field(default_factory=list)  # ->/->> path segments
    json_text: bool = False  # final segment used ->> (text) vs -> (json)

    @property
    def output_key(self) -> str:
        if self.alias:
            return self.alias
        if self.json_path:
            return self.json_path[-1]
        return self.column


@dataclass
class SelectEmbed:
    relation: str  # related accessor name on the model
    alias: str | None = None
    children: list = field(default_factory=list)  # list[SelectField | SelectEmbed]

    @property
    def output_key(self) -> str:
        return self.alias or self.relation


def _parse_json_path(rest: str) -> tuple[list[str], bool]:
    """Parse the ``->a->>b`` portion after a base column."""
    segments: list[str] = []
    json_text = False
    # rest looks like "->a->b->>c"
    chunk = rest
    while chunk.startswith("->"):
        if chunk.startswith("->>"):
            json_text = True
            chunk = chunk[3:]
        else:
            json_text = False
            chunk = chunk[2:]
        # read until the next "->" or end
        nxt = chunk.find("->")
        seg = chunk if nxt == -1 else chunk[:nxt]
        segments.append(seg.strip().strip("'\""))
        chunk = "" if nxt == -1 else chunk[nxt:]
    return segments, json_text


def _parse_select_field(item: str) -> SelectField:
    alias = None
    if ":" in item and "::" not in item.split(":", 1)[0]:
        # alias:col  (avoid splitting the ::cast operator)
        maybe_alias, _, rest = item.partition(":")
        if rest and not rest.startswith(":"):
            alias = maybe_alias.strip()
            item = rest.strip()

    cast = None
    if "::" in item:
        item, _, cast = item.partition("::")
        cast = cast.strip()

    column = item
    json_path: list[str] = []
    json_text = False
    if "->" in item:
        column, sep, rest = item.partition("->")
        json_path, json_text = _parse_json_path(sep + rest)

    return SelectField(
        column=column.strip(),
        alias=alias,
        cast=cast,
        json_path=json_path,
        json_text=json_text,
    )


def parse_select(value: str) -> list:
    """Parse a ``select`` value into a list of SelectField / SelectEmbed nodes."""
    nodes: list = []
    for raw in split_top_level(value):
        item = raw.strip()
        if not item:
            continue
        if item == "*":
            continue  # "all fields" is the default; an explicit * is a no-op marker
        if "(" in item and item.endswith(")"):
            head, _, inner = item.partition("(")
            inner = inner[:-1]  # drop trailing ")"
            alias = None
            relation = head.strip()
            if ":" in relation:
                alias, _, relation = relation.partition(":")
                alias = alias.strip()
                relation = relation.strip()
            nodes.append(
                SelectEmbed(
                    relation=relation,
                    alias=alias,
                    children=parse_select(inner),
                ),
            )
        else:
            nodes.append(_parse_select_field(item))
    return nodes


# --------------------------------------------------------------------------- #
# order
# --------------------------------------------------------------------------- #
@dataclass
class OrderTerm:
    column: str
    descending: bool = False
    nulls: str | None = None  # "first" | "last" | None


def parse_order(value: str) -> list[OrderTerm]:
    terms: list[OrderTerm] = []
    for raw in split_top_level(value):
        item = raw.strip()
        if not item:
            continue
        parts = item.split(".")
        column = parts[0]
        descending = False
        nulls = None
        directions = {"asc": False, "desc": True}
        nulls_tokens = {"nullsfirst": "first", "nullslast": "last"}
        for token in parts[1:]:
            if token in directions:
                descending = directions[token]
            elif token in nulls_tokens:
                nulls = nulls_tokens[token]
            else:
                raise PostgrestError(
                    f"Invalid order token {token!r} in {item!r}",
                    code="PGRST-100",
                )
        terms.append(OrderTerm(column=column, descending=descending, nulls=nulls))
    return terms


def order_to_orm(terms: list[OrderTerm]) -> list:
    """Convert OrderTerms into ``OrderBy`` expressions / field strings."""
    from django.db.models import F

    expressions = []
    for t in terms:
        # ``nulls_first`` / ``nulls_last`` must be True or None (never False).
        nulls_kwargs: dict = {}
        if t.nulls == "first":
            nulls_kwargs["nulls_first"] = True
        elif t.nulls == "last":
            nulls_kwargs["nulls_last"] = True
        f = F(t.column)
        expr = f.desc(**nulls_kwargs) if t.descending else f.asc(**nulls_kwargs)
        expressions.append(expr)
    return expressions


# --------------------------------------------------------------------------- #
# logical or/and
# --------------------------------------------------------------------------- #
def _parse_logical(value: str, combinator: str) -> Q:
    """Parse the body of ``or=(...)`` / ``and=(...)`` into a combined ``Q``."""
    inner = value.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    combined: Q | None = None
    for raw in split_top_level(inner):
        cond = raw.strip()
        if not cond:
            continue
        q = _parse_condition(cond)
        if combined is None:
            combined = q
        elif combinator == "or":
            combined |= q
        else:
            combined &= q
    return combined if combined is not None else Q()


def _parse_condition(cond: str) -> Q:
    """Parse one condition inside a logical group.

    Either a nested ``and(...)`` / ``or(...)`` / ``not.and(...)`` group, or a
    leaf ``column.operator.value``.
    """
    negate = False
    if cond.startswith("not."):
        negate = True
        cond = cond[4:]

    if cond.startswith(("and(", "or(")):
        kind = "and" if cond.startswith("and(") else "or"
        body = cond[len(kind) :]
        q = _parse_logical(body, kind)
        return ~q if negate else q

    column, _, token = cond.partition(".")
    if not token:
        raise PostgrestError(f"Malformed condition {cond!r}", code="PGRST-100")
    q = build_q(column, ("not." + token) if negate else token)
    return q


# --------------------------------------------------------------------------- #
# top-level entry point
# --------------------------------------------------------------------------- #
@dataclass
class ParsedQuery:
    q: Q
    select: list | None  # None => all configured fields
    order: list  # list of ORM order expressions
    order_terms: list[OrderTerm]
    limit: int | None
    offset: int


def _base_column(name: str) -> str:
    """Strip ``->`` json paths and ``::`` casts to get the model field name."""
    return name.split("->", 1)[0].split("::", 1)[0]


def parse_request(request: HttpRequest, table) -> ParsedQuery:
    """Parse a request's GET params against a ``TableConfig``."""
    from .headers import parse_range

    params = request.GET
    q = Q()

    # Horizontal filters (column=op.value), allowing repeats.
    for key in params:
        if key in RESERVED_PARAMS:
            continue
        if "->" in key:
            raise PostgrestError(
                f"JSON-path filtering ({key!r}) is not supported yet",
                status=400,
                code="PGRST-400",
            )
        base = _base_column(key)
        if base not in table.filterable:
            raise PostgrestError(
                f"Column {base!r} is not filterable on table {table.name!r}",
                status=400,
                code="PGRST-400",
            )
        for token in params.getlist(key):
            q &= build_q(key, token)

    # Logical groups.
    for combinator in ("and", "or"):
        if combinator in params:
            for value in params.getlist(combinator):
                q &= _parse_logical(value, combinator)

    # select
    select = None
    if "select" in params:
        select = parse_select(params["select"])

    # order
    order_terms: list[OrderTerm] = []
    if "order" in params:
        order_terms = parse_order(params["order"])
        for t in order_terms:
            if _base_column(t.column) not in table.orderable:
                raise PostgrestError(
                    f"Column {t.column!r} is not orderable on table {table.name!r}",
                    status=400,
                    code="PGRST-400",
                )
    order = order_to_orm(order_terms)

    # limit / offset (query params take precedence over Range header)
    limit: int | None = None
    offset = 0
    range_offset, range_limit = parse_range(request)
    if range_offset is not None:
        offset = range_offset
        limit = range_limit
    if "limit" in params:
        limit = _int_param(params["limit"], "limit")
    if "offset" in params:
        offset = _int_param(params["offset"], "offset")

    return ParsedQuery(
        q=q,
        select=select,
        order=order,
        order_terms=order_terms,
        limit=limit,
        offset=offset,
    )


def _int_param(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise PostgrestError(
            f"{name} must be an integer, got {value!r}",
            code="PGRST-100",
        ) from exc
