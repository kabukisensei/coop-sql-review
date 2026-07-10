"""The family fingerprint identity rule (schema_version 4, issue #16).

Identity = (rule_id, object-or-file-basename, fingerprint_key-or-message,
occurrence ordinal) — the SAME construction as coop-dax-review's schema 3
(which adds its ``model`` component). Test names mirror the dax twin's
``tests/test_fingerprint_identity.py`` so the family contract stays visibly
in lockstep.
"""

from __future__ import annotations

import hashlib
import json

from click.testing import CliRunner

from coop_sql_review.cli import cli
from coop_sql_review.engine import run_rules
from coop_sql_review.finding import AgentReviewItem, Finding, assign_occurrences
from coop_sql_review.parser import parse_sql
from coop_sql_review.rules import all_rules

# One proc, TWO SELECT * — the constant-message collapse case from issue #16.
_PROC_TWO_STARS = (
    "CREATE OR ALTER PROCEDURE silver.p AS BEGIN\n"
    "    SELECT * FROM bronze.a;\n"
    "    SELECT * FROM bronze.b;\n"
    "END\n"
)
_PROC_ONE_STAR = "CREATE OR ALTER PROCEDURE silver.p AS BEGIN\n    SELECT * FROM bronze.a;\nEND\n"


def _run(sql: str, path: str = "t.sql"):
    return run_rules([parse_sql(path, sql)], all_rules())


def _star_findings(result):
    return [f for f in result.findings if f.rule_id == "SQL-NO-SELECT-STAR"]


# --- the family construction, pinned exactly (mirrored in coop-dax-review) ----------


def test_family_identity_construction():
    # fingerprint = sha1("rule \x1f object-or-basename \x1f key-or-message \x1f ordinal")[:12].
    # Pinned byte-for-byte so the two tools can never drift apart silently again.
    f = Finding("SQL-A", "warning", "dir/f.sql", 10, "silver.p", "msg", "§1", occurrence=2)
    expected = hashlib.sha1("\x1f".join(["SQL-A", "silver.p", "msg", "2"]).encode("utf-8")).hexdigest()[:12]
    assert f.fingerprint() == expected
    # Empty object -> the file BASENAME stands in; fingerprint_key overrides the message.
    g = Finding("SQL-A", "warning", "dir/f.sql", 10, "", "msg 27 things", "§1", fingerprint_key="stable")
    expected = hashlib.sha1("\x1f".join(["SQL-A", "f.sql", "stable", "0"]).encode("utf-8")).hexdigest()[:12]
    assert g.fingerprint() == expected


def test_fingerprint_key_overrides_message():
    volatile = Finding("SQL-A", "warning", "f.sql", 1, "o", "msg with 27 items", "§1", fingerprint_key="core")
    grown = Finding("SQL-A", "warning", "f.sql", 1, "o", "msg with 28 items", "§1", fingerprint_key="core")
    assert volatile.fingerprint() == grown.fingerprint()  # message churn doesn't move identity
    keyless = Finding("SQL-A", "warning", "f.sql", 1, "o", "msg with 27 items", "§1")
    assert keyless.fingerprint() != volatile.fingerprint()  # empty key -> message IS the identity


def test_occurrence_participates_in_fingerprint():
    first = Finding("SQL-A", "warning", "f.sql", 1, "o", "msg", "§1", occurrence=0)
    second = Finding("SQL-A", "warning", "f.sql", 9, "o", "msg", "§1", occurrence=1)
    assert first.fingerprint() != second.fingerprint()


# --- occurrence ordinals: assignment + the ratchet fix -------------------------------


def test_two_occurrences_get_distinct_fingerprints():
    # issue #16: N occurrences in ONE object used to collapse to ONE fingerprint.
    stars = _star_findings(_run(_PROC_TWO_STARS))
    assert len(stars) == 2
    assert stars[0].object == stars[1].object == "silver.p"
    assert stars[0].message == stars[1].message  # constant-message rule...
    assert stars[0].fingerprint() != stars[1].fingerprint()  # ...but distinct identities
    assert [f.occurrence for f in stars] == [0, 1]


def test_first_occurrence_keeps_ordinal_zero():
    # A single-occurrence group is just ordinal 0 — adding a second occurrence BELOW
    # it must not move the first one's fingerprint (only new siblings get new ordinals).
    only = _star_findings(_run(_PROC_ONE_STAR))[0]
    first_of_two = _star_findings(_run(_PROC_TWO_STARS))[0]
    assert only.occurrence == first_of_two.occurrence == 0
    assert only.fingerprint() == first_of_two.fingerprint()


