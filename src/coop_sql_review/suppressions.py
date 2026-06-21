"""Suppressions: inline ``coop-sql-review:ignore`` directives + a fingerprint baseline.

Both let this advisory linter be adopted on existing code without drowning in
already-known findings — and both stay deterministic and never block:

- **inline**: a comment ``coop-sql-review:ignore SQL-NO-SELECT-STAR`` on a finding's
  line (or the line directly above it) silences that rule there. List several ids
  (``ignore SQL-A, SQL-B``) or none / ``*`` to silence all rules on that line; a
  trailing ``reason: ...`` is ignored by the parser but documents the waiver.
- **baseline**: a JSON file of finding fingerprints; findings already in it are
  hidden so only *new* findings surface (a ratchet). Written by ``--write-baseline``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TOOL = "coop-sql-review"

# `<tool>:ignore` followed by optional rule ids, up to a reason/comment delimiter.
_DIRECTIVE_RE = re.compile(rf"{re.escape(TOOL)}\s*:\s*ignore\b([^\n]*)", re.IGNORECASE)
_RULE_ID_RE = re.compile(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+")


def scan_directives(text: str) -> dict[int, set[str]]:
    """Map each 1-based line carrying an ignore directive to the rule ids it silences.

    A directive with no explicit rule id (or a bare ``*``) silences every rule on
    its target line.
    """
    out: dict[int, set[str]] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _DIRECTIVE_RE.search(line)
        if not match:
            continue
        # Stop at a reason/comment delimiter so a reason mentioning a RULE-LIKE token
        # isn't captured as a rule id.
        head = re.split(r"\breason\b|--|//|#", match.group(1), maxsplit=1)[0]
        ids = set(_RULE_ID_RE.findall(head))
        out[lineno] = ids or {"*"}
    return out


def is_inline_suppressed(rule_id: str, line: int, directives: dict[int, set[str]]) -> bool:
    """True if a directive on this line (or the line directly above) covers the rule."""
    if not line:  # file-level findings (line 0) can't be inline-targeted
        return False
    for d_line in (line, line - 1):
        ids = directives.get(d_line)
        if ids and ("*" in ids or rule_id in ids):
            return True
    return False


def baseline_payload(fingerprints) -> dict:
    """Deterministic baseline content: sorted, de-duplicated fingerprints + a header."""
    return {"tool": TOOL, "fingerprints": sorted(set(fingerprints))}


def write_baseline(path: Path, fingerprints) -> int:
    """Write a baseline file; returns how many fingerprints it recorded."""
    payload = baseline_payload(fingerprints)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return len(payload["fingerprints"])


def load_baseline(path: Path) -> set[str]:
    """The fingerprints recorded in a baseline file (empty if absent/unreadable/malformed)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(data, dict):
        return {str(fp) for fp in data.get("fingerprints", [])}
    if isinstance(data, list):
        return {str(fp) for fp in data}
    return set()
