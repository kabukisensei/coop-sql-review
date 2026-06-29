"""Tests for identifier helpers (original_name / qualify / normalize_identifier)."""

from __future__ import annotations

from coop_sql_review.identifiers import (
    normalize_identifier,
    original_name,
    qualify,
)


def test_original_name_strips_brackets_and_takes_bare_name():
    assert original_name("[dim].[Practice]") == "Practice"


def test_qualify_splits_schema_and_name():
    assert qualify("[dbo].[Foo]") == ("dbo", "foo")


def test_qualify_unqualified_defaults_to_dbo():
    assert qualify("customer") == ("dbo", "customer")


def test_qualify_drops_database_part():
    assert qualify("mydb.myschema.mytable") == ("myschema", "mytable")


def test_normalize_identifier_lowercases_and_strips():
    assert normalize_identifier("[dbo].[Fact Sales]") == "dbo.fact sales"


def test_original_name_keeps_dot_inside_single_bracketed_token():
    # REGRESSION: in T-SQL [a.b] is ONE identifier literally named "a.b" — the
    # dot is part of the name, not a qualifier separator. Stripping brackets
    # before splitting on '.' wrongly truncated this to "b".
    assert original_name("[a.b]") == "a.b"


def test_qualify_keeps_dot_inside_single_bracketed_token():
    # REGRESSION: [a.b] is an unqualified name "a.b" in schema dbo, not a.b.
    assert qualify("[a.b]") == ("dbo", "a.b")


def test_normalize_keeps_dot_inside_single_bracketed_token():
    # REGRESSION: the embedded dot survives normalization (lowercased name).
    assert normalize_identifier("[a.b]") == "a.b"


def test_qualify_schema_with_dotted_bracketed_name():
    # REGRESSION: a top-level dot still separates schema from a dotted name.
    assert qualify("[s].[a.b]") == ("s", "a.b")
    assert original_name("[s].[a.b]") == "a.b"
