# Findings & open work

Tracked follow-ups for `ninja_postgrest`, so they survive across sessions.
Grouped by kind and roughly in priority order. IDs (F-N) are referenced from
[Conformance.md](./Conformance.md).

Status legend: `[ ]` open · `[~]` in progress · `[x]` done.

## Correctness

- [x] **F-1 — `isdistinct` drops NULL rows.** `operators.py` compiles
  `isdistinct` as `~Q(col__exact=value)`, which (like Django's `.exclude()`)
  excludes rows where the column `IS NULL`. PostgREST's `IS DISTINCT FROM` is
  NULL-safe, so a NULL row is *distinct* from any non-null value and should be
  returned. Fix: `~Q(col__exact=value) | Q(col__isnull=True)`. Add a test with a
  NULL-valued column. (`neq` is fine as-is — `<>` also excludes NULLs.)

- [x] **F-2 — `DEFAULT_LIMIT` is loaded but never applied.**
  `conf.py` reads `default_limit` and it appears in the README config example,
  but `query.slice_queryset` only consults `max_limit`. Either wire
  `default_limit` in as the effective page size when the request specifies no
  `limit`/`Range`, or remove the setting and its README mention.

## Dead code / cleanup

- [ ] **F-3 — `schemas.py` is unused.** `get_full_schema`,
  `reset_schema_cache`, and `JsonBody` have no call sites, so the intended
  OpenAPI full-row response schema is never generated (routes register raw view
  callables with no `response=`). Either wire `get_full_schema` into
  `router.add_api_operation(..., response=...)`, or delete the module.

- [ ] **F-4 — `columns` reserved param is a no-op.** `parsing.RESERVED_PARAMS`
  reserves `columns` but nothing implements PostgREST's insert column
  restriction, so `?columns=` is silently ignored. Implement it or drop it from
  the reserved set and note the gap.

## Tests

- [ ] **F-5 — Reduce duplication between `test_endpoints.py` and
  `test_postgrest_client.py`.** The client suite re-covers plain CRUD/filter
  cases the raw-URL suite already asserts identically (`select`+`order`,
  `filter_eq`, `filter_in`, `limit`, `count_exact`, forward/reverse embed,
  single-object, basic insert/bulk/update/delete). Keep the client suite focused
  on what only it can exercise — the wire grammar the `postgrest` library emits,
  session-cookie auth, `APIError` JSON-shape assertions, and guardian-filtered
  writes — and let `test_endpoints.py` own the plain CRUD/filter matrix.

- [ ] **F-6 — Fill operator/feature coverage holes.** No tests currently cover:
  `match`/`imatch`, `isdistinct` (hides F-1), array/range ops `cs`/`cd`/`ov`,
  the FTS family `fts`/`plfts`/`phfts`/`wfts`; nor `Range`-header pagination,
  `offset`, `nullsfirst`/`nullslast` ordering, JSON-path *serialization*
  (`_dig_json` is parsed but never rendered end-to-end), or `select`
  alias/`::cast` output keys. Prefer adding the grammar-level ones through the
  `postgrest` client (`.match`, `.contains`, `.text_search`, `.range`) so they
  are verified against real client output. PG-only operators need a PostgreSQL
  backend or a documented skip.

## Standard parity (larger scope)

- [ ] **F-7 — Error codes.** Emit PostgREST-compatible `code` values (e.g.
  `PGRST116` for no/multiple rows on singular) instead of the custom `PGRST-4xx`
  strings, so clients keying on `err.code` behave as they would against
  PostgREST.

- [ ] **F-8 — Write-response parity.** Set a `Location` header on insert, and
  honour the singular `application/vnd.pgrst.object+json` media type on
  `PATCH`/`DELETE` (currently they always return an array).

- [ ] **F-9 — Documented v1 gaps** (from README "Known limitations"): RPC
  (`POST /rpc/{fn}`), FK disambiguation (`relation!fk(...)`), JSON-path
  *filtering*, and forward-embed permission filtering.
