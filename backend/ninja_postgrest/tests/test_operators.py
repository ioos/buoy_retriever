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
