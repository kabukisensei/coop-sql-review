"""The Finding model — the unit every rule emits.

Severity is advisory; nothing the linter produces is fatal to a build
(unless the caller opts into ``--strict``). Findings sort deterministically
so the JSON contract and text report are byte-stable across runs and OSes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

# Severity ordering + the line-independent fingerprint live in the shared core;
# re-exported here so the rule modules keep importing them from `finding`.
from coop_review_core.severity import (  # noqa: F401
    SEVERITIES,
    at_or_above,
    severity_rank,
)
from coop_review_core.severity import fingerprint as _fingerprint


def _object_part(obj: str, file: str) -> str:
    """The ``object`` component of a fingerprint. When a finding has no object — rules
    that always emit ``object=""`` with a constant message, or ``enclosing_object()`` on a
    bare script — fall back to the file's BASENAME so two different files don't collapse to
    ONE fingerprint (issue #3): a baselined object-less finding would otherwise silently
    hide a brand-new one elsewhere. The basename is still cwd/machine-independent (the v2
    goal was surviving a directory/machine change — basenames do), so identities remain
    stable across working directories."""
    return obj or PurePosixPath(file).name


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
        """Stable, line- AND path-independent identity, so a consumer can track
        or suppress this finding across runs even as lines shift above it — and
        from any working directory or machine. The full ``file`` path deliberately
        does NOT participate; the identity is (rule_id, object, message). Two files
        carrying the same qualified object + message collide by design — they are the
        same logical issue. When ``object`` is empty, the file BASENAME stands in for it
        (see :func:`_object_part`) so object-less findings don't collapse across files."""
        return _fingerprint(self.rule_id, _object_part(self.object, self.file), self.message)


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
        """Stable, line- and path-independent identity (see
        :meth:`Finding.fingerprint`): (rule_id, object, note), with the file basename
        standing in for an empty object so items don't collapse across files."""
        return _fingerprint(self.rule_id, _object_part(self.object, self.file), self.note)
