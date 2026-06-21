"""The Finding model — the unit every rule emits.

Severity is advisory; nothing the linter produces is fatal to a build
(unless the caller opts into ``--strict``). Findings sort deterministically
so the JSON contract and text report are byte-stable across runs and OSes.
"""

from __future__ import annotations

from dataclasses import dataclass

# Severity ordering + the line-independent fingerprint live in the shared core;
# re-exported here so the rule modules keep importing them from `finding`.
from coop_review_core.severity import (  # noqa: F401
    SEVERITIES,
    at_or_above,
    severity_rank,
)
from coop_review_core.severity import fingerprint as _fingerprint


@dataclass(frozen=True)
class Finding:
    """One flagged deviation from the standards, at a specific file + line."""

    rule_id: str
    severity: str
    file: str
    line: int
    object: str
    message: str
    standard_ref: str

    def sort_key(self) -> tuple:
        return (self.file, self.line, severity_rank(self.severity), self.rule_id, self.object, self.message)

    def fingerprint(self) -> str:
        """Stable, line-independent identity, so a consumer can track or suppress
        this finding across runs even as lines shift above it."""
        return _fingerprint(self.rule_id, self.file, self.object, self.message)


@dataclass(frozen=True)
class AgentReviewItem:
    """A construct the engine detects but cannot judge — handed to the agent."""

    rule_id: str
    file: str
    object: str
    line: int
    note: str
    standard_ref: str

    def sort_key(self) -> tuple:
        return (self.file, self.rule_id, self.object, self.line, self.note)

    def fingerprint(self) -> str:
        """Stable, line-independent identity (see :meth:`Finding.fingerprint`)."""
        return _fingerprint(self.rule_id, self.file, self.object, self.note)
