"""Integration tests exercising the generated endpoints end-to-end.

These run against the project's configured tables (``datasets`` /
``dataset_configs``) so they cover the real django-ninja + guardian wiring.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from guardian.shortcuts import assign_perm

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
def test_filter_eq(datasets, admin):
    rows = client_for(admin).get(f"{PG}/datasets?slug=eq.beta").json()
    assert {r["slug"] for r in rows} == {"beta"}


def test_filter_in(datasets, admin):
    rows = client_for(admin).get(f"{PG}/datasets?slug=in.(alpha,beta)").json()
    assert {r["slug"] for r in rows} == {"alpha", "beta"}


def test_select_projection(datasets, admin):
    rows = client_for(admin).get(f"{PG}/datasets?select=slug").json()
    assert all(set(r.keys()) == {"slug"} for r in rows)


def test_order_desc(datasets, admin):
    rows = client_for(admin).get(f"{PG}/datasets?select=slug&order=slug.desc").json()
    assert [r["slug"] for r in rows] == ["beta", "alpha"]


def test_limit(datasets, admin):
    rows = client_for(admin).get(f"{PG}/datasets?order=slug.asc&limit=1").json()
    assert [r["slug"] for r in rows] == ["alpha"]


def test_content_range_header(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets")
    assert resp.headers["Content-Range"] == "0-1/*"


def test_count_exact(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets", headers={"Prefer": "count=exact"})
    assert resp.headers["Content-Range"] == "0-1/2"


# --------------------------------------------------------------------------- #
# Singular responses
# --------------------------------------------------------------------------- #
SINGULAR = "application/vnd.pgrst.object+json"


def test_single_object(datasets, admin):
    resp = client_for(admin).get(
        f"{PG}/datasets?slug=eq.alpha",
        headers={"Accept": SINGULAR},
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "alpha"


def test_single_object_multiple_rows_406(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets", headers={"Accept": SINGULAR})
    assert resp.status_code == 406


# --------------------------------------------------------------------------- #
# Embedding
# --------------------------------------------------------------------------- #
def test_embed_reverse_fk(datasets, admin):
    ds1, _ = datasets
    DatasetConfig.objects.create(dataset=ds1, state=DatasetConfig.State.DRAFT)
    rows = (
        client_for(admin)
        .get(
            f"{PG}/datasets?slug=eq.alpha&select=slug,configs(state)",
            headers={"Accept": SINGULAR},
        )
        .json()
    )
    assert rows["slug"] == "alpha"
    assert rows["configs"] == [{"state": "Draft"}]


def test_embed_forward_fk(datasets, admin):
    # dataset_configs -> dataset is a forward FK to a registered table.
    ds1, _ = datasets
    DatasetConfig.objects.create(dataset=ds1, state=DatasetConfig.State.DRAFT)
    rows = (
        client_for(admin)
        .get(
            f"{PG}/dataset_configs?select=state,dataset(slug)",
            headers={"Accept": SINGULAR},
        )
        .json()
    )
    assert rows["dataset"] == {"slug": "alpha"}


def test_embed_unregistered_model_denied(datasets, admin):
    # 'pipeline' is listed as embeddable, but Pipeline is not a registered
    # table -> embedding it is explicitly denied.
    resp = client_for(admin).get(f"{PG}/datasets?select=slug,pipeline(slug)")
    assert resp.status_code == 400
    assert "not a registered table" in resp.json()["message"]


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
def test_create(pipeline, admin):
    body = {"slug": "gamma", "pipeline_id": pipeline.id, "state": "Active"}
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Prefer": "return=representation"},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "gamma"
    assert Dataset.objects.filter(slug="gamma").exists()


def test_update(datasets, admin):
    resp = client_for(admin).patch(
        f"{PG}/datasets?slug=eq.alpha",
        data=json.dumps({"state": "Disabled"}),
        content_type="application/json",
        headers={"Prefer": "return=representation"},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["state"] == "Disabled"
    assert Dataset.objects.get(slug="alpha").state == "Disabled"


def test_delete(datasets, admin):
    resp = client_for(admin).delete(f"{PG}/datasets?slug=eq.beta")
    assert resp.status_code == 204
    assert not Dataset.objects.filter(slug="beta").exists()


def test_create_rejects_non_writable_column(pipeline, admin):
    body = {"slug": "delta", "pipeline_id": pipeline.id, "id": 999}
    resp = client_for(admin).post(
        f"{PG}/datasets",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
def test_unknown_table_404(admin):
    resp = client_for(admin).get(f"{PG}/not_a_table")
    assert resp.status_code == 404


def test_non_filterable_column_400(datasets, admin):
    resp = client_for(admin).get(f"{PG}/datasets?bogus=eq.1")
    assert resp.status_code == 400
