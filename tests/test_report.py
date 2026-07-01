"""Report renderers: JSON contract shape + determinism, console output."""

import json

from coop_sql_review.engine import Result
from coop_sql_review.finding import AgentReviewItem, Finding
from coop_sql_review.report import console_lines, json_text, to_html, to_json

STANDARDS = {"path": "docs/standards.md", "sha256": "abc123"}


def _result() -> Result:
    # findings already in engine-sorted order (by file, then line)
    return Result(
        findings=[
            Finding("SQL-TYPE-MONEY", "warning", "gold/fact.sql", 4, "gold.fact", "money", "§9"),
            Finding("SQL-NO-SELECT-STAR", "warning", "silver/dim.sql", 12, "silver.dim", "SELECT *", "§11"),
        ],
        agent_review=[
            AgentReviewItem("SQL-UPSERT-CHOICE", "gold/fact.sql", "gold.fact", 20, "MERGE seen", "§5")
        ],
        files_checked=2,
    )


def test_json_contract_keys():
    payload = to_json(_result(), version="0.1.0", standards=STANDARDS)
    assert payload["tool"] == "coop-sql-review"
    assert payload["version"] == "0.1.0"
    assert payload["standards"] == {"path": "docs/standards.md", "sha256": "abc123"}
    assert payload["summary"] == {"error": 0, "warning": 2, "info": 0}
    # v2: fingerprints dropped the display path from their identity (cwd-independent).
    assert payload["schema_version"] == 2
    assert set(payload["verdict"]) == {"clean", "highest_severity"}
    first = payload["findings"][0]
    assert set(first) == {
        "rule_id",
        "severity",
        "file",
        "line",
        "object",
        "message",
        "standard_ref",
        "fingerprint",
    }
    review = payload["agent_review"][0]
    assert set(review) == {"rule_id", "file", "object", "line", "note", "standard_ref", "fingerprint"}


def test_json_text_is_deterministic_and_sorted():
    a = json_text(_result(), version="0.1.0", standards=STANDARDS)
    b = json_text(_result(), version="0.1.0", standards=STANDARDS)
    assert a == b
    assert a.endswith("\n")
    parsed = json.loads(a)
    # findings ordered by (file, line) deterministically
    locs = [(f["file"], f["line"]) for f in parsed["findings"]]
    assert locs == sorted(locs)


def test_console_mentions_advisory_and_counts():
    lines = "\n".join(console_lines(_result()))
    assert "2 warning" in lines
    assert "Advisory only" in lines
    assert "agent review" in lines


def test_console_lists_agent_review_items():
    text = "\n".join(console_lines(_result()))
    assert "Agent review (judgment required)" in text  # the section, not just a count
    assert "JUDGE" in text
    assert "SQL-UPSERT-CHOICE" in text  # the actual flagged rule is shown


def test_console_is_report_styled_and_plain_by_default():
    text = "\n".join(console_lines(_result(), version="0.1.4", standards=STANDARDS))
    assert "coop-sql-review" in text  # banner
    assert "SQL standards report" in text
    assert "===" in text  # banner / summary rules
    assert "SUMMARY" in text
    assert "Advisory only" in text
    assert "\033[" not in text  # no ANSI unless color is requested


def test_console_color_adds_ansi_only_when_requested():
    assert "\033[" in "\n".join(console_lines(_result(), color=True))
    assert "\033[" not in "\n".join(console_lines(_result(), color=False))


def test_console_chrome_is_ascii_safe_even_colored():
    # An empty result is pure chrome; it stays ASCII even colored (ANSI is ASCII).
    assert "\n".join(console_lines(Result(files_checked=1))).isascii()
    assert "\n".join(console_lines(Result(files_checked=1), color=True)).isascii()
    assert "no issues found" in "\n".join(console_lines(Result(files_checked=1)))


def test_html_is_self_contained_and_escapes():
    result = Result(
        findings=[Finding("R", "warning", "f.sql", 1, "o", "x < y & z > w", "§9")],
        files_checked=1,
    )
    out = to_html(result, version="0.1.1", standards={"path": "p", "sha256": "s"})
    assert out.startswith("<!DOCTYPE html>")
    assert "<style>" in out  # inline CSS, no external/CDN assets
    assert "http://" not in out and "https://" not in out  # offline / self-contained
    # dynamic content is HTML-escaped (no raw <, >, & from the message)
    assert "x &lt; y &amp; z &gt; w" in out
    assert "x < y & z > w" not in out
    # branded: the Cooptimize logo is embedded inline as a data URI
    assert "data:image/png;base64," in out
    assert "SQL Review" in out
