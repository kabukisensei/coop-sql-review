"""Command-line interface.

Thin wrapper over the pipeline (discover -> parse -> run rules -> render).
Advisory by default: exit code 0 no matter what is found. ``--strict`` is the
opt-in CI gate — exit 2 when any reported finding remains after the
``--min-severity`` filter.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from coop_sql_review import __version__
from coop_sql_review.diagnostics import FILE_UNREADABLE, Diagnostic
from coop_sql_review.engine import run_rules
from coop_sql_review.finding import SEVERITIES
from coop_sql_review.parser import parse_sql
from coop_sql_review.progress import Progress, should_enable
from coop_sql_review.report import console_lines, json_text, log_text, to_html, to_markdown
from coop_sql_review.rules import all_rules
from coop_sql_review.sql_model import ParsedFile
from coop_sql_review.standards import (
    RuleConfig,
    StandardsError,
    apply_config,
    default_config_path,
    resolve_standards_path,
    standards_info,
)

_SEVERITY_CHOICE = click.Choice(SEVERITIES)


def _display_path(path: Path) -> str:
    """POSIX-style path, relative to cwd when possible (deterministic, OS-stable)."""
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def discover_sql_files(paths: tuple[str, ...]) -> list[Path]:
    """Expand the given paths into a sorted list of ``.sql`` files.

    Files are taken as-is; directories are searched recursively, skipping
    hidden directories. Defaults to the current directory when none given.
    """
    roots = [Path(p) for p in paths] or [Path(".")]
    found: set[Path] = set()
    for root in roots:
        if root.is_file():
            found.add(root)
        elif root.is_dir():
            for candidate in root.rglob("*.sql"):
                rel = candidate.relative_to(root)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if candidate.is_file():
                    found.add(candidate)
    return sorted(found, key=lambda p: _display_path(p))


def _parse_files(files: list[Path], dialect: str, on_file=None) -> tuple[list[ParsedFile], list[Diagnostic]]:
    """Parse each file; an unreadable file becomes a diagnostic, not a crash.

    ``on_file`` (optional) is ticked once per file for progress reporting.
    """
    parsed: list[ParsedFile] = []
    read_diagnostics: list[Diagnostic] = []
    for path in files:
        if on_file:
            on_file(path)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            read_diagnostics.append(
                Diagnostic(
                    severity="error",
                    category=FILE_UNREADABLE,
                    file=_display_path(path),
                    line=0,
                    message=f"could not read file: {exc}",
                )
            )
            continue
        parsed.append(parse_sql(_display_path(path), text, dialect=dialect))
    return parsed, read_diagnostics


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="coop-sql-review")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Offline, advisory SQL standards linter for Microsoft Fabric DW.

    Reports deviations from the SQL standards; never edits or blocks.
    Processing problems (parse failures, rule errors) are reported as
    diagnostics in every run; use ``check --log-file`` to capture them.
    """
    ctx.ensure_object(dict)
    # sqlglot logs a warning for every statement it falls back to a Command on;
    # we already surface that as a controlled parse_degraded diagnostic, so keep
    # its noise out of the report (stderr).
    logging.getLogger("sqlglot").setLevel(logging.ERROR)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("paths", nargs=-1, type=click.Path())
@click.option(
    "--standards", "standards_path", default=None, help="Path to the standards file (default: bundled)."
)
@click.option(
    "--config", "config_path", default=None, help="Path to a rules.yml (default: alongside standards)."
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "markdown", "html"]),
    default="text",
    show_default=True,
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Write the report to this file instead of the screen (easier to read for big runs).",
)
@click.option(
    "--min-severity",
    type=_SEVERITY_CHOICE,
    default="info",
    show_default=True,
    help="Hide findings below this severity.",
)
@click.option("--dialect", default="tsql", show_default=True, help="sqlglot dialect to parse with.")
@click.option(
    "--log-file",
    "log_file",
    type=click.Path(),
    default=None,
    help="Write a diagnostics log (parse problems, rule errors) to this file.",
)
@click.option("--strict", is_flag=True, help="Exit 2 if any reported finding remains (opt-in CI gate).")
@click.pass_context
def check(
    ctx: click.Context,
    paths: tuple[str, ...],
    standards_path: str | None,
    config_path: str | None,
    fmt: str,
    output_path: str | None,
    min_severity: str,
    dialect: str,
    log_file: str | None,
    strict: bool,
) -> None:
    """Check SQL files (or directories) against the standards."""
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    config = RuleConfig.load(Path(config_path) if config_path else default_config_path(std_path))
    rules = apply_config(all_rules(), config)

    files = discover_sql_files(paths)
    if not files:
        click.echo("No .sql files found.", err=True)
        return

    # Progress is stderr-only + TTY-gated, so it never pollutes the report
    # (stdout) or a redirected --output file.
    progress = Progress(should_enable(quiet=False))
    progress.line(f"Checking {len(files)} SQL file(s)...")
    with progress.bar("Parsing", total=len(files)) as tick:
        parsed, read_diagnostics = _parse_files(files, dialect, on_file=tick)
    result = run_rules(parsed, rules)
    result.diagnostics.extend(read_diagnostics)
    result.diagnostics.sort(key=lambda d: d.sort_key())
    result = result.filtered(min_severity)

    standards = standards_info(std_path)
    if fmt == "json":
        rendered = json_text(result, version=__version__, standards=standards)
    elif fmt == "markdown":
        rendered = to_markdown(result, version=__version__, standards=standards) + "\n"
    elif fmt == "html":
        rendered = to_html(result, version=__version__, standards=standards)
    else:
        rendered = "\n".join(console_lines(result)) + "\n"

    if output_path:
        try:
            Path(output_path).write_text(rendered, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"could not write report to {output_path}: {exc}") from exc
        progress.line(f"Report written to {output_path}")
    else:
        click.echo(rendered, nl=False)

    if log_file:
        try:
            Path(log_file).write_text(log_text(result), encoding="utf-8", newline="\n")
            click.echo(f"Diagnostics log written to {log_file}", err=True)
        except OSError as exc:
            raise click.ClickException(f"could not write log file {log_file}: {exc}") from exc

    if strict and result.findings:
        sys.exit(2)