def test_new_occurrence_not_suppressed_by_prior_baseline(tmp_path):
    # THE ratchet hole (issue #16): baseline a proc with one SELECT *, later add a
    # second SELECT * to the same proc -> the new finding must surface, not vanish.
    f = tmp_path / "p.sql"
    f.write_text(_PROC_ONE_STAR, encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(f), "--write-baseline", str(bl)])
    f.write_text(_PROC_TWO_STARS, encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--baseline", str(bl), "--format", "json"]).output
    stars = [x for x in json.loads(out)["findings"] if x["rule_id"] == "SQL-NO-SELECT-STAR"]
    assert len(stars) == 1  # the pre-existing occurrence stays baselined...
    assert stars[0]["line"] == 3  # ...and the NEW one (the second star) is reported


def test_removing_earlier_occurrence_shifts_later_ordinals(tmp_path):
    # The documented trade-off (issue #16): ordinals number occurrences in the
    # deterministic sort order, so removing (or inserting) an EARLIER sibling shifts
    # the later ones — the shifted finding resurfaces and its baseline entry goes
    # stale LOUDLY. Line-shift stability inside a same-identity group is deliberately
    # traded for closing the ratchet hole.
    f = tmp_path / "p.sql"
    f.write_text(_PROC_TWO_STARS, encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(f), "--write-baseline", str(bl)])
    # remove the FIRST star; the survivor shifts from ordinal 1 to ordinal 0
    f.write_text(_PROC_ONE_STAR.replace("bronze.a", "bronze.b"), encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--baseline", str(bl)]).output
    assert "SQL-NO-SELECT-STAR" not in out  # ordinal 0 is in the baseline -> still suppressed
    assert "baseline:" in out and "no longer match" in out  # the ordinal-1 entry is stale, loudly


def test_unrelated_lines_above_do_not_change_fingerprints():
    # Identity stays line-free: inserting unrelated lines above every occurrence
    # must not move any fingerprint (only same-group insertions shift ordinals).
    plain = _star_findings(_run(_PROC_TWO_STARS))
    shifted = _star_findings(_run("-- header comment\n\n\n" + _PROC_TWO_STARS))
    assert [f.fingerprint() for f in plain] == [f.fingerprint() for f in shifted]
    assert [f.line for f in plain] != [f.line for f in shifted]  # lines DID move


def test_fingerprint_free_of_path():
    # Identity stays path-free: the same file seen from another cwd / machine yields
    # byte-identical fingerprints (baselines survive a directory or machine change).
    a = _star_findings(_run(_PROC_TWO_STARS, path="proj/sql/p.sql"))
    b = _star_findings(_run(_PROC_TWO_STARS, path="p.sql"))
    assert [f.fingerprint() for f in a] == [f.fingerprint() for f in b]


def test_agent_items_get_occurrence_ordinals_too():
    # The agent channel has the same collapse hole: two BEGIN TRAN in one file emit
    # object-less, constant-note items — the ordinal keeps them distinct.
    sql = "BEGIN TRAN;\nUPDATE t SET a = 1;\nCOMMIT;\nBEGIN TRAN;\nUPDATE t SET a = 2;\nCOMMIT;\n"
    result = _run(sql)
    txn = [a for a in result.agent_review if a.rule_id == "SQL-TXN-SHORT"]
    assert len(txn) == 2
    assert txn[0].note == txn[1].note
    assert txn[0].fingerprint() != txn[1].fingerprint()
    assert [a.occurrence for a in txn] == [0, 1]


def test_assign_occurrences_is_stable_and_group_scoped():
    # Ordinals count WITHIN one identity group; unrelated findings are untouched
    # (same list in -> same list out when ordinals already match, items reused).
    items = [
        Finding("SQL-A", "warning", "f.sql", 1, "o", "msg", "§1"),
        Finding("SQL-B", "warning", "f.sql", 2, "o", "msg", "§1"),  # different rule -> own group
        Finding("SQL-A", "warning", "f.sql", 3, "o", "msg", "§1"),
    ]
    stamped = assign_occurrences(items)
    assert [f.occurrence for f in stamped] == [0, 0, 1]
    assert stamped[0] is items[0]  # ordinal already correct -> the instance is reused
    again = assign_occurrences(stamped)
    assert again == stamped  # idempotent


def test_agent_item_family_identity_construction():
    # AgentReviewItem mirrors Finding exactly (note stands in for message).
    item = AgentReviewItem("SQL-X", "dir/m.sql", "", 5, "note", "§5", occurrence=1)
    expected = hashlib.sha1("\x1f".join(["SQL-X", "m.sql", "note", "1"]).encode("utf-8")).hexdigest()[:12]
    assert item.fingerprint() == expected
