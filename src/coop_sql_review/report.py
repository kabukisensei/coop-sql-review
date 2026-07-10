"""Render a :class:`Result` several ways: machine JSON (the agent contract), a
human console report, Markdown, and a self-contained HTML page — plus a
diagnostics log. All are deterministic (sorted, sort_keys + ensure_ascii on
JSON, LF newlines) so output is byte-identical across runs and operating
systems; HTML/Markdown are offline (inline CSS, no network) and HTML-escape
all dynamic text.

The tool-agnostic pieces — the ASCII console chrome, the branded HTML style +
logo, the JSON envelope/verdict, the diagnostics log, and the SARIF emitter —
live in ``coop_review_core.report`` (core 0.4.0, issues #9/#11); this module
renders THIS tool's ``Result`` through them and keeps everything tool-specific
(the finding/agent-review JSON shapes, the console/markdown/HTML layouts, and
the SARIF driver metadata).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from coop_review_core.report import (
    BADGE,
    BADGE_COLOR,
    HTML_STYLE,
    REPORT_WIDTH,
    SARIF_LEVEL,
    build_envelope,
    chip,
    diagnostic_json,
    envelope_text,
    esc,
    logo_data_uri,
    sty,
    verdict,
)
from coop_review_core.report import (
    log_text as _core_log_text,
)
from coop_review_core.report import (
    to_sarif as _core_to_sarif,
)

from coop_sql_review.engine import Result
from coop_sql_review.finding import SEVERITIES, severity_rank

# Findings-by-rule triage (issue #18): the report used to total only by severity,
# but the user's next step (rules.yml `enabled: false` / a severity override /
# `ignore:`) is per RULE — so the console/markdown/HTML reports also break the
# counts down by rule. When one rule dominates, a one-line hint points at the
# per-rule knobs (README section 7). JSON is unchanged (no schema bump).
_TRIAGE_HINT_THRESHOLD = 10  # a rule at/above this many findings triggers the hint
_TRIAGE_HINT = (
    "Tip: a noisy rule can be tuned or disabled in rules.yml "
    "(enabled / severity / ignore) - README section 7."
)


def rule_counts(result: Result) -> list[tuple[str, str, int]]:
    """``(rule_id, severity, count)`` for every rule with findings — sorted by
    count desc, then rule id, so the noisiest (most actionable) rule leads.
    The severity shown is the highest seen for that rule. Deterministic."""
    counts: dict[str, list] = {}
    for f in result.findings:
        entry = counts.setdefault(f.rule_id, [f.severity, 0])
        if severity_rank(f.severity) > severity_rank(entry[0]):
            entry[0] = f.severity
        entry[1] += 1
    return sorted(((rid, sev, n) for rid, (sev, n) in counts.items()), key=lambda t: (-t[2], t[0]))


# The terminal report's chrome (banner, badges, labels) stays ASCII so it is
# safe on a legacy Windows console (cp1252/cp437) and the no-color output is
# byte-stable; finding messages pass through as authored. Color is layered on
# only when the caller asks for it (an interactive terminal) — the chrome
# constants and `sty` come from coop_review_core.report.

# The agent JSON contract version. Bump on any breaking change to the shape so a
# consumer can pin/branch on it; additive fields don't require a bump.
# v2: fingerprints dropped the display path from their identity (rule_id, object,
# message/note only), so baselines and rules.yml ignore lists survive a cwd/machine
# change; baselines written under v1 must be regenerated once.
# v3: for a finding with an EMPTY object, the fingerprint now substitutes the file
# BASENAME for the object part, so object-less findings no longer collapse to one
# fingerprint across files (a baselined one could otherwise silently hide a new one
# elsewhere). Baselines/ignore lists holding object-less fingerprints regenerate once.
SCHEMA_VERSION = 3


def _verdict(result: Result) -> dict:
    """This tool's inputs to core's advisory :func:`coop_review_core.report.verdict`:
    the per-severity summary, whether findings remain, and whether an error-severity
    diagnostic (a genuine syntax error, a rule crash, an unreadable file) compromised
    coverage — which makes the run **not clean** even with zero findings."""
    return verdict(
        result.summary(),
        has_findings=bool(result.findings),
        has_error_diagnostic=any(d.severity == "error" for d in result.diagnostics),
    )


def _finding_json(f) -> dict:
    """One finding as the JSON dict the envelope (and the SARIF emitter) consume."""
    return {
        "rule_id": f.rule_id,
        "severity": f.severity,
        "file": f.file,
        "line": f.line,
        "object": f.object,
        "message": f.message,
        "standard_ref": f.standard_ref,
        "fingerprint": f.fingerprint(),  # stable, line- and path-independent identity
    }


def _agent_json(a) -> dict:
    """One agent-review item as the JSON dict the envelope (and SARIF) consume."""
    return {
        "rule_id": a.rule_id,
        "file": a.file,
        "object": a.object,
        "line": a.line,
        "note": a.note,
        "standard_ref": a.standard_ref,
        "fingerprint": a.fingerprint(),
    }


def to_json(result: Result, *, version: str, standards: dict[str, str]) -> dict:
    """The agent contract: stable keys, sorted, deterministic. The envelope shape
    is core's (:func:`coop_review_core.report.build_envelope`); the finding /
    agent-review dicts are this tool's."""
    return build_envelope(
        tool="coop-sql-review",
        schema_version=SCHEMA_VERSION,
        version=version,
        standards=standards,
        checked_key="files_checked",  # lets the agent tell "clean" from "nothing parsed"
        checked=result.files_checked,
        verdict=_verdict(result),
        findings=[_finding_json(f) for f in result.findings],
        summary=result.summary(),
        agent_review=[_agent_json(a) for a in result.agent_review],
        diagnostics=[diagnostic_json(d) for d in result.diagnostics],
    )


