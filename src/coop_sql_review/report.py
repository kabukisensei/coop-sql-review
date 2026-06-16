"""Render a :class:`Result` several ways: machine JSON (the agent contract), a
human console report, Markdown, and a self-contained HTML page — plus a
diagnostics log. All are deterministic (sorted, sort_keys + ensure_ascii on
JSON, LF newlines) so output is byte-identical across runs and operating
systems; HTML/Markdown are offline (inline CSS, no network) and HTML-escape
all dynamic text.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

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


# Cooptimize brand palette (sampled from the integrated logo): navy #004068,
# accent red-orange #e84028, green gradient #407838 / #80a840 / #b0d030.
_HTML_STYLE = """
:root {
  --bg: #f6f8f9; --card: #ffffff; --ink: #14202b; --muted: #5c6b73; --line: #e4e8ea;
  --brand: #004068; --accent: #e84028;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --error: #c23b22; --error-bg: #fdece8; --warning: #8a5a00; --warning-bg: #fff5dd;
  --info: #3a5a72; --info-bg: #e9eef2;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5; }
.wrap { max-width: 960px; margin: 0 auto; padding: 28px 20px 64px; }
header.brand { display: flex; align-items: center; gap: 14px; }
header.brand img { height: 46px; width: auto; }
header.brand h1 { font-size: 1.4rem; margin: 0; letter-spacing: -0.01em; color: var(--brand); }
header.brand .sub { color: var(--muted); font-size: 0.85rem; }
.brandbar { height: 4px; border-radius: 4px; margin: 14px 0 18px;
  background: linear-gradient(90deg, #004068, #407838, #80a840, #b0d030); }
.meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 14px; }
.meta code { font-family: var(--mono); }
.pills { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 8px; }
.pill { font-size: 0.8rem; font-weight: 600; padding: 4px 10px; border-radius: 999px;
  border: 1px solid var(--line); background: var(--card); }
.pill.error { color: var(--error); background: var(--error-bg); border-color: transparent; }
.pill.warning { color: var(--warning); background: var(--warning-bg); border-color: transparent; }
.pill.info { color: var(--info); background: var(--info-bg); border-color: transparent; }
.advisory { color: var(--muted); font-size: 0.85rem; margin: 4px 0 24px; }
h2 { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brand);
  margin: 32px 0 12px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  margin-bottom: 14px; overflow: hidden; box-shadow: 0 1px 2px rgba(20,32,43,0.04); }
.file { font-family: var(--mono); font-size: 0.85rem; font-weight: 600; padding: 12px 16px;
  border-bottom: 1px solid var(--line); background: #fbfcfd; color: var(--brand);
  word-break: break-all; }
.f { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; padding: 12px 16px;
  border-bottom: 1px solid var(--line); }
.f:last-child { border-bottom: 0; }
.f.error { box-shadow: inset 3px 0 0 var(--accent); }
.chip { align-self: start; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.03em; padding: 3px 8px; border-radius: 6px; white-space: nowrap; }
.chip.error { color: var(--error); background: var(--error-bg); }
.chip.warning { color: var(--warning); background: var(--warning-bg); }
.chip.info { color: var(--info); background: var(--info-bg); }
.head { font-size: 0.8rem; color: var(--muted); font-family: var(--mono); }
.head .rule { color: var(--ink); font-weight: 600; }
.msg { grid-column: 2; }
.empty { color: var(--muted); padding: 24px; text-align: center; background: var(--card);
  border: 1px solid var(--line); border-radius: 12px; }
""".strip()

_LOGO_PATH = Path(__file__).resolve().parent / "data" / "cooptimize-logo.png"


def _logo_data_uri() -> str:
    """The bundled Cooptimize logo as a base64 data URI, so the HTML stays
    self-contained (no external image). Empty string if the asset is missing."""
    try:
        raw = _LOGO_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _chip(severity: str) -> str:
    sev = severity if severity in SEVERITIES else "info"
    return f'<span class="chip {sev}">{_esc(severity)}</span>'


def to_html(result: Result, *, version: str, standards: dict[str, str]) -> str:
    """A self-contained, clean HTML report (inline CSS, no network).

    Deterministic and offline: findings are pre-sorted, no timestamps, all
    dynamic text is HTML-escaped. Pair with ``--output report.html``.
    """
    summary = result.summary()
    logo = _logo_data_uri()
    logo_img = f'<img src="{logo}" alt="Cooptimize">' if logo else ""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Cooptimize SQL Review</title>",
        f"<style>{_HTML_STYLE}</style>",
        '</head><body><div class="wrap">',
        f'<header class="brand">{logo_img}<div>'
        "<h1>SQL Review</h1>"
        '<div class="sub">coop-sql-review &middot; Fabric DW standards report</div>'
        "</div></header>",
        '<div class="brandbar"></div>',
        f'<div class="meta">version {_esc(version)} &middot; standards '
        f"<code>{_esc(standards.get('path', ''))}</code> &middot; "
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

    by_file: dict[str, list] = {}
    for finding in result.findings:
        by_file.setdefault(finding.file, []).append(finding)

    if by_file:
        for file in sorted(by_file):
            rows = "".join(
                f'<div class="f {_esc(f.severity)}">{_chip(f.severity)}'
                f'<div class="head"><span class="rule">{_esc(f.rule_id)}</span> '
                f"({_esc(f.standard_ref)}) &middot; {_esc(f.file)}:{_esc(f.line)}</div>"
                f'<div class="msg">{_esc(f.message)}</div></div>'
                for f in by_file[file]
            )
            parts.append(f'<div class="card"><div class="file">{_esc(file)}</div>{rows}</div>')
    else:
        parts.append('<div class="empty">No issues found.</div>')

    if result.agent_review:
        parts.append("<h2>Agent review (judgment required)</h2>")
        rows = "".join(
            f'<div class="f"><span class="chip info">agent</span>'
            f'<div class="head"><span class="rule">{_esc(a.rule_id)}</span> '
            f"({_esc(a.standard_ref)}) &middot; {_esc(a.object)}</div>"
            f'<div class="msg">{_esc(a.note)}</div></div>'
            for a in result.agent_review
        )
        parts.append(f'<div class="card">{rows}</div>')

    if result.diagnostics:
        parts.append("<h2>Diagnostics (processing problems)</h2>")
        rows = "".join(
            f'<div class="f">{_chip(d.severity)}'
            f'<div class="head"><span class="rule">{_esc(d.category)}</span> &middot; '
            f"{_esc(d.file)}{(':' + _esc(d.line)) if d.line else ''}</div>"
            f'<div class="msg">{_esc(d.message)}</div></div>'
            for d in result.diagnostics
        )
        parts.append(f'<div class="card">{rows}</div>')

    parts.append("</div></body></html>")
    return "\n".join(parts) + "\n"


def log_text(result: Result) -> str:
    """Full diagnostics log for ``--log-file``: every processing problem,
    one per line, deterministically ordered. Empty-safe."""
    header = f"coop-sql-review diagnostics log - {result.files_checked} file(s) checked"
    if not result.diagnostics:
        return header + "\nNo diagnostics.\n"
    body = "\n".join(diag.as_line() for diag in result.diagnostics)
    return f"{header}\n{body}\n"
