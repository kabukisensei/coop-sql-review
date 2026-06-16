"""The Rule interface and the context handed to each rule.

A deterministic rule is a small dataclass plus a ``check(ctx) -> [Finding]``
function; an agent-judgment rule provides ``detect(ctx) -> [AgentReviewItem]``
instead (the engine routes those to the ``agent_review`` list rather than
evaluating them). ``RuleContext`` stamps the rule's id/severity/standard_ref
onto every Finding so rule modules stay terse and consistent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from coop_sql_review.finding import AgentReviewItem, Finding
from coop_sql_review.sql_model import ParsedFile


@dataclass
class Rule:
    """Metadata + the callable that evaluates one standard as a check."""

    id: str
    title: str
    severity: str  # default; a config or the standard may override
    category: str  # short topic, e.g. "naming", "datatypes", "joins"
    standard_ref: str  # section in standards.md, e.g. "§9"
    tier: int
    kind: str = "deterministic"  # "deterministic" | "agent"
    # Off-by-default rules still ship and can be turned on in rules.yml
    # (`enabled: true`); used for checks that are noisy on estates that don't
    # follow that particular convention (header blocks, medallion schema names).
    default_enabled: bool = True
    check: Optional[Callable[["RuleContext"], list[Finding]]] = None
    detect: Optional[Callable[["RuleContext"], list[AgentReviewItem]]] = None


class RuleContext:
    """What a rule's ``check``/``detect`` receives: the parsed file plus
    factory helpers that pre-fill the rule's identity onto each result."""

    def __init__(self, rule: Rule, parsed: ParsedFile) -> None:
        self.rule = rule
        self.parsed = parsed

    @property
    def file(self) -> str:
        return self.parsed.path

    def finding(self, *, line: int, object: str, message: str, severity: str | None = None) -> Finding:
        """Build a Finding stamped with this rule's id, severity, and ref."""
        return Finding(
            rule_id=self.rule.id,
            severity=severity or self.rule.severity,
            file=self.parsed.path,
            line=line,
            object=object,
            message=message,
            standard_ref=self.rule.standard_ref,
        )

    def review(self, *, object: str, line: int, note: str) -> AgentReviewItem:
        """Build an agent-review item stamped with this rule's id and ref."""
        return AgentReviewItem(
            rule_id=self.rule.id,
            file=self.parsed.path,
            object=object,
            line=line,
            note=note,
            standard_ref=self.rule.standard_ref,
        )
