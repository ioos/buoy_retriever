"""Integration tests for the raw HTTP surface: auth/permissions, status codes
and headers, settings overrides, and behaviors the ``postgrest`` client
library cannot express. The plain CRUD/filter matrix lives in
``test_postgrest_client.py``.
"""

import json

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from guardian.shortcuts import assign_perm

from ninja_postgrest.conf import reset_global_config
from ninja_postgrest.registry import reset_registry

from datasets.models import Dataset, DatasetConfig
from pipelines.models import Pipeline

User = get_user_model()
PG = "/backend/api/pg"

pytestmark = pytest.mark.django_db


@pytest.fixture
def pipeline():
    return Pipeline.objects.create(
        slug="p1",
        name="Pipeline 1",
        config_schema={},
        description="",
        active=True,
    )


@pytest.fixture
def datasets(pipeline):
    ds1 = Dataset.objects.create(slug="alpha", pipeline=pipeline)
    ds2 = Dataset.objects.create(slug="beta", pipeline=pipeline)
    return ds1, ds2


@pytest.fixture
def alice():
    return User.objects.create_user("alice", password="pw")  # noqa: S106


@pytest.fixture
def admin():
    return User.objects.create_superuser("admin", password="pw")  # noqa: S106


def client_for(user):
    c = Client()
    c.force_login(user)
    return c


# --------------------------------------------------------------------------- #
# Read + guardian filtering
# --------------------------------------------------------------------------- #
def test_list_filtered_by_guardian(datasets, alice):
    ds1, _ds2 = datasets
    ds1.assign_view_permission(alice)
    resp = client_for(alice).get(f"{PG}/datasets")
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["slug"] for r in rows} == {"alpha"}


