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
  `imatch`, `in`, `is`, `cs`, `cd`, `ov`, `fts`/`plfts`/`phfts`/`wfts`.
  (`isdistinct` is implemented but has a NULL bug — see Deviates.)

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

### Responses
- `Content-Range` response header, including the empty-page `*/<total>` form.
- `Prefer: count=exact` adds the exact total to `Content-Range`.
- Singular responses via `Accept: application/vnd.pgrst.object+json`, returning
  406 unless exactly one row matches (on `GET`).
- Single-object insert returns an array (collapsed to one object only under the
  singular media type).
- `Prefer: return=representation` returns affected rows on write.

### Writes
- `POST` insert of one object or an array.
- `PATCH` / `DELETE` of rows matching the request filters.
- Upsert via `Prefer: resolution=merge-duplicates` / `ignore-duplicates` plus
  `?on_conflict=col[,col2]`; without an `on_conflict` target the request
  degrades to a plain insert.

### Errors
- JSON error body shape `{message, details, hint, code}`.

## Deviates

| Area | PostgREST | This app | Tracking |
|------|-----------|----------|----------|
| `isdistinct` | `IS DISTINCT FROM` is NULL-safe (`NULL isdistinct 5` → true) | Compiled as `~Q(col__exact=v)`, which excludes `NULL` rows — a matching NULL row is dropped | [F-1](./Findings.md) |
| Default page size | `db-max-rows` caps; a server may set a default limit | Only `MAX_LIMIT` (the cap) is honoured. `DEFAULT_LIMIT` is read from settings and documented but never applied, so there is no default page size below the cap | [F-2](./Findings.md) |
| Error `code` values | Codes like `PGRST116` (no/multiple rows), and pass-through Postgres `SQLSTATE`s | Custom codes (`PGRST-400`, `PGRST-406`, ...). A client keying on `err.code` will not see real PostgREST codes | [F-7](./Findings.md) |
| Insert `Location` header | Returns a `Location` header for created rows | Not set | [F-8](./Findings.md) |
| Singular `Accept` on writes | `PATCH`/`DELETE` honour the singular media type | `PATCH`/`DELETE` always return an array | [F-8](./Findings.md) |
| `columns` param | Restricts the columns considered on insert | Reserved but unimplemented — `?columns=` is silently ignored | [F-4](./Findings.md) |
| JSON-path filtering | `config->>x=eq.y` filters on JSON paths | Rejected with 400; JSON paths work in `select` only | README v1 limitation |
| Forward-embed permissions | — | Forward (FK/O2O) embeds of registered models are **not** permission-filtered; only reverse-FK/M2M embeds are (the parent row is already authorized) | README v1 limitation |
| FK disambiguation | `relation!fk(...)` picks a specific FK | Not supported | README v1 limitation |
| RPC | `POST /rpc/{fn}` | Not implemented | README v1 limitation |
| PG-only operators | Work on PostgreSQL | `cs`/`cd`/`ov` and the FTS family require a PostgreSQL backend (no-op/raise on SQLite) | README v1 limitation |
