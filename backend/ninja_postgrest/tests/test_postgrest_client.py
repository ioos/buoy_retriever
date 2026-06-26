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
