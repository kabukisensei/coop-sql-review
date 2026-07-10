"""Report renderers: JSON contract shape + determinism, console output."""

import json

from coop_sql_review.engine import Result
from coop_sql_review.finding import AgentReviewItem, Finding
from coop_sql_review.report import console_lines, json_text, to_html, to_json, to_sarif

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
    # v3: empty-object fingerprints substitute the file basename (still cwd-independent).
    assert payload["schema_version"] == 3
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


def test_console_summary_has_findings_by_rule_table():
    # issue #18: triage is per-rule (rules.yml enabled/severity/ignore), so the
    # SUMMARY carries per-rule counts — sorted by count desc, then rule id.
    lines = console_lines(_result())
    idx = next(i for i, ln in enumerate(lines) if "Findings by rule" in ln)
    table = "\n".join(lines[idx : idx + 3])
    # equal counts (1 each) -> rule-id order breaks the tie
    assert table.index("SQL-NO-SELECT-STAR") < table.index("SQL-TYPE-MONEY")
    assert "1  SQL-NO-SELECT-STAR  [warning]" in table


def test_console_by_rule_sorted_by_count_desc_and_hint_at_threshold():
    findings = [Finding("SQL-NOISY", "info", f"f{i}.sql", i + 1, "", "m", "sA") for i in range(10)] + [
        Finding("SQL-AAA-RARE", "warning", "g.sql", 1, "", "m", "sB")
    ]
    result = Result(findings=sorted(findings, key=lambda f: (f.file, f.line)), files_checked=11)
    text = "\n".join(console_lines(result))
    idx = text.index("Findings by rule")
    # count desc beats alphabetical: the 10x rule leads despite sorting after "SQL-AAA".
    assert text.index("SQL-NOISY", idx) < text.index("SQL-AAA-RARE", idx)
    assert "Tip: a noisy rule can be tuned or disabled in rules.yml" in text
    assert text.isascii()  # the new table + hint chrome stays ASCII (Windows consoles)


def test_console_no_hint_below_threshold_and_no_table_when_clean():
    assert "Tip: a noisy rule" not in "\n".join(console_lines(_result()))  # max count 1
    assert "Findings by rule" not in "\n".join(console_lines(Result(files_checked=1)))


def test_markdown_has_findings_by_rule_section():
    from coop_sql_review.report import to_markdown

    md = to_markdown(_result(), version="0.1.0", standards=STANDARDS)
    assert "## Findings by rule" in md
    assert "| 1 | `SQL-NO-SELECT-STAR` | warning |" in md
    # section is absent on a clean run
    clean = to_markdown(Result(files_checked=1), version="0.1.0", standards=STANDARDS)
    assert "## Findings by rule" not in clean


def test_html_has_findings_by_rule_section():
    html = to_html(_result(), version="0.1.0", standards=STANDARDS)
    assert "<h2>Findings by rule</h2>" in html
    assert "1 finding(s)" in html
    clean = to_html(Result(files_checked=1), version="0.1.0", standards=STANDARDS)
    assert "Findings by rule" not in clean


def test_console_lists_agent_review_items():
    text = "\n".join(console_lines(_result()))
    assert "Agent review (judgment required)" in text  # the section, not just a count
    assert "JUDGE" in text
    assert "SQL-UPSERT-CHOICE" in text  # the actual flagged rule is shown
    assert "gold/fact.sql:20" in text  # issue #6: the clickable location, so it's locatable


def test_console_agent_item_line_zero_shows_just_the_file():
    # A file-level agent item (line 0) prints only the file — never ":0".
    result = Result(
        findings=[],
        agent_review=[AgentReviewItem("SQL-TXN-SHORT", "silver/load.sql", "", 0, "explicit txn", "§9")],
        files_checked=1,
    )
    text = "\n".join(console_lines(result))
    assert "silver/load.sql" in text
    assert "silver/load.sql:0" not in text


def test_html_agent_row_includes_file_and_line():
    html = to_html(_result(), version="0.1.0", standards=STANDARDS)
    assert "gold/fact.sql:20" in html  # issue #6: agent row carries the location like findings do


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


def test_sarif_is_valid_2_1_0_and_maps_findings():
    import json as _json

    sarif = _json.loads(to_sarif(_result(), version="0.1.0", standards=STANDARDS))
    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif
    run = sarif["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "coop-sql-review" and driver["version"] == "0.1.0"
    rule_ids = {r["id"] for r in driver["rules"]}
    # Every result maps to a rule that exists in tool.driver.rules.
    for res in run["results"]:
        assert res["ruleId"] in rule_ids
    # The finding maps to a warning-level result at its line with its fingerprint.
    finding_res = next(r for r in run["results"] if r["ruleId"] == "SQL-TYPE-MONEY")
    assert finding_res["level"] == "warning"
    assert finding_res["locations"][0]["physicalLocation"]["region"]["startLine"] == 4
    assert finding_res["partialFingerprints"]["coopFingerprint/v2"] == _result().findings[0].fingerprint()
    # The agent-review item is a non-blocking note.
    agent_res = next(r for r in run["results"] if r["ruleId"] == "SQL-UPSERT-CHOICE")
    assert agent_res["level"] == "note"


def test_sarif_severity_mapping():
    from coop_sql_review.engine import Result

    result = Result(
        findings=[
            Finding("SQL-A", "error", "a.sql", 1, "o", "m", "§1"),
            Finding("SQL-B", "warning", "a.sql", 2, "o", "m", "§1"),
            Finding("SQL-C", "info", "a.sql", 3, "o", "m", "§1"),
        ],
        files_checked=1,
    )
    import json as _json

    levels = {
        r["ruleId"]: r["level"]
        for r in _json.loads(to_sarif(result, version="0", standards=STANDARDS))["runs"][0]["results"]
    }
    assert levels == {"SQL-A": "error", "SQL-B": "warning", "SQL-C": "note"}  # info -> note


def test_sarif_omits_region_for_line_zero():
    from coop_sql_review.engine import Result

    result = Result(
        findings=[Finding("SQL-X", "warning", "a.sql", 0, "", "file-level", "§1")], files_checked=1
    )
    import json as _json

    loc = _json.loads(to_sarif(result, version="0", standards=STANDARDS))["runs"][0]["results"][0][
        "locations"
    ][0]
    assert "region" not in loc["physicalLocation"]  # no line -> no region
    assert loc["physicalLocation"]["artifactLocation"]["uri"] == "a.sql"


def test_sarif_is_deterministic():
    a = to_sarif(_result(), version="0.1.0", standards=STANDARDS)
    b = to_sarif(_result(), version="0.1.0", standards=STANDARDS)
    assert a == b and a.endswith("\n")
