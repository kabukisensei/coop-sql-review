import json
from pathlib import Path
import click
from coop_review_core.delta import diff_envelopes, delta_text, delta_markdown, DeltaError, EnvelopeDelta
from coop_review_core.report import HTML_STYLE
from coop_review_core.cliutils import write_extra_report
from coop_sql_review.progress import should_enable


def render_delta_html(delta: EnvelopeDelta) -> str:
    from html import escape

    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{escape(delta.tool)} Delta</title>",
        f"<style>{HTML_STYLE}</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(delta.tool)} Delta</h1>",
        f"<p><strong>{delta.new_count} new</strong>, <strong>{delta.fixed_count} fixed</strong>, {delta.persisting} unchanged.</p>",
    ]
    if delta.standards_changed:
        lines.append(
            "<p><strong>Standards changed</strong> - findings may differ because rules changed.</p>"
        )

    def render_finding(f: dict) -> str:
        loc = f.get("model") or f.get("file") or ""
        obj = f.get("object") or ""
        loc_str = f"{loc} :: {obj}" if loc and obj else (loc or obj)
        return f"<li><span class='severity-{f.get('severity', 'info')}'>[{escape(f.get('severity', 'info'))}]</span> <code>{escape(f.get('rule_id', ''))}</code> <code>{escape(loc_str)}</code> - {escape(f.get('message', ''))}</li>"

    if delta.new_findings:
        lines.append(f"<h2>New ({delta.new_count})</h2><ul>")
        lines.extend(render_finding(f) for f in delta.new_findings)
        lines.append("</ul>")

    if delta.fixed_findings:
        lines.append(f"<h2>Fixed ({delta.fixed_count})</h2><ul>")
        lines.extend(render_finding(f) for f in delta.fixed_findings)
        lines.append("</ul>")

    lines.append("<h2>Summary Delta</h2><ul>")
    for s, count in delta.summary_delta.items():
        sign = "+" if count >= 0 else ""
        lines.append(f"<li>{escape(s)}: {sign}{count}</li>")
    lines.append("</ul>")

    lines.extend(["</body>", "</html>"])
    return "\n".join(lines) + "\n"


def run_compare(
    old_path: str, new_path: str, md_path: str | None, html_path: str | None, color_flag: bool | None
) -> None:
    try:
        old_env = json.loads(Path(old_path).read_text(encoding="utf-8-sig"))
        new_env = json.loads(Path(new_path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise click.UsageError(f"cannot read JSON: {exc}") from exc
    except ValueError as exc:
        raise click.UsageError(f"invalid JSON: {exc}") from exc

    try:
        delta = diff_envelopes(old_env, new_env)
    except DeltaError as exc:
        raise click.UsageError(str(exc)) from exc

    use_color = should_enable(quiet=False) if color_flag is None else color_flag
    click.echo(delta_text(delta, color=use_color), err=False, nl=False)

    if md_path:
        write_extra_report(Path(md_path), delta_markdown(delta), "Markdown")
    if html_path:
        write_extra_report(Path(html_path), render_delta_html(delta), "HTML")
