"""Rule registry via auto-discovery.

Every rule lives in its own ``sql_*.py`` module exporting a module-level
``RULE``. Discovery imports each such module and collects its ``RULE``, so a
new rule is added by dropping in a file — no shared registry to edit (which
keeps parallel rule authoring conflict-free). Rules are returned sorted by
id for deterministic ordering.
"""

from __future__ import annotations

import importlib
import pkgutil

from coop_sql_review.rules.base import Rule, RuleContext

__all__ = ["Rule", "RuleContext", "all_rules"]


def all_rules() -> list[Rule]:
    """Every discovered rule, sorted by id."""
    rules: list[Rule] = []
    for info in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        short = info.name.rsplit(".", 1)[1]
        if not short.startswith("sql_"):
            continue  # base/helpers are not rule modules
        module = importlib.import_module(info.name)
        rule = getattr(module, "RULE", None)
        if isinstance(rule, Rule):
            rules.append(rule)
    rules.sort(key=lambda r: r.id)
    return rules