def json_text(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """JSON string with a trailing newline, sorted keys, LF line endings."""
    return envelope_text(to_json(result, version=version, standards=standards))


# --- SARIF 2.1.0 (GitHub code scanning / Azure DevOps PR annotations) ----------------
_SARIF_INFO_URI = "https://github.com/kabukisensei/coop-sql-review"
# The partialFingerprints KEY stays deliberately frozen at core's default
# ("coopFingerprint/v2"). GitHub code scanning matches alerts across runs by
# (key, value) pair; renaming the key to v3 would orphan every existing alert and
# re-open it as new. The VALUES are the current schema_version-3 identities
# (Finding/AgentReviewItem.fingerprint(): empty objects fall back to the file
# basename) — only the label stays put. Bump the key (core `to_sarif`'s
# ``fingerprint_key``) only if a future scheme changes identities so broadly that
# a clean alert reset is the better trade.


def to_sarif(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A deterministic single-run SARIF 2.1.0 log (string + trailing LF).

    Findings/agent-items/error-diagnostics become ``results`` with SARIF ``level``
    (error/warning/note), a physical location, and ``partialFingerprints`` (GitHub uses
    them to dedupe alerts across runs). Warning-severity diagnostics are advisory
    processing notes and are intentionally NOT emitted. No timestamps -> byte-stable.

    The emitter is core's (:func:`coop_review_core.report.to_sarif`); this tool
    supplies its driver metadata (the real rules — core appends the synthetic
    ``syntax-error`` diagnostics rule) and its pre-serialized findings.
    """
    from coop_sql_review.rules import all_rules  # lazy: avoid an import cycle

    driver_rules = [
        {
            "id": r.id,
            "name": r.id,
            "shortDescription": {"text": r.title},
            "defaultConfiguration": {"level": SARIF_LEVEL.get(r.severity, "note")},
            "properties": {
                "standard_ref": r.standard_ref,
                "tier": r.tier,
                "category": r.category,
                "targets": sorted(r.targets),
            },
        }
        for r in all_rules()
    ]
    return _core_to_sarif(
        tool_name="coop-sql-review",
        information_uri=_SARIF_INFO_URI,
        version=version,
        driver_rules=driver_rules,
        findings=[_finding_json(f) for f in result.findings],
        agent_review=[_agent_json(a) for a in result.agent_review],
        diagnostics=result.diagnostics,
        diagnostics_rule_description=(
            "A processing problem: a real T-SQL syntax error, a rule crash, or an unreadable file."
        ),
    )


def console_lines(
    result: Result,
    *,
    version: str = "",
    standards: dict[str, str] | None = None,
    color: bool = False,
) -> list[str]:
    """A report-style terminal summary: a banner, one section per file with
    severity-badged findings, then a summary panel. Deterministic with ASCII
    chrome; ``color`` only layers ANSI on top (opt-in, for an interactive
    terminal). Advisory wording throughout."""
    bar = "=" * REPORT_WIDTH
    indent = " " * 9  # aligns continuation lines under the rule id (3 + badge 5 + 1)
    lines: list[str] = []

    # ---- banner ----
    title, subtitle = "coop-sql-review", "SQL standards report"
    pad = max(2, REPORT_WIDTH - 2 - len(title) - len(subtitle))
    lines.append(sty(bar, "cyan", color=color))
    lines.append(
        "  " + sty(title, "bold", "cyan", color=color) + " " * pad + sty(subtitle, "dim", color=color)
    )
    lines.append(sty(bar, "cyan", color=color))
    meta = []
    if standards and standards.get("path"):
        meta.append(f"standards: {Path(standards['path']).name}")  # filename only; full path is in the JSON
    meta.append(f"files checked: {result.files_checked}")
    if version:
        meta.append(f"v{version}")
    lines.append("  " + sty("    ".join(meta), "dim", color=color))

    # ---- findings, grouped by file ----
    by_file: dict[str, list] = {}
    for finding in result.findings:
        by_file.setdefault(finding.file, []).append(finding)

    for file in sorted(by_file):
        lines.append("")
        lines.append("  " + sty(file, "bold", color=color))
        lines.append("  " + sty("-" * (REPORT_WIDTH - 2), "dim", color=color))
        for f in by_file[file]:
            badge = sty(
                BADGE.get(f.severity, "     "), BADGE_COLOR.get(f.severity, "blue"), "bold", color=color
            )
            head = f"   {badge} " + sty(f.rule_id, "bold", color=color) + f"  {f.standard_ref}"
            if f.object:
                head += f"   {f.object}"
            lines.append(head)
            lines.append(indent + sty(f"{f.file}:{f.line}", "dim", color=color))  # clickable in editors
            for wrapped in textwrap.wrap(f.message, REPORT_WIDTH - 9):
                lines.append(indent + wrapped)

    # ---- agent review (judgment required) — list what was flagged, not just a count ----
    if result.agent_review:
        lines.append("")
        lines.append("  " + sty("Agent review (judgment required)", "bold", color=color))
        lines.append("  " + sty("-" * (REPORT_WIDTH - 2), "dim", color=color))
        for a in result.agent_review:
            head = (
                "   "
                + sty("JUDGE", "cyan", "bold", color=color)
                + " "
                + sty(a.rule_id, "bold", color=color)
                + f"  {a.standard_ref}"
            )
            if a.object:
                head += f"   {a.object}"
            lines.append(head)
            # Same clickable location line findings get — without it, an object-less agent
            # item (e.g. SQL-TXN-SHORT) is literally unlocatable among the scanned files.
            loc = f"{a.file}:{a.line}" if a.line else a.file
            lines.append(indent + sty(loc, "dim", color=color))
            for wrapped in textwrap.wrap(a.note, REPORT_WIDTH - 9):
                lines.append(indent + wrapped)

    # ---- diagnostics (processing problems) — always shown; they explain gaps ----
    if result.diagnostics:
        lines.append("")
        lines.append(
            "  " + sty("Diagnostics (processing problems - analysis may be incomplete)", "bold", color=color)
        )
        lines.append("  " + sty("-" * (REPORT_WIDTH - 2), "dim", color=color))
        for diag in result.diagnostics:
            lines.append("   " + diag.as_line())

    # ---- summary panel ----
    summary = result.summary()
    total = sum(summary.values())
    lines.append("")
    lines.append(sty(bar, "cyan", color=color))
    if total == 0 and not result.diagnostics:
        lines.append("  " + sty("SUMMARY", "bold", color=color) + "    no issues found")
    else:
        segs = [
            sty(f"{summary[s]} {s}", BADGE_COLOR[s], "bold", color=color)
            if summary[s]
            else sty(f"{summary[s]} {s}", "dim", color=color)
            for s in SEVERITIES
        ]
        lines.append("  " + sty("SUMMARY", "bold", color=color) + "    " + "   ".join(segs))
        diag = result.diagnostic_summary()
        if result.agent_review:
            lines.append(
                " " * 13 + sty(f"{len(result.agent_review)} flagged for agent review", "dim", color=color)
            )
        if diag["error"] or diag["warning"]:
            bits = ", ".join(f"{diag[s]} {s}" for s in ("error", "warning") if diag[s])
            lines.append(" " * 13 + sty(f"diagnostics: {bits}", "dim", color=color))
        by_rule = rule_counts(result)
        if by_rule:
            lines.append("")
            lines.append("  " + sty("Findings by rule", "bold", color=color))
            width = len(str(by_rule[0][2]))  # first row carries the max count
            for rule_id, sev, count in by_rule:
                lines.append(
                    f"   {count:>{width}}  "
                    + sty(rule_id, "bold", color=color)
                    + "  "
                    + sty(f"[{sev}]", "dim", color=color)
                )
            if by_rule[0][2] >= _TRIAGE_HINT_THRESHOLD:
                lines.append("   " + sty(_TRIAGE_HINT, "dim", color=color))
    lines.append(sty(bar, "cyan", color=color))
    lines.append("  " + sty("Advisory only - nothing was changed or blocked.", "dim", color=color))
    return lines


def to_markdown(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A readable markdown report grouped by file — good for `--output report.md`.

    Deterministic (findings already sorted; LF newlines). Chrome is ASCII;
    rule messages pass through as-authored.
    """
    summary = result.summary()
    lines = [
        "# coop-sql-review report",
        "",
        f"- version: {version}",
        f"- standards: `{standards.get('path', '')}`",
        f"- files checked: {result.files_checked}",
        f"- findings: {summary['error']} error, {summary['warning']} warning, {summary['info']} info",
    ]
    diag = result.diagnostic_summary()
    if diag["error"] or diag["warning"]:
        lines.append(f"- diagnostics: {diag['error']} error, {diag['warning']} warning")
    if result.agent_review:
        lines.append(f"- agent review: {len(result.agent_review)} construct(s) need judgment")
    lines.append("")
    lines.append("_Advisory only - nothing was changed or blocked._")

    by_rule = rule_counts(result)
    if by_rule:
        lines.append("")
        lines.append("## Findings by rule")
        lines.append("")
        lines.append("| count | rule | severity |")
        lines.append("|---:|---|---|")
        for rule_id, sev, count in by_rule:
            lines.append(f"| {count} | `{rule_id}` | {sev} |")
        if by_rule[0][2] >= _TRIAGE_HINT_THRESHOLD:
            lines.append("")
            lines.append(f"_{_TRIAGE_HINT}_")

    by_file: dict[str, list] = {}
    for finding in result.findings:
        by_file.setdefault(finding.file, []).append(finding)
    if by_file:
        lines.append("")
        lines.append("## Findings")
        for file in sorted(by_file):
            lines.append("")
            lines.append(f"### `{file}`")
            lines.append("")
            for f in by_file[file]:
                lines.append(
                    f"- `{f.file}:{f.line}` **[{f.severity}]** {f.rule_id} ({f.standard_ref}): {f.message}"
                )

    if result.agent_review:
        lines.append("")
        lines.append("## Agent review (judgment required)")
        lines.append("")
        for a in result.agent_review:
            loc = f"{a.file}:{a.line}" if a.line else a.file
            lines.append(f"- `{loc}` {a.rule_id} ({a.standard_ref}) - {a.object}: {a.note}")

    if result.diagnostics:
        lines.append("")
        lines.append("## Diagnostics (processing problems)")
        lines.append("")
        for d in result.diagnostics:
            lines.append(f"- {d.as_line()}")
    lines.append("")
    return "\n".join(lines)


def to_html(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A self-contained, clean HTML report (inline CSS, no network).

    Deterministic and offline: findings are pre-sorted, no timestamps, all
    dynamic text is HTML-escaped. The brand chrome (``HTML_STYLE``, the base64
    logo, ``esc``/``chip``) is core's. Pair with ``--output report.html``.
    """
    summary = result.summary()
    logo = logo_data_uri()
    logo_img = f'<img src="{logo}" alt="Cooptimize">' if logo else ""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Cooptimize SQL Review</title>",
        f"<style>{HTML_STYLE}</style>",
        '</head><body><div class="wrap">',
        f'<header class="brand">{logo_img}<div>'
        "<h1>SQL Review</h1>"
        '<div class="sub">coop-sql-review &middot; Fabric DW standards report</div>'
        "</div></header>",
        '<div class="brandbar"></div>',
        f'<div class="meta">version {esc(version)} &middot; standards '
        f"<code>{esc(standards.get('path', ''))}</code> &middot; "
        f"{result.files_checked} file(s) checked</div>",
        '<div class="pills">'
        + "".join(f'<span class="pill {s}">{summary[s]} {s}</span>' for s in SEVERITIES if summary[s])
        + (
            f'<span class="pill">{len(result.agent_review)} agent review</span>'
            if result.agent_review
            else ""
        )
        + "</div>",
        '<div class="advisory">Advisory only - nothing was changed or blocked.</div>',
    ]

    by_rule = rule_counts(result)
    if by_rule:
        parts.append("<h2>Findings by rule</h2>")
        rows = "".join(
            f'<div class="f {esc(sev)}">{chip(sev)}'
            f'<div class="head"><span class="rule">{esc(rule_id)}</span> &middot; '
            f"{count} finding(s)</div></div>"
            for rule_id, sev, count in by_rule
        )
        parts.append(f'<div class="card">{rows}</div>')
        if by_rule[0][2] >= _TRIAGE_HINT_THRESHOLD:
            parts.append(f'<div class="advisory">{esc(_TRIAGE_HINT)}</div>')

    by_file: dict[str, list] = {}
    for finding in result.findings:
        by_file.setdefault(finding.file, []).append(finding)

    if by_file:
        for file in sorted(by_file):
            rows = "".join(
                f'<div class="f {esc(f.severity)}">{chip(f.severity)}'
                f'<div class="head"><span class="rule">{esc(f.rule_id)}</span> '
                f"({esc(f.standard_ref)}) &middot; {esc(f.file)}:{esc(f.line)}</div>"
                f'<div class="msg">{esc(f.message)}</div></div>'
                for f in by_file[file]
            )
            parts.append(f'<div class="card"><div class="file">{esc(file)}</div>{rows}</div>')
    else:
        parts.append('<div class="empty">No issues found.</div>')

    if result.agent_review:
        parts.append("<h2>Agent review (judgment required)</h2>")
        rows = "".join(
            f'<div class="f"><span class="chip info">agent</span>'
            f'<div class="head"><span class="rule">{esc(a.rule_id)}</span> '
            f"({esc(a.standard_ref)}) &middot; "
            f"{(esc(a.object) + ' &middot; ') if a.object else ''}"
            f"{esc(a.file)}{(':' + esc(a.line)) if a.line else ''}</div>"
            f'<div class="msg">{esc(a.note)}</div></div>'
            for a in result.agent_review
        )
        parts.append(f'<div class="card">{rows}</div>')

    if result.diagnostics:
        parts.append("<h2>Diagnostics (processing problems)</h2>")
        rows = "".join(
            f'<div class="f">{chip(d.severity)}'
            f'<div class="head"><span class="rule">{esc(d.category)}</span> &middot; '
            f"{esc(d.file)}{(':' + esc(d.line)) if d.line else ''}</div>"
            f'<div class="msg">{esc(d.message)}</div></div>'
            for d in result.diagnostics
        )
        parts.append(f'<div class="card">{rows}</div>')

    parts.append("</div></body></html>")
    return "\n".join(parts) + "\n"


def log_text(result: Result) -> str:
    """Full diagnostics log for ``--log-file``: every processing problem,
    one per line, deterministically ordered. Empty-safe."""
    return _core_log_text(
        result.diagnostics, tool="coop-sql-review", checked=result.files_checked, unit="file"
    )
