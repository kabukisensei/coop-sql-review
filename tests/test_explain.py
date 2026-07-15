"""`coop-sql-review explain <RULE-ID>` (issue #38): rationale + standards excerpt."""

import json

import pytest
from click.testing import CliRunner

from coop_sql_review.cli import cli
from coop_sql_review.rules import all_rules
from coop_sql_review.standards import resolve_standards_path, section_text

RULE_IDS = [r.id for r in all_rules()]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_explain_every_rule_runs(rule_id):
    r = CliRunner().invoke(cli, ["explain", rule_id, "--no-color"])
    assert r.exit_code == 0, r.output
    assert rule_id in r.output
    assert "severity:" in r.output


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_explain_json_every_rule(rule_id):
    r = CliRunner().invoke(cli, ["explain", rule_id, "--format", "json"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["id"] == rule_id
    assert set(["rationale", "standards_excerpt", "severity", "targets", "tier"]) <= set(d)


def test_explain_is_case_insensitive():
    r = CliRunner().invoke(cli, ["explain", "sql-no-select-star", "--no-color"])
    assert r.exit_code == 0
    assert "SQL-NO-SELECT-STAR" in r.output


def test_explain_numeric_ref_shows_the_standards_excerpt():
    r = CliRunner().invoke(cli, ["explain", "SQL-NO-SELECT-STAR", "--no-color"])
    assert "Standard §11" in r.output  # SQL-NO-SELECT-STAR cites §11


def test_explain_unknown_id_is_a_usage_error_with_suggestion():
    r = CliRunner().invoke(cli, ["explain", "SQL-SELECT-STAR"])
    assert r.exit_code == 2
    assert "unknown rule id" in r.output
    assert "SQL-NO-SELECT-STAR" in r.output  # the close match is suggested


def test_section_text_slices_exactly_and_is_safe():
    std = resolve_standards_path(None)
    s1 = section_text(std, "§1")
    assert s1.startswith("## 1.")
    assert "\n## 2." not in s1  # stops before the next section heading
    # letter refs live in the un-bundled proposed-additions file; missing refs are safe
    assert section_text(std, "§A") == ""
    assert section_text(std, "§999") == ""
    assert section_text(std, "") == ""
