"""Inline ignore directives + the fingerprint baseline, and fingerprint stability."""

from coop_sql_review.finding import AgentReviewItem, Finding
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


def test_fingerprint_is_path_independent():
    # The display path is cwd-relative (or absolute cross-drive), so hashing it
    # would break baselines/ignores run from another folder or machine. Identity
    # is (rule_id, object, message) — the file NEVER participates.
    a = Finding("SQL-A", "warning", "proj/f.sql", 10, "o", "msg", "§1")
    b = Finding("SQL-A", "warning", "f.sql", 10, "o", "msg", "§1")  # another cwd's view
    c = Finding("SQL-A", "warning", "/abs/elsewhere/f.sql", 10, "o", "msg", "§1")
    assert a.fingerprint() == b.fingerprint() == c.fingerprint()
    # ...but the logical identity fields still discriminate.
    assert a.fingerprint() != Finding("SQL-A", "warning", "proj/f.sql", 10, "o2", "msg", "§1").fingerprint()
    assert a.fingerprint() != Finding("SQL-A", "warning", "proj/f.sql", 10, "o", "msg2", "§1").fingerprint()


def test_agent_item_fingerprint_is_path_independent():
    a = AgentReviewItem("SQL-X", "proj/m.sql", "gold.t", 5, "note", "§5")
    b = AgentReviewItem("SQL-X", "m.sql", "gold.t", 5, "note", "§5")
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != AgentReviewItem("SQL-X", "m.sql", "gold.u", 5, "note", "§5").fingerprint()


def test_fingerprint_object_less_uses_basename_so_files_do_not_collapse():
    # issue #3: with object="", the file BASENAME stands in for the object, so two files'
    # object-less findings don't collapse to ONE fingerprint (which would let a baselined
    # one silently hide a new one elsewhere). Only the basename participates, so it stays
    # cwd-independent.
    a = Finding("SQL-EXISTS-COMMENT", "info", "dir1/a.sql", 3, "", "explain why", "§7")
    b = Finding("SQL-EXISTS-COMMENT", "info", "dir2/b.sql", 9, "", "explain why", "§7")
    assert a.fingerprint() != b.fingerprint()  # different files -> different fingerprints
    # ...but the SAME file seen from another cwd still collapses (basename is cwd-independent).
    a_other_cwd = Finding("SQL-EXISTS-COMMENT", "info", "/abs/elsewhere/a.sql", 3, "", "explain why", "§7")
    assert a.fingerprint() == a_other_cwd.fingerprint()


def test_agent_item_object_less_uses_basename():
    # Two files each with a BEGIN TRAN (SQL-TXN-SHORT emits object="", constant note)
    # must produce DISTINCT agent-review fingerprints.
    a = AgentReviewItem("SQL-TXN-SHORT", "a.sql", "", 5, "keep transactions short", "§X")
    b = AgentReviewItem("SQL-TXN-SHORT", "b.sql", "", 5, "keep transactions short", "§X")
    assert a.fingerprint() != b.fingerprint()


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
