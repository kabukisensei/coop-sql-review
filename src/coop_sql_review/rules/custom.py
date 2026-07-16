import re
import click
from pathlib import Path
from typing import List

from coop_sql_review.rules.base import Rule


def build_custom_rules(cfg_data: dict, cfg_path: Path) -> List[Rule]:
    """Parse 'custom_rules' from the config mapping into Rule objects."""
    custom_rules = cfg_data.get("custom_rules", [])
    if not isinstance(custom_rules, list):
        raise click.UsageError(f"{cfg_path}: custom_rules must be a list")

    rules = []
    for item in custom_rules:
        if not isinstance(item, dict):
            raise click.UsageError(f"{cfg_path}: custom_rules entry must be a mapping")

        rule_id = item.get("id")
        pattern = item.get("pattern")
        message = item.get("message")

        if not rule_id or not str(rule_id).startswith("CUSTOM-"):
            raise click.UsageError(f"{cfg_path}: custom_rules id must start with 'CUSTOM-' (got {rule_id})")
        if not pattern:
            raise click.UsageError(f"{cfg_path}: custom_rule {rule_id} missing 'pattern'")
        if not message:
            raise click.UsageError(f"{cfg_path}: custom_rule {rule_id} missing 'message'")

        sev = str(item.get("severity", "warning")).lower()
        if sev not in ("error", "warning", "info"):
            raise click.UsageError(f"{cfg_path}: custom_rule {rule_id} has invalid severity '{sev}'")

        flags_list = item.get("flags", [])
        if not isinstance(flags_list, list):
            raise click.UsageError(f"{cfg_path}: custom_rule {rule_id} 'flags' must be a list")

        re_flags = 0
        for f in flags_list:
            if f.lower() == "ignorecase":
                re_flags |= re.IGNORECASE
            elif f.lower() == "multiline":
                re_flags |= re.MULTILINE
            else:
                raise click.UsageError(f"{cfg_path}: custom_rule {rule_id} flag '{f}' unknown")

        try:
            compiled = re.compile(pattern, re_flags)
        except re.error as e:
            raise click.UsageError(f"{cfg_path}: custom_rule {rule_id} invalid pattern: {e}")

        std_ref = str(item.get("standard_ref", "Custom Estate Rule"))

        def make_check(_pattern, _msg):
            def check(ctx):
                findings = []
                for match in _pattern.finditer(ctx.parsed.masked):
                    line = ctx.parsed.line_of_offset(match.start())
                    findings.append(ctx.finding(line=line, object="", message=_msg))
                return findings

            return check

        r = Rule(
            id=str(rule_id),
            title=f"Custom rule {rule_id}",
            category="custom",
            severity=sev,
            standard_ref=std_ref,
            tier=1,
            check=make_check(compiled, str(message)),
        )
        rules.append(r)

    return rules
