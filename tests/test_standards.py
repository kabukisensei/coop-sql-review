"""Standards resolution + rules.yml configuration."""

import hashlib

import pytest

from coop_sql_review.rules.base import Rule
from coop_sql_review.standards import (
    BUNDLED_STANDARDS,
    RuleConfig,
    StandardsError,
    apply_config,
    resolve_standards_path,
    standards_info,
)


def _rule(rule_id: str, severity: str = "warning") -> Rule:
    return Rule(id=rule_id, title="t", severity=severity, category="c", standard_ref="§1", tier=1)


def test_bundled_standards_exists_and_hashes():
    path = resolve_standards_path(None)
    assert path == BUNDLED_STANDARDS
    assert path.is_file()
    info = standards_info(path)
    assert info["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert info["path"].endswith("standards.md")


def test_missing_explicit_standards_raises():
    with pytest.raises(StandardsError):
        resolve_standards_path("/nope/does-not-exist.md")


def test_rule_config_disables_and_overrides(tmp_path):
    cfg_file = tmp_path / "rules.yml"
    cfg_file.write_text(
        "rules:\n  SQL-TYPE-MONEY:\n    enabled: false\n  SQL-NO-SELECT-STAR:\n    severity: error\n",
        encoding="utf-8",
    )
    config = RuleConfig.load(cfg_file)
    rules = [_rule("SQL-TYPE-MONEY"), _rule("SQL-NO-SELECT-STAR"), _rule("SQL-CTE-PREFIX", "info")]
    out = {r.id: r.severity for r in apply_config(rules, config)}
    assert "SQL-TYPE-MONEY" not in out  # disabled -> dropped
    assert out["SQL-NO-SELECT-STAR"] == "error"  # overridden
    assert out["SQL-CTE-PREFIX"] == "info"  # untouched


def test_empty_config_keeps_all():
    config = RuleConfig.load(None)
    rules = [_rule("A"), _rule("B")]
    assert len(apply_config(rules, config)) == 2


def _off_rule(rule_id: str) -> Rule:
    return Rule(
        id=rule_id,
        title="t",
        severity="info",
        category="c",
        standard_ref="§1",
        tier=1,
        default_enabled=False,
    )


def test_off_by_default_rule_excluded_then_opt_in():
    rules = [_off_rule("X-OFF"), _rule("X-ON")]
    assert {r.id for r in apply_config(rules, RuleConfig())} == {"X-ON"}
    opted_in = RuleConfig(enabled={"X-OFF"})
    assert {r.id for r in apply_config(rules, opted_in)} == {"X-OFF", "X-ON"}


def test_rules_yml_can_enable_an_off_by_default_rule(tmp_path):
    cfg_file = tmp_path / "rules.yml"
    cfg_file.write_text("rules:\n  SQL-TABLE-LAYER-NAME:\n    enabled: true\n", encoding="utf-8")
    config = RuleConfig.load(cfg_file)
    assert "SQL-TABLE-LAYER-NAME" in config.enabled


def test_shipped_noisy_rules_are_off_by_default():
    from coop_sql_review.rules import all_rules

    active = {r.id for r in apply_config(all_rules(), RuleConfig())}
    for off in (
        "SQL-HEADER-COMMENT",
        "SQL-TABLE-LAYER-NAME",
        "SQL-CTE-PREFIX",
        "SQL-ALIAS-DESCRIPTIVE",
        "SQL-INSERT-ALIAS-MATCH",
        "SQL-QUERY-LABEL",
    ):
        assert off not in active
    assert "SQL-NO-SELECT-STAR" in active  # a normal rule still runs
