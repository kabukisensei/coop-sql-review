"""The Finding model — the unit every rule emits.

Severity is advisory; nothing the linter produces is fatal to a build
(unless the caller opts into ``--strict``). Findings sort deterministically
so the JSON contract and text report are byte-stable across runs and OSes.

**Family fingerprint identity (schema_version 4)** — identical construction in
coop-sql-review and coop-dax-review (which adds its ``model`` component):
``(rule_id, object-or-file-basename, fingerprint_key-or-message, occurrence)``.
The ``fingerprint_key`` lets a rule whose display message embeds volatile detail
(counts, name lists) expose a stable identity core instead; the ``occurrence``
ordinal discriminates N same-identity findings so a baseline written before a
NEW occurrence never silently suppresses it (the ratchet hole, issue #16).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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


def assign_occurrences(items: list) -> list:
    """Stamp each item's ``occurrence`` ordinal: within one identity-core group
    (:meth:`Finding.identity_parts` — the fingerprint components minus the ordinal),
    items are numbered 0, 1, 2, ... in list order. The caller passes the already
    deterministically SORTED list (the engine's sort: file, line, ...), so ordinals
    are byte-stable across runs/OSes. The first occurrence keeps ordinal 0.

    Deliberate trade-off (issue #16): a *new* occurrence inserted above an existing
    one shifts the later siblings' ordinals — those resurface (and their baseline
    entries go stale, loudly). Line-shift stability *within* a same-identity group
    is traded for closing the ratchet hole; unrelated edits (lines inserted above,
    file moves) still never change an identity."""
    counters: dict[tuple, int] = {}
    stamped = []
    for item in items:
        key = item.identity_parts()
        ordinal = counters.get(key, 0)
        counters[key] = ordinal + 1
        stamped.append(item if item.occurrence == ordinal else replace(item, occurrence=ordinal))
    return stamped


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
    # A rule whose display message embeds volatile detail (counts, name lists) sets a
    # stable identity core here; empty means the message IS the identity (the default).
    fingerprint_key: str = ""
    # Ordinal within this finding's identity-core group (0-based; engine-stamped after
    # the deterministic sort). Discriminates N same-identity occurrences (issue #16).
    occurrence: int = 0

    def sort_key(self) -> tuple:
        return (self.file, self.line, severity_rank(self.severity), self.rule_id, self.object, self.message)

    def identity_parts(self) -> tuple[str, str, str]:
        """The fingerprint's identity components, minus the occurrence ordinal:
        ``(rule_id, object-or-file-basename, fingerprint_key-or-message)``."""
        return (self.rule_id, _object_part(self.object, self.file), self.fingerprint_key or self.message)

    def fingerprint(self) -> str:
        """Stable, line- AND path-independent identity, so a consumer can track
        or suppress this finding across runs even as lines shift above it — and
        from any working directory or machine. The full ``file`` path deliberately
        does NOT participate; the identity is ``identity_parts()`` + the occurrence
        ordinal (schema_version 4 — the family rule shared with coop-dax-review).
        The ordinal means N occurrences of the same logical issue get N distinct
        fingerprints, so baselining today's occurrences never suppresses tomorrow's."""
        return _fingerprint(*self.identity_parts(), str(self.occurrence))


@dataclass(frozen=True)
class AgentReviewItem:
    """A construct the engine detects but cannot judge — handed to the agent."""

    rule_id: str
    file: str
    object: str
    line: int
    note: str
    standard_ref: str
    fingerprint_key: str = ""  # same contract as Finding.fingerprint_key (over the note)
    occurrence: int = 0  # same contract as Finding.occurrence

    def sort_key(self) -> tuple:
        return (self.file, self.rule_id, self.object, self.line, self.note)

    def identity_parts(self) -> tuple[str, str, str]:
        """See :meth:`Finding.identity_parts` — the note stands in for the message."""
        return (self.rule_id, _object_part(self.object, self.file), self.fingerprint_key or self.note)

    def fingerprint(self) -> str:
        """Stable, line- and path-independent identity (see
        :meth:`Finding.fingerprint`): ``identity_parts()`` + the occurrence ordinal,
        with the file basename standing in for an empty object so items don't
        collapse across files."""
        return _fingerprint(*self.identity_parts(), str(self.occurrence))
