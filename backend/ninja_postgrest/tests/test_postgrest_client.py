"""Validate the generated endpoints against the standard ``postgrest`` client
library (https://pypi.org/project/postgrest/).

These exercise the real HTTP surface end-to-end: a live server, django-ninja
auth (via a session cookie), guardian filtering and the PostgREST query grammar
as produced by a third-party client rather than hand-built URLs.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

postgrest = pytest.importorskip("postgrest")
from postgrest import SyncPostgrestClient  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402

from guardian.shortcuts import assign_perm  # noqa: E402

from datasets.models import Dataset, DatasetConfig  # noqa: E402
from pipelines.models import Pipeline  # noqa: E402

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    pipeline = Pipeline.objects.create(
        slug="p1",
        name="Pipeline 1",
        config_schema={},
        description="",
        active=True,
    )
    ds1 = Dataset.objects.create(slug="alpha", pipeline=pipeline)
    Dataset.objects.create(slug="beta", pipeline=pipeline)
    DatasetConfig.objects.create(dataset=ds1, state=DatasetConfig.State.DRAFT)
    return pipeline


@pytest.fixture
def admin():
    return User.objects.create_superuser("admin", password="pw")  # noqa: S106


@pytest.fixture
def alice():
    return User.objects.create_user("alice", password="pw")  # noqa: S106


def pg_client(live_server, user) -> SyncPostgrestClient:
    """A PostgREST client authenticated as ``user`` via a Django session cookie."""
    django_client = Client()
    django_client.force_login(user)
    sessionid = django_client.cookies["sessionid"].value
    # base_url must end with "/" so httpx preserves the /backend/api/pg prefix
    # when it appends the table path.
    return SyncPostgrestClient(
        f"{live_server.url}/backend/api/pg/",
        headers={"Cookie": f"sessionid={sessionid}"},
    )


def test_client_select_and_order(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").order("slug").execute()
    assert [r["slug"] for r in res.data] == ["alpha", "beta"]
    # The projection is exact: no other columns leak into the rows.
    assert all(set(r.keys()) == {"slug"} for r in res.data)
    # Descending through the client's order grammar (order=slug.desc).
    res = pg.from_("datasets").select("slug").order("slug", desc=True).execute()
    assert [r["slug"] for r in res.data] == ["beta", "alpha"]


def test_client_filter_eq(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").eq("slug", "beta").execute()
    assert [r["slug"] for r in res.data] == ["beta"]


def test_client_filter_in(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").in_("slug", ["alpha", "beta"]).execute()
    assert {r["slug"] for r in res.data} == {"alpha", "beta"}


def test_client_limit(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").order("slug").limit(1).execute()
    assert [r["slug"] for r in res.data] == ["alpha"]


def test_client_single(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").eq("slug", "alpha").single().execute()
    assert res.data["slug"] == "alpha"


def test_client_count_exact(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug", count="exact").execute()
    assert res.count == 2


def test_client_embed_reverse_fk(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = (
        pg.from_("datasets")
        .select("slug,configs(state)")
        .eq("slug", "alpha")
        .single()
        .execute()
    )
    assert res.data["slug"] == "alpha"
    assert res.data["configs"] == [{"state": "Draft"}]


def test_client_embed_forward_fk(live_server, seeded, admin):
    # dataset_configs -> dataset is a forward FK to a registered table.
    pg = pg_client(live_server, admin)
    res = pg.from_("dataset_configs").select("state,dataset(slug)").single().execute()
    assert res.data["dataset"] == {"slug": "alpha"}


def test_client_guardian_filtering(live_server, seeded):
    """A user with no object permissions sees no rows through the client."""
    bob = User.objects.create_user("bob", password="pw")  # noqa: S106
    pg = pg_client(live_server, bob)
    res = pg.from_("datasets").select("slug").execute()
    assert res.data == []


# --------------------------------------------------------------------------- #
# Writes through the real client (insert / update / delete / upsert)
# --------------------------------------------------------------------------- #
def test_client_insert_single(live_server, seeded, admin):
    pipeline = seeded
    pg = pg_client(live_server, admin)
    res = (
        pg.from_("datasets")
        .insert({"slug": "gamma", "pipeline_id": pipeline.id, "state": "Active"})
        .execute()
    )
    # A single-object body still comes back as an array, matching PostgREST.
    assert [r["slug"] for r in res.data] == ["gamma"]
    assert Dataset.objects.filter(slug="gamma").exists()


def test_client_insert_bulk(live_server, seeded, admin):
    pipeline = seeded
    pg = pg_client(live_server, admin)
    res = (
        pg.from_("datasets")
        .insert(
            [
                {"slug": "gamma", "pipeline_id": pipeline.id},
                {"slug": "delta", "pipeline_id": pipeline.id},
            ],
        )
        .execute()
    )
    assert {r["slug"] for r in res.data} == {"gamma", "delta"}
    assert Dataset.objects.filter(slug__in=["gamma", "delta"]).count() == 2


def test_client_update(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = (
        pg.from_("datasets").update({"state": "Disabled"}).eq("slug", "alpha").execute()
    )
    assert [r["state"] for r in res.data] == ["Disabled"]
    assert Dataset.objects.get(slug="alpha").state == "Disabled"


def test_client_delete(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").delete().eq("slug", "beta").execute()
    assert [r["slug"] for r in res.data] == ["beta"]
    assert not Dataset.objects.filter(slug="beta").exists()
    assert Dataset.objects.filter(slug="alpha").exists()


def test_client_upsert_new_row(live_server, seeded, admin):
    # Without an on_conflict target an upsert degrades to a plain insert.
    pipeline = seeded
    pg = pg_client(live_server, admin)
    pg.from_("datasets").upsert(
        {"slug": "epsilon", "pipeline_id": pipeline.id},
    ).execute()
    assert Dataset.objects.filter(slug="epsilon").exists()


def test_client_upsert_merge_on_conflict(live_server, seeded, admin):
    # Upsert keyed on slug updates the existing "alpha" row rather than
    # colliding with its unique slug.
    pg = pg_client(live_server, admin)
    res = (
        pg.from_("datasets")
        .upsert({"slug": "alpha", "state": "Disabled"}, on_conflict="slug")
        .execute()
    )
    assert [r["slug"] for r in res.data] == ["alpha"]
    assert Dataset.objects.filter(slug="alpha").count() == 1
    assert Dataset.objects.get(slug="alpha").state == "Disabled"


# --------------------------------------------------------------------------- #
# Filter grammar as emitted by the client
# --------------------------------------------------------------------------- #
def test_client_like(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").like("slug", "al*").execute()
    assert [r["slug"] for r in res.data] == ["alpha"]


def test_client_ilike_case_insensitive(live_server, seeded, admin):
    # An upper-case pattern still matches the lower-case slug.
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").ilike("slug", "*LPH*").execute()
    assert [r["slug"] for r in res.data] == ["alpha"]


def test_client_range_comparison(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").gte("slug", "b").order("slug").execute()
    assert [r["slug"] for r in res.data] == ["beta"]


def test_client_or_filter(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    res = (
        pg.from_("datasets")
        .select("slug")
        .or_("slug.eq.alpha,slug.eq.beta")
        .order("slug")
        .execute()
    )
    assert [r["slug"] for r in res.data] == ["alpha", "beta"]


def test_client_is_null(live_server, seeded, admin):
    # No dataset has a null state, so is.null returns nothing — this exercises
    # the ``is`` operator round-tripping through the client and the endpoint.
    pg = pg_client(live_server, admin)
    res = pg.from_("datasets").select("slug").is_("state", "null").execute()
    assert res.data == []


# --------------------------------------------------------------------------- #
# Error contract: PostgREST JSON error shape as parsed by the client
# --------------------------------------------------------------------------- #
def test_client_single_multiple_rows_raises_apierror(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    with pytest.raises(APIError) as excinfo:
        pg.from_("datasets").select("slug").single().execute()
    err = excinfo.value
    assert err.code == "PGRST116"
    assert "exactly one row" in err.message


def test_client_non_filterable_column_raises_apierror(live_server, seeded, admin):
    pg = pg_client(live_server, admin)
    with pytest.raises(APIError) as excinfo:
        pg.from_("datasets").select("slug").eq("bogus", "1").execute()
    err = excinfo.value
    assert err.code == "PGRST-400"
    assert "not filterable" in err.message


# --------------------------------------------------------------------------- #
# Write authorization through the client (guardian filtering on update/delete)
# --------------------------------------------------------------------------- #
def test_client_update_filtered_by_guardian(live_server, seeded, alice):
    # alice may change alpha but not beta; an update matching both touches only
    # the row she can change.
    Dataset.objects.get(slug="alpha").assign_edit_permission(alice)
    pg = pg_client(live_server, alice)
    res = (
        pg.from_("datasets")
        .update({"state": "Disabled"})
        .eq("state", "Active")
        .execute()
    )
    assert [r["slug"] for r in res.data] == ["alpha"]
    assert Dataset.objects.get(slug="alpha").state == "Disabled"
    assert Dataset.objects.get(slug="beta").state == "Active"


def test_client_update_without_perm_is_noop(live_server, seeded, alice):
    pg = pg_client(live_server, alice)
    res = (
        pg.from_("datasets").update({"state": "Disabled"}).eq("slug", "alpha").execute()
    )
    assert res.data == []
    assert Dataset.objects.get(slug="alpha").state == "Active"


def test_client_delete_filtered_by_guardian(live_server, seeded, alice):
    # alice may delete alpha but not beta; a delete matching both removes only
    # the row she can delete.
    assign_perm("datasets.delete_dataset", alice, Dataset.objects.get(slug="alpha"))
    pg = pg_client(live_server, alice)
    res = pg.from_("datasets").delete().in_("slug", ["alpha", "beta"]).execute()
    assert [r["slug"] for r in res.data] == ["alpha"]
    assert not Dataset.objects.filter(slug="alpha").exists()
    assert Dataset.objects.filter(slug="beta").exists()