@cli.command(name="rules")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
def rules_cmd(fmt: str) -> None:
    """List every rule: id, severity, tier, and whether it needs the agent."""
    rules = all_rules()
    if fmt == "json":
        import json

        payload = [
            {
                "id": r.id,
                "title": r.title,
                "severity": r.severity,
                "category": r.category,
                "standard_ref": r.standard_ref,
                "tier": r.tier,
                "kind": r.kind,
                "default_enabled": r.default_enabled,
            }
            for r in rules
        ]
        click.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return
    click.echo(f"{len(rules)} rule(s) ('off' = disabled by default; enable in rules.yml):\n")
    for r in rules:
        tag = "agent" if r.kind == "agent" else r.severity
        off = "" if r.default_enabled else "  [off by default]"
        click.echo(f"  {r.id:26} [{tag:7}] T{r.tier} {r.standard_ref:5} {r.title}{off}")


def _run_upgrade(check_only: bool, yes: bool) -> None:
    """Shared self-update behind both `upgrade` and `update` (the only networked path)."""
    from coop_sql_review.upgrade import UpgradeError, apply_plan, build_plan

    plan = build_plan()
    click.echo(f"coop-sql-review {plan.tool_installed} ({plan.install_method}) — {plan.tool_note}")
    if plan.dependencies:
        click.echo("\nDependencies:")
        for dep in plan.dependencies:
            latest = dep.latest or "?"
            label = {
                "current": "up to date",
                "safe": f"update available -> {latest}",
                "major": f"MAJOR update available -> {latest} (review before applying)",
                "unknown": "could not check (offline?)",
            }[dep.kind]
            click.echo(f"  {dep.name:20} {dep.installed:12} {label}")
    if check_only:
        return
    if not yes:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            click.echo("\nRe-run with --yes to apply in non-interactive environments.", err=True)
            return
        if not click.confirm("\nApply the update and any non-breaking dependency updates?", default=True):
            click.echo("Nothing changed.")
            return
    try:
        executed = apply_plan(plan)
    except UpgradeError as exc:
        raise click.ClickException(str(exc)) from exc
    for command in executed:
        click.echo(f"ran: {' '.join(command)}", err=True)
    click.echo("Done. Run `coop-sql-review --version` to confirm.")


_UPGRADE_OPTIONS = [
    click.option("--check", "check_only", is_flag=True, help="Report available updates; change nothing."),
    click.option("--yes", is_flag=True, help="Apply without asking for confirmation."),
]


def _with_upgrade_options(func):
    for option in reversed(_UPGRADE_OPTIONS):
        func = option(func)
    return func


@cli.command()
@_with_upgrade_options
def upgrade(check_only: bool, yes: bool) -> None:
    """Update coop-sql-review to the latest version (and safe dependency bumps).

    The ONLY command that uses the network. Major dependency jumps are
    reported but never auto-applied.
    """
    _run_upgrade(check_only, yes)


@cli.command()
@_with_upgrade_options
def update(check_only: bool, yes: bool) -> None:
    """Alias for `upgrade` — update coop-sql-review to the latest version."""
    _run_upgrade(check_only, yes)


@cli.command(name="help")
@click.argument("command_name", required=False)
@click.pass_context
def help_cmd(ctx: click.Context, command_name: str | None) -> None:
    """Show help. `help` for everything, or `help <command>` (e.g. `help check`)."""
    parent = ctx.parent
    if command_name is None:
        click.echo(parent.get_help())
        return
    command = cli.get_command(ctx, command_name)
    if command is None:
        raise click.UsageError(f"unknown command '{command_name}' — try `coop-sql-review help`", ctx=parent)
    sub_ctx = click.Context(command, info_name=command_name, parent=parent)
    click.echo(command.get_help(sub_ctx))


def _force_utf8_console() -> None:
    """Emit UTF-8 on every platform so non-ASCII in messages (the § section
    marks, em-dashes) never raise UnicodeEncodeError on a legacy Windows
    console (cp1252/cp437). errors='replace' guarantees we never crash on
    output; worst case an old console shows a replacement glyph."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # not a reconfigurable text stream (e.g. under test capture)


def main() -> None:
    """Console-script entrypoint: friendly one-line errors, 130 on Ctrl-C."""
    _force_utf8_console()
    try:
        cli(obj={}, standalone_mode=False)
    except click.exceptions.Abort:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)
    except click.exceptions.Exit as exc:  # --help / --version
        sys.exit(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
