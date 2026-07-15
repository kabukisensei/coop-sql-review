"""Rule registry via auto-discovery.

Every rule lives in its own ``sql_*.py`` module exporting a module-level
``RULE``. Discovery imports each such module and collects its ``RULE``, so a
new rule is added by dropping in a file — no shared registry to edit (which
keeps parallel rule authoring conflict-free). Rules are returned sorted by
id for deterministic ordering.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from coop_sql_review.rules.base import Rule, RuleContext

__all__ = ["Rule", "RuleContext", "all_rules", "rule_docs"]


def _discover():
    """Yield ``(rule, module)`` for every ``sql_*.py`` rule module."""
    for info in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        short = info.name.rsplit(".", 1)[1]
        if not short.startswith("sql_"):
            continue  # base/helpers are not rule modules
        module = importlib.import_module(info.name)
        rule = getattr(module, "RULE", None)
        if isinstance(rule, Rule):
            yield rule, module


def all_rules() -> list[Rule]:
    """Every discovered rule, sorted by id."""
    rules = [rule for rule, _ in _discover()]
    rules.sort(key=lambda r: r.id)
    return rules


def rule_docs() -> dict[str, str]:
    """Map each rule id to its module's docstring — the rule's rationale prose,
    consumed by ``coop-sql-review explain``."""
    return {rule.id: (inspect.getdoc(module) or "") for rule, module in _discover()}
