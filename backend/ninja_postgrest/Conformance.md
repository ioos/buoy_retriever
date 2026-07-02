# PostgREST conformance

How `ninja_postgrest` maps onto the [PostgREST](https://postgrest.org) API, and
where it currently deviates. This is a v1 implementation targeting the common
read/write surface used by the standard
[`postgrest`](https://pypi.org/project/postgrest/) client, not full parity.

See [README.md](./README.md) for configuration and [Findings.md](./Findings.md)
for the open work behind the deviations below.

## Conforms

### Filtering
- Horizontal filters `?col=op.value`, repeatable (`&`-combined as AND).
- `not.` negation prefix on any operator.
- Logical groups `or=(...)` / `and=(...)`, including nesting and `not.and(...)` /
  `not.or(...)`. Columns inside a group honour the same `filterable` allowlist as
  plain filters.
- Operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `ilike`, `match`,
  `imatch`, `in`, `is`, `isdistinct`, `cs`, `cd`, `ov`, `fts`/`plfts`/`phfts`/`wfts`.

### Selection & embedding
- `select` projection: bare columns, `alias:col`, `col::cast` (cast is
  informational), JSON paths `col->a->>b`.
- Resource embedding `relation(col,...)` with aliases and arbitrary nesting.
- Forward FK/O2O embeds resolve to a single object (or `null`); reverse-FK/M2M
  embeds resolve to an array.
- Foreign keys surface as their scalar `*_id` column; the relation name is used
  only for embeds.

### Ordering & pagination
- `order` with `asc`/`desc` and `nullsfirst`/`nullslast`, multiple terms.
- `limit` / `offset` query params.
- `Range: 0-9` request header (query params take precedence).
- `MAX_LIMIT` hard cap on rows returned per request (analogous to PostgREST's
  `db-max-rows`).
- `DEFAULT_LIMIT` is the default page size applied when a request gives no
  `limit`/`Range`, still bounded by `MAX_LIMIT`.

### Responses
- `Content-Range` response header, including the empty-page `*/<total>` form.
- `Prefer: count=exact` adds the exact total to `Content-Range`.
- Singular responses via `Accept: application/vnd.pgrst.object+json`, returning
  406 unless exactly one row matches (on `GET`).
- Single-object insert returns an array (collapsed to one object only under the
  singular media type).
- `Prefer: return=representation` returns affected rows on write.
- Insert (`POST`) sets a `Location` header pointing at the created row(s) (a PK
  filter: `?id=eq.5`, or `?id=in.(1,2)` for a bulk insert).
- `PATCH` / `DELETE` honour the singular media type when returning a
  representation: 406 (`PGRST116`) unless exactly one row is affected, and the
  write does not take effect (rolled back / not deleted) on that 406.

### Writes
- `POST` insert of one object or an array.
- `PATCH` / `DELETE` of rows matching the request filters.
- Upsert via `Prefer: resolution=merge-duplicates` / `ignore-duplicates` plus
  `?on_conflict=col[,col2]`; without an `on_conflict` target the request
  degrades to a plain insert.
- `?columns=col[,col2]` restricts the insert column set (`POST` only): body
  keys not listed are ignored (dropped/defaulted) rather than rejected, for
  both plain inserts and upserts.

### Errors
- JSON error body shape `{message, details, hint, code}`.
- Singular response with 0 or >1 rows returns `code: "PGRST116"` (status 406),
  matching real PostgREST.
- Query-string / operator parse errors return `code: "PGRST100"` (status 400),
  matching real PostgREST.

## Deviates

| Area | PostgREST | This app | Tracking |
|------|-----------|----------|----------|
| Error `code` values | Real codes (`PGRST116`, `PGRST100`, ...) and pass-through Postgres `SQLSTATE`s | `PGRST116` (singular no/multiple rows) and `PGRST100` (query-parse) now match PostgREST exactly. Remaining hyphenated `PGRST-4xx` codes are app-specific markers with no exact PostgREST equivalent (PostgREST would surface a Postgres `SQLSTATE` or a `PGRST2xx` there): `PGRST-400` (not-filterable/not-writable column, bad embed, invalid body, unknown `on_conflict`/`columns`), `PGRST-403` (permission denied), `PGRST-404` (unknown table) | [F-7](./Findings.md) |
| JSON-path filtering | `config->>x=eq.y` filters on JSON paths | Rejected with 400; JSON paths work in `select` only | README v1 limitation |
| `->>` text cast in `select` | `->>` returns the value as *text* (`"2"`) | The parsed `->`/`->>` distinction is not applied during serialization: both return the raw JSON value (`2`, `true`, objects) | [F-10](./Findings.md) |
| Forward-embed permissions | — | Forward (FK/O2O) embeds of registered models are **not** permission-filtered; only reverse-FK/M2M embeds are (the parent row is already authorized) | README v1 limitation |
| FK disambiguation | `relation!fk(...)` picks a specific FK | Not supported | README v1 limitation |
| RPC | `POST /rpc/{fn}` | Not implemented | README v1 limitation |
| PG-only operators | Work on PostgreSQL | `cs`/`cd`/`ov` and the FTS family require a PostgreSQL backend (no-op/raise on SQLite) | README v1 limitation |
