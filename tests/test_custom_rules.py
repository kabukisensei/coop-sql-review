import pytest
from pathlib import Path
from coop_sql_review.rules.custom import build_custom_rules
from coop_sql_review.sql_model import ParsedFile
from coop_sql_review.rules.base import RuleContext
import click


def test_custom_rules():
    cfg = {
        "custom_rules": [
            {
                "id": "CUSTOM-NO-DBO",
                "pattern": r"\bdbo\.",
                "message": "Do not use dbo.",
                "severity": "error",
                "flags": ["ignorecase"],
            }
        ]
    }
    rules = build_custom_rules(cfg, Path("rules.yml"))
    assert len(rules) == 1
    r = rules[0]
    assert r.id == "CUSTOM-NO-DBO"
    assert r.severity == "error"
    assert r.category == "custom"

    parsed = ParsedFile(
        "test.sql", "SELECT * FROM dbo.table", "SELECT * FROM dbo.table", "tsql", _line_offsets=[0]
    )
    ctx = RuleContext(r, parsed)
    findings = r.check(ctx)
    assert len(findings) == 1
    assert findings[0].rule_id == "CUSTOM-NO-DBO"
    assert findings[0].message == "Do not use dbo."
    assert findings[0].line == 1


def test_custom_rules_invalid():
    with pytest.raises(click.UsageError, match="must start with 'CUSTOM-'"):
        build_custom_rules(
            {"custom_rules": [{"id": "NO-DBO", "pattern": "a", "message": "b"}]}, Path("rules.yml")
        )
