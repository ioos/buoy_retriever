"""Unit tests for the query-string parser."""

from django.db.models import Q

from ninja_postgrest.parsing import (
    SelectEmbed,
    SelectField,
    _parse_logical,
    parse_order,
    parse_select,
    split_top_level,
)


def test_split_top_level_respects_parens():
    assert split_top_level("a,b(c,d),e") == ["a", "b(c,d)", "e"]


def test_parse_select_fields_and_embed():
    nodes = parse_select("slug,configs(state,created),pipeline_id")
    assert isinstance(nodes[0], SelectField)
    assert nodes[0].column == "slug"
    assert isinstance(nodes[1], SelectEmbed)
    assert nodes[1].relation == "configs"
    assert [c.column for c in nodes[1].children] == ["state", "created"]
    assert isinstance(nodes[2], SelectField)
    assert nodes[2].column == "pipeline_id"


def test_parse_select_alias_and_cast():
    (node,) = parse_select("name:slug")
    assert node.alias == "name"
    assert node.column == "slug"
    assert node.output_key == "name"

    (cast_node,) = parse_select("count::text")
    assert cast_node.column == "count"
    assert cast_node.cast == "text"


def test_parse_select_json_path():
    (node,) = parse_select("config->>units")
    assert node.column == "config"
    assert node.json_path == ["units"]
    assert node.json_text is True


def test_parse_order():
    terms = parse_order("created.desc.nullslast,slug")
    assert terms[0].column == "created"
    assert terms[0].descending is True
    assert terms[0].nulls == "last"
    assert terms[1].column == "slug"
    assert terms[1].descending is False


def test_logical_or():
    q = _parse_logical("(slug.eq.a,slug.eq.b)", "or")
    assert q == (Q(slug__exact="a") | Q(slug__exact="b"))


def test_logical_and():
    q = _parse_logical("(state.eq.Active,slug.eq.a)", "and")
    assert q == (Q(state__exact="Active") & Q(slug__exact="a"))
