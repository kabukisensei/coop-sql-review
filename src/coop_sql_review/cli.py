"""Command-line interface.

Thin wrapper over the pipeline (discover -> parse -> run rules -> render).
Advisory by default: exit code 0 no matter what is found. ``--strict`` is the
opt-in CI gate — exit 2 when any reported finding remains after the
``--min-severity`` filter.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from coop_sql_review import __version__
from coop_sql_review.diagnostics import (
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    FILE_UNREADABLE,
    Diagnostic,
)
from coop_sql_review.engine import run_rules
from coop_sql_review.finding import SEVERITIES
from coop_sql_review.parser import parse_sql
from coop_sql_review.progress import Progress, should_enable
from coop_sql_review.report import console_lines, json_text, log_text, to_html, to_markdown
from coop_sql_review.rules import all_rules
from coop_sql_review.sql_model import ParsedFile
from coop_sql_review.suppressions import (
    is_inline_suppressed,
    load_baseline,
    scan_directives,
    write_baseline,
)
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
    found: dict[Path, Path] = {}  # resolved path -> original, so a file reached
    # via two overlapping roots (e.g. `.` and `./sub`) is only counted once.
    for root in roots:
        if root.is_file():
            found.setdefault(root.resolve(), root)
        elif root.is_dir():
            # Case-insensitive on the extension so `.SQL`/`.Sql` are not skipped.
            for candidate in root.rglob("*.[sS][qQ][lL]"):
                rel = candidate.relative_to(root)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if candidate.is_file():
                    found.setdefault(candidate.resolve(), candidate)
    return sorted(found.values(), key=lambda p: _display_path(p))


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


def _stdio_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _use_color(color_flag: bool | None, output_path: str | None) -> bool:
    """Whether to colorize the terminal report. An explicit ``--color`` /
    ``--no-color`` wins; otherwise auto: color only when writing to an
    interactive stdout (never to a file) and ``NO_COLOR`` is unset."""
    if color_flag is not None:
        return color_flag
    if output_path or os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _should_open_report(fmt: str, open_report: bool | None) -> bool:
    """Whether to open the just-written report in a browser.

    Only ever applies to the HTML report (the only browser-viewable format).
    An explicit ``--open``/``--no-open`` overrides the default; otherwise we
    auto-open only in an interactive terminal — so an agent or CI run, which
    just reads the file we name, never triggers a browser pop-up.
    """
    if fmt != "html":
        return False
    if open_report is not None:
        return open_report
    return _stdio_interactive()


def _open_report(path: Path) -> None:
    """Open a written report in the default browser. Best-effort: opening a
    browser is a convenience, so a failure is reported but never fatal (the
    file is already written and its path has been printed)."""
    import webbrowser

    try:
        opened = webbrowser.open(path.as_uri())
    except Exception as exc:
        click.echo(f"(could not open the report automatically: {exc})", err=True)
        return
    if not opened:
        click.echo("(could not find a browser to open it - open the path above yourself)", err=True)


def _interactive_pick_paths(root: Path) -> list[Path] | None:
    """Let the user pick which subfolders to check via a checkbox.

    All folders start selected, so pressing ENTER checks everything (== scan
    the whole folder). Returns the chosen paths, or None to fall back to the
    default behavior — no subfolders, questionary unavailable, or cancelled.
    """
    try:
        subdirs = sorted(
            (d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")),
            key=lambda d: d.name,
        )
    except OSError:
        return None
    if not subdirs:
        return None
    try:
        import questionary
    except ImportError:
        return None
    choices = [questionary.Choice(title=f"{d.name}/", value=d, checked=True) for d in subdirs]
    try:
        selected = questionary.checkbox(
            "Folders to check (all selected; SPACE to toggle, ENTER to confirm):", choices=choices
        ).ask()
    except (OSError, EOFError):
        return None
    if not selected:
        return None
    # Everything selected -> scan the root (also catches loose top-level .sql files).
    if len(selected) == len(subdirs):
        return [root]
    return list(selected)


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
    "--open/--no-open",
    "open_report",
    default=None,
    help="Open an HTML report in your browser when finished "
    "(default: auto - opens only in an interactive terminal).",
)
@click.option(
    "--color/--no-color",
    "color_flag",
    default=None,
    help="Colorize the text report (default: auto - only at an interactive terminal).",
)
@click.option(
    "--min-severity",
    type=_SEVERITY_CHOICE,
    default="info",
    show_default=True,
    help="Hide findings below this severity.",
)
@click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(),
    default=None,
    help="Suppress findings already recorded in this baseline file (only new ones surface).",
)
@click.option(
    "--write-baseline",
    "write_baseline_path",
    type=click.Path(),
    default=None,
    help="Write the current findings to this baseline file (ratchet setup), then report as usual.",
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
    open_report: bool | None,
    color_flag: bool | None,
    min_severity: str,
    baseline_path: str | None,
    write_baseline_path: str | None,
    dialect: str,
    log_file: str | None,
    strict: bool,
) -> None:
    """Check SQL files (or directories) against the standards."""
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    cfg_path = Path(config_path) if config_path else default_config_path(std_path)
    config = RuleConfig.load(cfg_path)
    rules = apply_config(all_rules(), config)
    unknown_rules = config.unknown_rule_ids({r.id for r in all_rules()})

    # With no paths in an interactive terminal, offer a folder picker.
    if not paths and _stdio_interactive():
        picked = _interactive_pick_paths(Path("."))
        if picked is not None:
            paths = tuple(str(p) for p in picked)

    # A path the user typed that doesn't exist is almost always a typo — call it
    # out so it isn't silently indistinguishable from a clean scan.
    missing = [p for p in paths if not Path(p).exists()]
    for p in missing:
        click.echo(f"path not found: {p}", err=True)

    files = discover_sql_files(paths)
    if not files:
        if not missing:
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
    for rule_id in unknown_rules:
        result.diagnostics.append(
            Diagnostic(
                severity="warning",
                category=CONFIG_UNKNOWN_RULE,
                file=cfg_path.as_posix(),
                line=0,
                message=f"rules.yml: unknown rule id '{rule_id}' - ignored",
            )
        )

    # Suppressions: inline `coop-sql-review:ignore` directives (always), then a
    # fingerprint baseline (opt-in). Both run before the --min-severity floor so a
    # suppressed finding is gone regardless of severity.
    inline = {pf.path: scan_directives(pf.text) for pf in parsed}
    result.findings = [
        f for f in result.findings if not is_inline_suppressed(f.rule_id, f.line, inline.get(f.file, {}))
    ]
    if write_baseline_path:
        count = write_baseline(Path(write_baseline_path), [f.fingerprint() for f in result.findings])
        click.echo(f"Wrote baseline of {count} finding(s) to {write_baseline_path}", err=True)
    elif baseline_path:
        baseline_fps = load_baseline(Path(baseline_path))
        seen = {f.fingerprint() for f in result.findings}
        result.findings = [f for f in result.findings if f.fingerprint() not in baseline_fps]
        stale = len(baseline_fps - seen)
        if stale:
            result.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=BASELINE_STALE,
                    file=Path(baseline_path).as_posix(),
                    line=0,
                    message=f"baseline: {stale} entr{'y' if stale == 1 else 'ies'} no longer match a "
                    "current finding; re-run --write-baseline to prune",
                )
            )
    result.diagnostics.sort(key=lambda d: d.sort_key())
    result = result.filtered(min_severity)

    standards = standards_info(std_path)
    use_color = fmt == "text" and _use_color(color_flag, output_path)
    if fmt == "json":
        rendered = json_text(result, version=__version__, standards=standards)
    elif fmt == "markdown":
        rendered = to_markdown(result, version=__version__, standards=standards) + "\n"
    elif fmt == "html":
        rendered = to_html(result, version=__version__, standards=standards)
    else:
        body = console_lines(result, version=__version__, standards=standards, color=use_color)
        rendered = "\n".join(body) + "\n"

    if output_path:
        out_file = Path(output_path)
        try:
            out_file.write_text(rendered, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"could not write report to {output_path}: {exc}") from exc
        resolved = out_file.resolve()
        # Always announce the path (not gated on the TTY progress bar) so a
        # piped run or an agent can find the file it just wrote.
        click.echo(f"Report written to {resolved.as_posix()}", err=True)
        if _should_open_report(fmt, open_report):
            _open_report(resolved)
    else:
        click.echo(rendered, nl=False, color=use_color)

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


def _run_upgrade(check_only: bool) -> None:
    """Shared logic behind `upgrade` and `update` (the only networked path).

    Checks PyPI for the latest release to report whether an update exists, then
    prints the exact command to run. It does NOT apply the update itself: a
    running program can't reliably replace its own files (on Windows its
    console-script .exe is locked), so the user runs the command in a fresh
    terminal. This keeps the tool's advisory, never-acts-for-you contract.
    """
    from coop_sql_review.upgrade import build_plan, upgrade_command

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
    commands = "\n".join(f"    {' '.join(cmd)}" for cmd in upgrade_command(plan))
    click.echo(
        "\nThis tool can't upgrade itself while it's running. To upgrade, "
        "open a new terminal and run:\n\n"
        f"{commands}\n"
    )


_UPGRADE_OPTIONS = [
    click.option(
        "--check",
        "check_only",
        is_flag=True,
        help="Only report whether an update is available; don't print the upgrade command.",
    ),
]


def _with_upgrade_options(func):
    for option in reversed(_UPGRADE_OPTIONS):
        func = option(func)
    return func


@cli.command()
@_with_upgrade_options
def upgrade(check_only: bool) -> None:
    """Show how to update coop-sql-review to the latest version.

    The ONLY command that uses the network: it checks PyPI for the latest
    release and prints the command to run. It does not upgrade in place —
    a running program can't replace its own files — so run the printed
    command yourself in a fresh terminal.
    """
    _run_upgrade(check_only)


@cli.command()
@_with_upgrade_options
def update(check_only: bool) -> None:
    """Alias for `upgrade` — show how to update coop-sql-review."""
    _run_upgrade(check_only)


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
            # newline="" disables write-time \n -> \r\n translation, so the JSON
            # contract (and the text report) stay byte-identical (LF) across OSes
            # even when redirected to a file on Windows.
            stream.reconfigure(encoding="utf-8", errors="replace", newline="")
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
