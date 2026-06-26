# ninja_postgrest

A reusable Django app that builds a [Django-Ninja](https://django-ninja.dev/)
router exposing [PostgREST](https://postgrest.org)-compatible REST endpoints for
a configured set of models. It respects **django-guardian** object-level
permissions and plugs into **django-ninja** authentication.

The app is self-contained so it can later be split into its own pip package.

## Installation / wiring

1. Add the app to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [..., "guardian", "ninja_postgrest", ...]
   ```

2. Configure the tables (see below) via `NINJA_POSTGREST` in settings.

3. Mount the router on your `NinjaAPI`:

   ```python
   from ninja_postgrest import build_router

   api.add_router("/pg/", build_router())
   ```

   Tables are then served under `/<api-prefix>/pg/<table>`.

## Configuration

```python
NINJA_POSTGREST = {
    # Default django-ninja auth applied to every table (import path, callable,
    # instance, or list). Omit / set to None for no authentication.
    "DEFAULT_AUTH": "ninja.security.django_auth",

    # Default permission strategy: "guardian" | "model" | "open".
    "DEFAULT_PERMISSIONS": "guardian",

    # Hard cap on rows returned per request.
    "MAX_LIMIT": 1000,
    "DEFAULT_LIMIT": None,

    "TABLES": {
        # Shorthand: table name -> "app_label.ModelName".
        "pipelines": "pipelines.Pipeline",

        # Full form.
        "datasets": {
            "model": "datasets.Dataset",            # dotted path or model class
            "operations": ["list", "read", "create", "update", "delete"],
            "fields": [...],                        # exposed columns (default: all)
            "filterable": [...],                    # default: fields
            "orderable": [...],                     # default: fields
            "writable": [...],                      # accepted on write (default: editable, non-pk)
            "embeddable": ["configs", "pipeline"],  # relations allowed in select (default: none)
            "pk": "id",                             # single-object lookup field
            "auth": "...",                          # per-table auth override
            "permissions": "guardian",              # per-table strategy override
            "permission_map": {                     # per-action permission codenames
                "list": "datasets.view_dataset",
                "create": "datasets.add_dataset",
                "update": "datasets.change_dataset",
                "delete": "datasets.delete_dataset",
            },
        },
    },
}
```

Foreign keys are exposed as their scalar `*_id` column (e.g. `pipeline_id`) for
fields/filtering/ordering, while the relationship name (`pipeline`) is used for
embedding — matching PostgREST conventions.

## Endpoint contract

| Verb | Behaviour |
|------|-----------|
| `GET /pg/{t}` | List. Supports `select`, horizontal filters, `order`, `limit`/`offset` (and `Range`). `Accept: application/vnd.pgrst.object+json` returns a single object (406 unless exactly one row). `Prefer: count=exact` adds the exact total to `Content-Range`. |
| `POST /pg/{t}` | Insert one object or an array. `Prefer: return=representation` returns the created rows (201). |
| `PATCH /pg/{t}` | Update rows matching the filters with the JSON body. Returns rows with `Prefer: return=representation`. |
| `DELETE /pg/{t}` | Delete rows matching the filters. Returns rows with `Prefer: return=representation`. |

### Filtering operators

`?col=op.value`, optionally `not.` prefixed, combined with `&` (AND) or
`or=(…)` / `and=(…)`:

`eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `ilike`, `match`, `imatch`,
`in`, `is`, `isdistinct`, `cs`, `cd`, `ov`, `fts`/`plfts`/`phfts`/`wfts`.

### select / embedding

`?select=col,alias:col,col::cast,json->>path,relation(col,...)`. Embeds use
`select_related` for forward FK/O2O and a permission-filtered `prefetch_related`
for reverse-FK/M2M.

A relation may only be embedded when it is listed in `embeddable` **and** its
related model is itself a registered table. Embedding a relation whose model is
not registered is denied with a 400 — there is no permission policy under which
to expose it.

## Permissions

- **guardian** (default): lists/reads filtered via
  `get_objects_for_user(view_*)`; updates/deletes restricted to objects the user
  may `change`/`delete`; creates require the model-level `add` permission.
- **model**: plain `user.has_perm('app.view_model')`, no per-object filtering.
- **open**: no permission checks (ninja `auth` still applies).

## Known limitations (v1)

- **RPC** (`POST /rpc/{fn}`) is not implemented.
- Embeds are restricted to relations whose model is a registered table (others
  are denied). **Forward** (FK/O2O) embeds of registered models are not
  additionally permission-filtered; only reverse-FK/M2M embeds are. The parent
  row is already authorized.
- **JSON-path filtering** (`config->>x=eq.y`) is rejected with a 400; JSON paths
  are supported in `select` only.
- Full-text search and array/range operators require a PostgreSQL backend.
- FK disambiguation (`relation!fk(...)`) is not supported.

## Tests

```bash
docker compose exec backend pixi run -e dev pytest ninja_postgrest/tests
```

Integration tests additionally validate the endpoints through the standard
[`postgrest`](https://pypi.org/project/postgrest/) client library against a live
server.
