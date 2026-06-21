"""The Finding model — the unit every rule emits.

Severity is advisory; nothing the linter produces is fatal to a build
(unless the caller opts into ``--strict``). Findings sort deterministically
so the JSON contract and text report are byte-stable across runs and OSes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

SEVERITIES = ("error", "warning", "info")
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def severity_rank(severity: str) -> int:
    """Order key for a severity; unknown severities sort last."""
    return _SEVERITY_RANK.get(severity, len(_SEVERITY_RANK))


def _fingerprint(*parts: str) -> str:
    """A short, stable hash over the identity parts (deliberately excludes the
    line number and severity, which shift with edits / config)."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


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