def test_superuser_sees_all(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets")
    assert {r["slug"] for r in resp.json()} == {"alpha", "beta"}


def test_anonymous_unauthorized(datasets):
    # The table inherits DEFAULT_AUTH (django_auth), so anonymous is rejected.
    resp = Client().get(f"{PG}/datasets")
    assert resp.status_code == 401


def test_authenticated_without_perms_sees_nothing(datasets, alice):
    # alice is logged in but has no object permissions on any dataset.
    resp = client_for(alice).get(f"{PG}/datasets")
    assert resp.status_code == 200
    assert resp.json() == []


def test_fk_serialized_as_scalar_id(datasets, admin, pipeline):
    rows = client_for(admin).get(f"{PG}/datasets").json()
    assert rows[0]["pipeline_id"] == pipeline.id


# --------------------------------------------------------------------------- #
# Horizontal / vertical filtering, ordering, pagination
# --------------------------------------------------------------------------- #
def test_content_range_header(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets")
    assert resp.headers["Content-Range"] == "0-1/*"


def test_default_limit_applied_when_unspecified(datasets, admin):
    # With DEFAULT_LIMIT=1 and no explicit limit, only one row is returned.
    overridden = {**settings.NINJA_POSTGREST, "DEFAULT_LIMIT": 1}
    with override_settings(NINJA_POSTGREST=overridden):
        reset_global_config()
        reset_registry()
        try:
            resp = client_for(admin).get(f"{PG}/datasets?order=slug.asc")
            assert resp.status_code == 200
            assert [r["slug"] for r in resp.json()] == ["alpha"]
            assert resp.headers["Content-Range"] == "0-0/*"
        finally:
            reset_global_config()
            reset_registry()


def test_explicit_limit_overrides_default_limit(datasets, admin):
    overridden = {**settings.NINJA_POSTGREST, "DEFAULT_LIMIT": 1}
    with override_settings(NINJA_POSTGREST=overridden):
        reset_global_config()
        reset_registry()
        try:
            rows = client_for(admin).get(f"{PG}/datasets?order=slug.asc&limit=2").json()
            assert [r["slug"] for r in rows] == ["alpha", "beta"]
        finally:
            reset_global_config()
            reset_registry()


# --------------------------------------------------------------------------- #
# Singular responses
# --------------------------------------------------------------------------- #
SINGULAR = "application/vnd.pgrst.object+json"


def test_single_object_multiple_rows_406(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets", headers={"Accept": SINGULAR})
    assert resp.status_code == 406


# --------------------------------------------------------------------------- #
# Embedding
# --------------------------------------------------------------------------- #
def test_embed_unregistered_model_denied(datasets, admin):
    # 'pipeline' is listed as embeddable, but we simulate Pipeline not being a
    # registered table by removing it from TABLES for this test.
    tables_without_pipelines = {
        k: v for k, v in settings.NINJA_POSTGREST["TABLES"].items() if k != "pipelines"
    }
    overridden = {**settings.NINJA_POSTGREST, "TABLES": tables_without_pipelines}
    with override_settings(NINJA_POSTGREST=overridden):
        reset_global_config()
        reset_registry()
        try:
            resp = client_for(admin).get(f"{PG}/datasets?select=slug,pipeline(slug)")
            assert resp.status_code == 400
            assert "not a registered table" in resp.json()["message"]
        finally:
            reset_global_config()
            reset_registry()


def test_embed_not_allowed_400(datasets, admin):
    # 'pipeline' is embeddable but a non-listed relation should 400.
    resp = client_for(admin).get(f"{PG}/datasets?select=slug,nonsense(x)")
    assert resp.status_code == 400


def test_embed_reverse_fk_permission_filtered(datasets, alice):
    """A registered embedded model (dataset_configs) is permission-filtered:
    alice can view the parent dataset but not its configs, so the embed is empty.
    """
    ds1, _ = datasets
    ds1.assign_view_permission(alice)
    DatasetConfig.objects.create(dataset=ds1, state=DatasetConfig.State.DRAFT)

    rows = (
        client_for(alice)
        .get(
            f"{PG}/datasets?slug=eq.alpha&select=slug,configs(state)",
            headers={"Accept": SINGULAR},
        )
        .json()
    )
    assert rows["slug"] == "alpha"
    assert rows["configs"] == []  # filtered: no view_datasetconfig grant


def test_embed_reverse_fk_visible_when_granted(datasets, alice):
    """Granting object-level view on the embedded config makes it appear."""
    ds1, _ = datasets
    ds1.assign_view_permission(alice)
    config = DatasetConfig.objects.create(dataset=ds1, state=DatasetConfig.State.DRAFT)
    assign_perm("datasets.view_datasetconfig", alice, config)

    rows = (
        client_for(alice)
        .get(
            f"{PG}/datasets?slug=eq.alpha&select=slug,configs(state)",
            headers={"Accept": SINGULAR},
        )
        .json()
    )
    assert rows["configs"] == [{"state": "Draft"}]


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def test_create_single_object_accept(pipeline, admin):
    # The singular media type collapses the array to one object.
    body = {"slug": "gamma", "pipeline_id": pipeline.id, "state": "Active"}
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "return=representation", "Accept": SINGULAR},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "gamma"


def test_delete(datasets, admin):
    # The client's test_client_delete always requests a representation; this
    # raw test is the only assertion of the 204 no-representation path and the
    # literal status code (the client hides status codes).
    resp = client_for(admin).delete(f"{PG}/datasets?slug=eq.beta")
    assert resp.status_code == 204
    assert not Dataset.objects.filter(slug="beta").exists()


def test_create_sets_location_header(pipeline, admin):
    body = {"slug": "gamma", "pipeline_id": pipeline.id}
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 201
    obj = Dataset.objects.get(slug="gamma")
    assert resp.headers["Location"] == f"{PG}/datasets?id=eq.{obj.id}"


def test_create_bulk_location_uses_in_filter(pipeline, admin):
    body = [
        {"slug": "gamma", "pipeline_id": pipeline.id},
        {"slug": "delta", "pipeline_id": pipeline.id},
    ]
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 201
    g = Dataset.objects.get(slug="gamma").id
    d = Dataset.objects.get(slug="delta").id
    assert resp.headers["Location"] == f"{PG}/datasets?id=in.({g},{d})"


def test_patch_single_object_accept(datasets, admin):
    resp = client_for(admin).patch(
        f"{PG}/datasets?slug=eq.alpha",
        data=json.dumps({"state": "Disabled"}),
        content_type="application/json",
        headers={"Prefer": "return=representation", "Accept": SINGULAR},
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "alpha"  # a single object, not an array


def test_patch_singular_multiple_rows_406_rolls_back(datasets, admin):
    # No filter matches both alpha and beta; singular + representation -> 406,
    # and the update must roll back (both rows unchanged).
    resp = client_for(admin).patch(
        f"{PG}/datasets",
        data=json.dumps({"state": "Disabled"}),
        content_type="application/json",
        headers={"Prefer": "return=representation", "Accept": SINGULAR},
    )
    assert resp.status_code == 406
    assert Dataset.objects.get(slug="alpha").state == "Active"
    assert Dataset.objects.get(slug="beta").state == "Active"


def test_delete_single_object_accept(datasets, admin):
    resp = client_for(admin).delete(
        f"{PG}/datasets?slug=eq.beta",
        headers={"Prefer": "return=representation", "Accept": SINGULAR},
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "beta"  # a single object, not an array
    assert not Dataset.objects.filter(slug="beta").exists()


def test_delete_singular_multiple_rows_406_no_delete(datasets, admin):
    resp = client_for(admin).delete(
        f"{PG}/datasets",
        headers={"Prefer": "return=representation", "Accept": SINGULAR},
    )
    assert resp.status_code == 406
    assert Dataset.objects.count() == 2  # nothing deleted


def test_create_rejects_non_writable_column(pipeline, admin):
    body = {"slug": "delta", "pipeline_id": pipeline.id, "id": 999}
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_columns_ignores_extra_nonwritable_key(pipeline, admin):
    # Without ?columns=, a non-writable "id" key is a 400 (see
    # test_create_rejects_non_writable_column). With ?columns=slug,pipeline_id
    # the extra "id" key is dropped instead of rejected.
    body = {"slug": "delta", "pipeline_id": pipeline.id, "id": 999}
    resp = client_for(admin).post(
        f"{PG}/datasets?columns=slug,pipeline_id",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert Dataset.objects.filter(slug="delta").exists()


def test_columns_ignores_unlisted_values(pipeline, admin):
    # A value sent for a column NOT in ?columns= is ignored: state falls back to
    # its model default ("Active") rather than the "Disabled" we sent.
    body = {"slug": "gamma", "pipeline_id": pipeline.id, "state": "Disabled"}
    resp = client_for(admin).post(
        f"{PG}/datasets?columns=slug,pipeline_id",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "return=representation"},
    )
    assert resp.status_code == 201
    assert Dataset.objects.get(slug="gamma").state == "Active"


def test_columns_unknown_column_400(pipeline, admin):
    body = {"slug": "gamma", "pipeline_id": pipeline.id}
    resp = client_for(admin).post(
        f"{PG}/datasets?columns=bogus",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_columns_accepts_quoted_tokens(pipeline, admin):
    # Real PostgREST clients send quoted identifiers, e.g. columns="slug","pipeline_id".
    # The quoted form must behave identically to the unquoted form (extra "id" dropped).
    body = {"slug": "zeta", "pipeline_id": pipeline.id, "id": 999}
    resp = client_for(admin).post(
        f'{PG}/datasets?columns="slug","pipeline_id"',
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert Dataset.objects.filter(slug="zeta").exists()


def test_upsert_merge_duplicates_updates(datasets, admin):
    # Upsert keyed on slug updates the existing "alpha" row instead of
    # erroring on its unique constraint.
    body = {"slug": "alpha", "state": "Disabled"}
    resp = client_for(admin).post(
        f"{PG}/datasets?on_conflict=slug",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    assert resp.status_code == 201
    assert [r["slug"] for r in resp.json()] == ["alpha"]
    assert Dataset.objects.filter(slug="alpha").count() == 1
    assert Dataset.objects.get(slug="alpha").state == "Disabled"


def test_upsert_ignore_duplicates_keeps_existing(datasets, admin):
    body = {"slug": "alpha", "state": "Disabled"}
    resp = client_for(admin).post(
        f"{PG}/datasets?on_conflict=slug",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "resolution=ignore-duplicates"},
    )
    assert resp.status_code == 201
    # The existing row is left untouched.
    assert Dataset.objects.filter(slug="alpha").count() == 1
    assert Dataset.objects.get(slug="alpha").state == "Active"


def test_upsert_without_conflict_target_inserts(pipeline, admin):
    # No on_conflict target: an upsert degrades to a plain insert.
    body = {"slug": "gamma", "pipeline_id": pipeline.id}
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "resolution=merge-duplicates"},
    )
    assert resp.status_code == 201
    assert Dataset.objects.filter(slug="gamma").exists()


def _grant_add_dataset(user):
    user.user_permissions.add(Permission.objects.get(codename="add_dataset"))


def test_upsert_merge_denied_without_change_perm(datasets, alice):
    # alice may create datasets (model-level add) but has no change permission
    # on the existing "alpha", so a merge that would update it is forbidden.
    _grant_add_dataset(alice)
    body = {"slug": "alpha", "state": "Disabled"}
    resp = client_for(alice).post(
        f"{PG}/datasets?on_conflict=slug",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "resolution=merge-duplicates"},
    )
    assert resp.status_code == 403
    assert Dataset.objects.get(slug="alpha").state == "Active"  # unchanged


def test_upsert_merge_allowed_with_change_perm(datasets, alice):
    # Granting object-level change on "alpha" lets the merge update it.
    ds1, _ = datasets
    _grant_add_dataset(alice)
    ds1.assign_edit_permission(alice)  # view + change on alpha
    body = {"slug": "alpha", "state": "Disabled"}
    resp = client_for(alice).post(
        f"{PG}/datasets?on_conflict=slug",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "resolution=merge-duplicates"},
    )
    assert resp.status_code == 201
    assert Dataset.objects.get(slug="alpha").state == "Disabled"


def test_upsert_merge_inserts_new_row_with_add_perm(pipeline, alice):
    # A brand-new row is an insert, so the model-level add perm alone suffices.
    _grant_add_dataset(alice)
    body = {"slug": "gamma", "pipeline_id": pipeline.id}
    resp = client_for(alice).post(
        f"{PG}/datasets?on_conflict=slug",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "resolution=merge-duplicates"},
    )
    assert resp.status_code == 201
    assert Dataset.objects.filter(slug="gamma").exists()


# --------------------------------------------------------------------------- #
# Write authorization
# --------------------------------------------------------------------------- #
# Guardian filtering of PATCH/DELETE for non-superusers is covered end-to-end
# through the real client in test_postgrest_client.py. Here we only assert the
# auth layer applies to writes, which the (always-authenticated) client cannot.
def test_anonymous_write_unauthorized(datasets):
    # Writes inherit DEFAULT_AUTH, so an unauthenticated PATCH is rejected.
    resp = Client().patch(
        f"{PG}/datasets?slug=eq.alpha",
        data=json.dumps({"state": "Disabled"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert Dataset.objects.get(slug="alpha").state == "Active"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
def test_unknown_table_404(admin):
    resp = client_for(admin).get(f"{PG}/not_a_table")
    assert resp.status_code == 404


def test_non_filterable_column_400(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets?bogus=eq.1")
    assert resp.status_code == 400


def test_non_filterable_column_in_or_group_400(datasets, admin):
    # Logical groups must honour the same filterable allowlist as plain
    # filters, so a non-filterable column cannot sneak in via or=(...).
    resp = client_for(admin).get(f"{PG}/datasets?or=(bogus.eq.1,slug.eq.alpha)")
    assert resp.status_code == 400
    assert "not filterable" in resp.json()["message"]


def test_parse_error_uses_pgrst100(datasets, admin):
    # "slug=eq" has no operator.value form -> malformed operator parse error.
    resp = client_for(admin).get(f"{PG}/datasets?slug=eq")
    assert resp.status_code == 400
    assert resp.json()["code"] == "PGRST100"


# --------------------------------------------------------------------------- #
# OpenAPI documentation
# --------------------------------------------------------------------------- #
def test_openapi_documents_full_row_read_schema():
    from ninja import NinjaAPI

    from ninja_postgrest import build_router

    api = NinjaAPI()
    api.add_router("/pg/", build_router())
    schema = api.get_openapi_schema()
    # get_full_schema names the component "Postgrest_<Model>"; it appears in
    # components only because the GET operation references it via response=.
    assert "Postgrest_Dataset" in schema["components"]["schemas"]
    # The GET operation is registered with by_alias=True, so the component
    # must document the flat PostgREST scalar column (the FK attname), not
    # the nested Django relation name.
    props = schema["components"]["schemas"]["Postgrest_Dataset"]["properties"]
    assert "pipeline_id" in props  # flat PostgREST scalar column
    assert "pipeline" not in props  # not the nested relation name
