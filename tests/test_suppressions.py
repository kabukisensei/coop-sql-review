"""Inline ignore directives + the fingerprint baseline, and fingerprint stability."""

from coop_sql_review.finding import Finding
from coop_sql_review.suppressions import (
    is_inline_suppressed,
    load_baseline,
    scan_directives,
    write_baseline,
)


def test_scan_directives_parses_ids_and_stops_at_reason():
    text = "SELECT 1;\n-- coop-sql-review:ignore SQL-NO-SELECT-STAR reason: legacy SQL-NOT-THIS\nSELECT *;\n"
    assert scan_directives(text) == {2: {"SQL-NO-SELECT-STAR"}}  # post-reason token is not an id


def test_scan_directives_bare_is_wildcard():
    assert scan_directives("-- coop-sql-review:ignore\n") == {1: {"*"}}


def test_scan_directives_multiple_ids():
    assert scan_directives("-- coop-sql-review:ignore SQL-A, SQL-B\n") == {1: {"SQL-A", "SQL-B"}}


def test_is_inline_suppressed_same_line_and_line_above():
    directives = {5: {"SQL-X"}}
    assert is_inline_suppressed("SQL-X", 5, directives)  # trailing on the same line
    assert is_inline_suppressed("SQL-X", 6, directives)  # directive on the line directly above
    assert not is_inline_suppressed("SQL-X", 7, directives)  # too far away
    assert not is_inline_suppressed("SQL-Y", 5, directives)  # a different rule
    assert not is_inline_suppressed("SQL-X", 0, directives)  # file-level finding (line 0)


def test_wildcard_directive_suppresses_any_rule():
    assert is_inline_suppressed("SQL-ANYTHING", 3, {3: {"*"}})


def test_fingerprint_is_line_independent_but_rule_sensitive():
    a = Finding("SQL-A", "warning", "f.sql", 10, "o", "msg", "§1")
    moved = Finding("SQL-A", "warning", "f.sql", 99, "o", "msg", "§1")  # only line differs
    other = Finding("SQL-B", "warning", "f.sql", 10, "o", "msg", "§1")  # rule differs
    assert a.fingerprint() == moved.fingerprint()
    assert a.fingerprint() != other.fingerprint()


def test_baseline_roundtrip_is_deduped_and_sorted(tmp_path):
    path = tmp_path / "bl.json"
    assert write_baseline(path, ["zzz", "aaa", "aaa"]) == 2  # de-duplicated
    assert load_baseline(path) == {"aaa", "zzz"}
    assert '"aaa"' in path.read_text(encoding="utf-8")  # sorted, human-readable


def test_load_missing_or_malformed_baseline_is_empty(tmp_path):
    assert load_baseline(tmp_path / "nope.json") == set()
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_baseline(bad) == set()
