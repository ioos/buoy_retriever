"""Unit tests for PostgREST operator -> Django ``Q`` translation."""

from django.db.models import Q

from ninja_postgrest.operators import build_q


def test_eq():
    assert build_q("age", "eq.18") == Q(age__exact="18")


def test_comparisons():
    assert build_q("age", "gte.18") == Q(age__gte="18")
    assert build_q("age", "lt.5") == Q(age__lt="5")


def test_neq_is_negated():
    assert build_q("name", "neq.bob") == ~Q(name__exact="bob")


def test_not_prefix_negates():
    assert build_q("age", "not.gte.18") == ~Q(age__gte="18")


def test_like_translates_star_to_percent():
    assert build_q("name", "like.J*") == Q(name__like="J%")


def test_in_parses_list():
    assert build_q("id", "in.(1,2,3)") == Q(id__in=["1", "2", "3"])


def test_is_null():
    assert build_q("deleted", "is.null") == Q(deleted__isnull=True)


def test_is_true():
    assert build_q("active", "is.true") == Q(active__exact=True)


def test_isdistinct_is_null_safe():
    # IS DISTINCT FROM must return NULL rows too, unlike a bare ~exact.
    assert build_q("age", "isdistinct.5") == (~Q(age__exact="5") | Q(age__isnull=True))


def test_match_and_imatch_are_regex():
    assert build_q("slug", "match.^al") == Q(slug__regex="^al")
    assert build_q("slug", "imatch.^AL") == Q(slug__iregex="^AL")


def test_set_operators_parse_lists():
    # PG array/range operators translate to the PG-specific lookups; SQLite
    # cannot execute them, so coverage is at the Q-translation level.
    assert build_q("tags", "cs.{a,b}") == Q(tags__contains=["a", "b"])
    assert build_q("tags", "cd.{a,b}") == Q(tags__contained_by=["a", "b"])
    assert build_q("tags", "ov.{a,b}") == Q(tags__overlap=["a", "b"])


def test_fts_operators_build_search_queries():
    from django.contrib.postgres.search import SearchQuery

    assert build_q("description", "fts.cat") == Q(
        description__search=SearchQuery("cat", config=None, search_type="plain"),
    )
    assert build_q("description", "plfts.cat") == Q(
        description__search=SearchQuery("cat", config=None, search_type="plain"),
    )
    assert build_q("description", "phfts.fat cat") == Q(
        description__search=SearchQuery("fat cat", config=None, search_type="phrase"),
    )
    assert build_q("description", "wfts.fat or cat") == Q(
        description__search=SearchQuery(
            "fat or cat",
            config=None,
            search_type="websearch",
        ),
    )


def test_fts_config_modifier():
    from django.contrib.postgres.search import SearchQuery

    assert build_q("description", "fts(english).cat") == Q(
        description__search=SearchQuery("cat", config="english", search_type="plain"),
    )
