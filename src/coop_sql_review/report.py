"""Render a :class:`Result` two ways: machine JSON (the agent contract) and a
human console report. Both are deterministic — sorted, sort_keys on the JSON,
LF newlines — so output is byte-identical across runs and operating systems.
"""

from __future__ import annotations

import json

from coop_sql_review.engine import Result
from coop_sql_review.finding import SEVERITIES

# ASCII-only markers: a legacy Windows console (cp1252/cp437) raises
# UnicodeEncodeError on box/geometric glyphs, so keep console chrome ASCII.
_SYMBOL = {"error": "x", "warning": "!", "info": "-"}


def to_json(result: Result, *, version: str, standards: dict[str, str]) -> dict:
    """The agent contract: stable keys, sorted, deterministic."""
    return {
        "tool": "coop-sql-review",
        "version": version,
        "standards": {"path": standards.get("path", ""), "sha256": standards.get("sha256", "")},
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "file": f.file,
                "line": f.line,
                "object": f.object,
                "message": f.message,
                "standard_ref": f.standard_ref,
            }
            for f in result.findings
        ],
        "summary": result.summary(),
        "agent_review": [
            {
                "rule_id": a.rule_id,
                "file": a.file,
                "object": a.object,
                "line": a.line,
                "note": a.note,
                "standard_ref": a.standard_ref,
            }
            for a in result.agent_review
        ],
        "diagnostics": [
            {
                "severity": d.severity,
                "category": d.category,
                "file": d.file,
                "line": d.line,
                "message": d.message,
                "rule_id": d.rule_id,
            }
            for d in result.diagnostics
        ],
    }


def json_text(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """JSON string with a trailing newline, sorted keys, LF line endings."""
    return (
        json.dumps(
            to_json(result, version=version, standards=standards),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,  # pure-ASCII output: deterministic + safe on any Windows console
        )
        + "\n"
    )


def console_lines(result: Result) -> list[str]:
    """Human report grouped by file, then a summary. Advisory wording."""
    lines: list[str] = []
    by_file: dict[str, list] = {}
    for finding in result.findings:
        by_file.setdefault(finding.file, []).append(finding)

    for file in sorted(by_file):
        lines.append("")
        lines.append(file)
        for finding in by_file[file]:
            symbol = _SYMBOL.get(finding.severity, "-")
            lines.append(
                f"  {symbol} {finding.file}:{finding.line}  "
                f"[{finding.severity}] {finding.rule_id} ({finding.standard_ref})"
            )
            lines.append(f"      {finding.message}")

    # Diagnostics (processing problems) are always shown — they explain gaps
    # in coverage and surface rule errors so they can be fixed.
    if result.diagnostics:
        lines.append("")
        lines.append("Diagnostics (processing problems - analysis may be incomplete):")
        for diag in result.diagnostics:
            lines.append(f"  {diag.as_line()}")

    summary = result.summary()
    head = ", ".join(f"{summary[s]} {s}" for s in SEVERITIES if summary[s]) or "no issues"
    lines.append("")
    lines.append(f"Checked {result.files_checked} file(s): {head}.")
    diag = result.diagnostic_summary()
    if diag["error"] or diag["warning"]:
        bits = ", ".join(f"{diag[s]} {s}" for s in ("error", "warning") if diag[s])
        lines.append(f"Diagnostics: {bits} (see above; rule errors are bugs worth reporting).")
    if result.agent_review:
        lines.append(
            f"{len(result.agent_review)} construct(s) flagged for agent review "
            "(judgment required - see --format json)."
        )
    lines.append("Advisory only - nothing was changed or blocked.")
    return lines


def log_text(result: Result) -> str:
    """Full diagnostics log for ``--log-file``: every processing problem,
    one per line, deterministically ordered. Empty-safe."""
    header = f"coop-sql-review diagnostics log - {result.files_checked} file(s) checked"
    if not result.diagnostics:
        return header + "\nNo diagnostics.\n"
    body = "\n".join(diag.as_line() for diag in result.diagnostics)
    return f"{header}\n{body}\n"
