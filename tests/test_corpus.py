"""Corpus crash-guard: no rule may crash on realistic estate SQL.

``engine.run_rules`` isolates a crashing rule into a ``rule_error`` diagnostic
and the exit code stays 0 — so without this guard a rule-crash regression
(e.g. a sqlglot bump changing a node shape) would ship green and only surface
as per-run diagnostics on user machines.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from coop_sql_review.cli import cli
from coop_sql_review.diagnostics import RULE_ERROR
from coop_sql_review.engine import run_rules
from coop_sql_review.parser import parse_sql
from coop_sql_review.rules import all_rules

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _parse_corpus():
    files = sorted(FIXTURES.glob("*.sql"))
    assert files, "fixture corpus is missing"
    return [parse_sql(p.name, p.read_text(encoding="utf-8-sig")) for p in files]


def test_every_rule_survives_the_fixture_corpus():
    # ALL rules — including off-by-default ones the CLI wouldn't run.
    parsed = _parse_corpus()
    result = run_rules(parsed, all_rules())
    errors = [d for d in result.diagnostics if d.category == RULE_ERROR]
    assert errors == [], "\n".join(d.as_line() for d in errors)
    # The realistic fixture must actually exercise rules (guards against the
    # corpus silently degrading into something no rule can see inside).
    assert result.findings and result.agent_review


def test_check_over_the_corpus_reports_no_rule_errors():
    # Integration: the real CLI over the whole fixture directory.
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["files_checked"] >= 2
    assert [d for d in payload["diagnostics"] if d["category"] == RULE_ERROR] == []


def test_corpus_findings_are_deterministic():
    # Same corpus in -> byte-identical finding list out (sorted engine output).
    first = run_rules(_parse_corpus(), all_rules())
    second = run_rules(_parse_corpus(), all_rules())
    key = [(f.file, f.line, f.rule_id) for f in first.findings]
    assert key == [(f.file, f.line, f.rule_id) for f in second.findings]
