"""Engine: rule execution, error isolation, severity filtering, summary."""

from coop_sql_review.engine import run_rules
from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import Rule, RuleContext


def _emit_rule(severity: str) -> Rule:
    def check(ctx: RuleContext):
        return [ctx.finding(line=1, object="dbo.t", message=f"{severity} hit")]

    return Rule(
        id=f"TEST-{severity.upper()}",
        title="t",
        severity=severity,
        category="test",
        standard_ref="§0",
        tier=1,
        check=check,
    )


def _boom_rule() -> Rule:
    def check(ctx: RuleContext):
        raise ValueError("kaboom")

    return Rule(
        id="TEST-BOOM", title="t", severity="warning", category="test", standard_ref="§0", tier=1, check=check
    )


def _parse():
    return [parse_sql("a.sql", "SELECT 1;"), parse_sql("b.sql", "SELECT 2;")]


def test_runs_every_rule_over_every_file():
    result = run_rules(_parse(), [_emit_rule("warning")])
    assert len(result.findings) == 2  # one per file
    assert result.files_checked == 2


def test_buggy_rule_is_isolated_and_surfaced_as_diagnostic():
    result = run_rules(_parse(), [_emit_rule("info"), _boom_rule()])
    assert len(result.findings) == 2  # the good rule still produced findings
    rule_errors = [d for d in result.diagnostics if d.category == "rule_error"]
    assert {d.rule_id for d in rule_errors} == {"TEST-BOOM"}
    assert all(d.severity == "error" and "kaboom" in d.message for d in rule_errors)


def test_summary_and_severity_filter():
    result = run_rules(_parse(), [_emit_rule("error"), _emit_rule("warning"), _emit_rule("info")])
    assert result.summary() == {"error": 2, "warning": 2, "info": 2}
    warn_plus = result.filtered("warning")
    assert {f.severity for f in warn_plus.findings} == {"error", "warning"}
    assert warn_plus.summary() == {"error": 2, "warning": 2, "info": 0}


def test_findings_sorted_deterministically():
    result = run_rules(_parse(), [_emit_rule("warning")])
    keys = [(f.file, f.line, f.rule_id) for f in result.findings]
    assert keys == sorted(keys)


def test_find_all_is_cached_and_semantics_preserved():
    # issue #8: find_all() is backed by a per-file node index (one walk, then isinstance
    # filtering) so 20+ rules don't each re-walk the tree. Semantics must be identical:
    # same (batch, node) pairs, same document order, and stable across repeated calls.
    from sqlglot import exp

    parsed = parse_sql(
        "q.sql",
        "SELECT a, b FROM t WHERE a IN (SELECT x FROM u); SELECT * FROM v;",
    )
    # Reference: the old per-call walk.
    ref = [
        (batch, node)
        for batch in parsed.batches
        for expr in batch.expressions
        for node in expr.find_all(exp.Select)
    ]
    first = list(parsed.find_all(exp.Select))
    second = list(parsed.find_all(exp.Select))  # served from the cache the 2nd time
    assert [id(n) for _, n in first] == [id(n) for _, n in ref]  # identical nodes, same order
    assert [id(n) for _, n in second] == [id(n) for _, n in first]  # stable across calls
    assert parsed._nodes is not None  # the index was built and retained
    # Subclass matching still works (Query is the base of Select/Union).
    assert len(list(parsed.find_all(exp.Query))) >= len(first)
