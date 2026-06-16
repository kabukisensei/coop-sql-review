"""The Finding model — the unit every rule emits.

Severity is advisory; nothing the linter produces is fatal to a build
(unless the caller opts into ``--strict``). Findings sort deterministically
so the JSON contract and text report are byte-stable across runs and OSes.
"""

from __future__ import annotations

from dataclasses import dataclass

SEVERITIES = ("error", "warning", "info")
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def severity_rank(severity: str) -> int:
    """Order key for a severity; unknown severities sort last."""
    return _SEVERITY_RANK.get(severity, len(_SEVERITY_RANK))


def at_or_above(severity: str, threshold: str) -> bool:
    """True when ``severity`` is as serious as ``threshold`` (error >= warning >= info)."""
    return severity_rank(severity) <= severity_rank(threshold)


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
