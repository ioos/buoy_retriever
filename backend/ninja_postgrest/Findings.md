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

- [x] **F-3 — `schemas.py` is unused.** `get_full_schema`,
  `reset_schema_cache`, and `JsonBody` have no call sites, so the intended
  OpenAPI full-row response schema is never generated (routes register raw view
  callables with no `response=`). Either wire `get_full_schema` into
  `router.add_api_operation(..., response=...)`, or delete the module.
  Resolved: `get_full_schema` is wired into the GET operation's `response=` in
  `router.py` (documents the full-row list shape; runtime output is unaffected
  since generated views return `HttpResponse` directly). `reset_schema_cache`
  is called from `reset_registry()`. `JsonBody` (no call sites) was removed.

- [x] **F-4 — `columns` reserved param is a no-op.** `parsing.RESERVED_PARAMS`
  reserves `columns` but nothing implements PostgREST's insert column
  restriction, so `?columns=` is silently ignored. Implement it or drop it from
  the reserved set and note the gap.
  Resolved: `views.py` filters `items` to the `?columns=` set (a listed column
  must be writable, else 400) right after the body is parsed, before the
  upsert/plain-insert branch, so both paths honour it. `POST` only, per
  PostgREST semantics.

## Tests

- [x] **F-5 — Reduce duplication between `test_endpoints.py` and
  `test_postgrest_client.py`.** The client suite re-covers plain CRUD/filter
  cases the raw-URL suite already asserts identically (`select`+`order`,
  `filter_eq`, `filter_in`, `limit`, `count_exact`, forward/reverse embed,
  single-object, basic insert/bulk/update/delete). Keep the client suite focused
  on what only it can exercise — the wire grammar the `postgrest` library emits,
  session-cookie auth, `APIError` JSON-shape assertions, and guardian-filtered
  writes — and let `test_endpoints.py` own the plain CRUD/filter matrix.
  Resolved: the resolution direction was inverted by decision — the client
  suite (`test_postgrest_client.py`) owns the duplicated CRUD/filter cases
  since it exercises the real wire grammar the `postgrest` library emits;
  `test_endpoints.py` keeps only raw-only concerns (auth/status codes,
  headers, settings overrides, and behaviors the client can't express). The
  11 raw-URL duplicates were removed from `test_endpoints.py` in favor of
  their existing `test_postgrest_client.py` counterparts, and
  `test_client_select_and_order` was extended to cover `desc` ordering.

- [x] **F-6 — Fill operator/feature coverage holes.** No tests currently cover:
  `match`/`imatch`, `isdistinct` (hides F-1), array/range ops `cs`/`cd`/`ov`,
  the FTS family `fts`/`plfts`/`phfts`/`wfts`; nor `Range`-header pagination,
  `offset`, `nullsfirst`/`nullslast` ordering, JSON-path *serialization*
  (`_dig_json` is parsed but never rendered end-to-end), or `select`
  alias/`::cast` output keys. Prefer adding the grammar-level ones through the
  `postgrest` client (`.match`, `.contains`, `.text_search`, `.range`) so they
  are verified against real client output. PG-only operators need a PostgreSQL
  backend or a documented skip.
  Resolved: split by what SQLite can execute. `match`/`imatch`,
  `isdistinct` (non-NULL path), `offset`, `Range`-header pagination (via
  `.range`/`.offset`, which emit `limit`/`offset` query params on this
  `postgrest` client version rather than a `Range` header), `nullsfirst`/
  `nullslast` ordering grammar, `select` alias and `::cast` output keys, and
  JSON-path serialization (`config->>units`, aliased nested digs) are all
  covered end-to-end through the real client (`test_postgrest_client.py`) and
  raw URLs (`test_endpoints.py`). `cs`/`cd`/`ov` and the FTS family
  (`fts`/`plfts`/`phfts`/`wfts`, incl. the `fts(config)` modifier) get
  grammar-level `Q`-shape unit tests in `test_operators.py` only, since no
  registered model has an ArrayField (cs/cd/ov) and SQLite has no
  `to_tsvector`/`@@` support (FTS). FTS additionally gets one documented
  `skipif(connection.vendor != "postgresql")` endpoint test in
  `test_endpoints.py` that will run if the suite is ever pointed at
  PostgreSQL; `cs`/`cd`/`ov` get no endpoint test even under skipif, since a
  PG run would still fail with no ArrayField model to exercise.

## Standard parity (larger scope)

- [x] **F-7 — Error codes.** Emit PostgREST-compatible `code` values (e.g.
  `PGRST116` for no/multiple rows on singular) instead of the custom `PGRST-4xx`
  strings, so clients keying on `err.code` behave as they would against
  PostgREST.
  Resolved: targeted subset applied — `PGRST-406`→`PGRST116` (singular
  no/multiple-rows) and `PGRST-100`→`PGRST100` (query-parse), both with HTTP
  statuses unchanged. The remaining `PGRST-400`/`PGRST-403`/`PGRST-404` codes
  are kept as-is and documented in `Conformance.md` as app-specific markers
  with no exact PostgREST equivalent.

- [x] **F-8 — Write-response parity.** Set a `Location` header on insert, and
  honour the singular `application/vnd.pgrst.object+json` media type on
  `PATCH`/`DELETE` (currently they always return an array).
  Resolved: `POST` sets `Location` to the request path plus a PK filter
  (`?id=eq.5`, or `?id=in.(1,2)` for a bulk insert) on every 201. `PATCH`/
  `DELETE` honour the singular media type when returning a representation:
  406 (`PGRST116`) unless exactly one row is affected, validated before the
  write takes effect (inside the update transaction so it rolls back; before
  `qs.delete()` for delete) so the mutation does not happen on a 406.

- [ ] **F-9 — Documented v1 gaps** (from README "Known limitations"): RPC
  (`POST /rpc/{fn}`), FK disambiguation (`relation!fk(...)`), JSON-path
  *filtering*, and forward-embed permission filtering.

- [ ] **F-10 — `->>` does not cast to text in `select`.** Surfaced while
  writing F-6's JSON-path serialization tests: parsing records the `->` vs
  `->>` distinction (`SelectField.json_text`), but serialization never
  consults it — `_dig_json` returns the raw JSON value either way, so
  `select=depth:config->nested->>depth` yields `2` (int) where PostgREST
  returns `"2"` (text). Fix would be to coerce in `_serialize_field` when
  `json_text` is set (PostgREST semantics: strings unquoted, other values as
  JSON text, `null` stays `NULL`), then update
  `test_client_json_path_serialization` to pin the text form. Documented in
  the Conformance Deviates table until then.
