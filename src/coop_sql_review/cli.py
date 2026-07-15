"""Command-line interface.

Thin wrapper over the pipeline (discover -> parse -> run rules -> render).
Advisory by default: exit code 0 no matter what is found. ``--strict`` is the
opt-in CI gate — exit 2 when any reported finding remains after the
``--min-severity`` filter, or when zero files were checked (a typo'd path must
not pass as clean). CLI input errors (bad flags, missing/malformed --config)
are one-line usage errors (exit 2); unwritable output sinks are one-line
ClickExceptions (exit 1). Never a traceback.
"""

from __future__ import annotations

import codecs
import difflib
import json
import logging
import os
import sys
from pathlib import Path

import click
from coop_review_core.cliutils import (
    apply_syntax_error_policy,
    config_write_path,
    run_upgrade,
    with_upgrade_options,
)

# The tool-agnostic CLI helpers live in coop_review_core.cliutils (core 0.4.0,
# issue #10); the established `_`-prefixed module names are kept as aliases so
# call sites (and the tests that monkeypatch them) stay unchanged.
from coop_review_core.cliutils import (
    display_path as _display_path,
)
from coop_review_core.cliutils import (
    force_utf8_console as _force_utf8_console,
)
from coop_review_core.cliutils import (
    should_open_report as _should_open_report,
)
from coop_review_core.cliutils import (
    stdio_interactive as _stdio_interactive,
)
from coop_review_core.cliutils import (
    use_color as _use_color,
)
from coop_review_core.cliutils import (
    write_extra_report as _write_extra_report,
)
from coop_review_core.delta import DeltaError, delta_text, diff_envelopes

from coop_sql_review import __version__
from coop_sql_review.diagnostics import (
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    DYNAMIC_SQL,
    FILE_UNREADABLE,
    IGNORE_STALE,
    SCAN_EMPTY,
    Diagnostic,
)
from coop_sql_review.engine import run_rules
from coop_sql_review.finding import SEVERITIES
from coop_sql_review.parser import parse_sql
from coop_sql_review.progress import Progress, should_enable
from coop_sql_review.report import (
    console_lines,
    json_text,
    log_text,
    to_html,
    to_json,
    to_markdown,
    to_sarif,
)
from coop_sql_review.rules import all_rules, rule_docs
from coop_sql_review.rules.base import TARGETS
from coop_sql_review.sql_model import ParsedFile
from coop_sql_review.suppressions import (
    TOOL,
    BaselineError,
    is_inline_suppressed,
    load_baseline,
    scan_directives,
    write_baseline,
)
from coop_sql_review.standards import (
    RuleConfig,
    StandardsError,
    add_ignores,
    apply_config,
    default_config_path,
    discover_config,
    load_config_friendly,
    parse_syntax_errors_knob,
    resolve_standards_path,
    section_text,
    standards_info,
)

_SEVERITY_CHOICE = click.Choice(SEVERITIES)

# Where `--format html` lands when -o is omitted: HTML is meant for a browser,
# so it is always written to a file (mirrors coop-dax-review's convention).
_DEFAULT_HTML_NAME = "coop-sql-review-report.html"


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


# BOM -> codec, longest BOM first: the UTF-32-LE BOM (ff fe 00 00) starts with
# the UTF-16-LE BOM (ff fe), so order matters. UTF-16 is what Windows tooling
# actually produces (SSMS "Save with Encoding: Unicode", PowerShell 5.1 `>`).
_BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _decode_sql_bytes(raw: bytes, display: str) -> tuple[str | None, Diagnostic | None]:
    """Decode a ``.sql`` file's bytes BOM-aware; a coverage gap is never silent.

    Returns ``(text, diagnostic)``: a UTF-16/32 BOM selects that codec (the file
    is then linted normally); anything else decodes as ``utf-8-sig``. Bytes that
    are not valid for the codec still decode (with replacements) so the file is
    linted, but a warning Diagnostic surfaces the gap. Text that comes out
    NUL-riddled (UTF-16 saved without a BOM, or binary) would parse into garbage
    and dodge every rule, so it is skipped with an error Diagnostic instead of
    being reported as silently clean — ``text`` is ``None`` in that case.
    """
    encoding = "utf-8-sig"
    for bom, bom_encoding in _BOM_ENCODINGS:
        if raw.startswith(bom):
            encoding = bom_encoding
            break
    try:
        text = raw.decode(encoding)
        diagnostic = None
    except UnicodeDecodeError as exc:
        text = raw.decode(encoding, errors="replace")
        diagnostic = Diagnostic(
            severity="warning",
            category=FILE_UNREADABLE,
            file=display,
            line=0,
            message=(
                f"file is not valid {encoding} ({exc.reason} at byte {exc.start}) - decoded with "
                "replacement characters, so findings in it may be off. Re-save the file as UTF-8."
            ),
        )
    if "\x00" in text:
        return None, Diagnostic(
            severity="error",
            category=FILE_UNREADABLE,
            file=display,
            line=0,
            message=(
                "file looks like UTF-16 without a BOM (or binary) - it cannot be checked. "
                "Re-save it as UTF-8 (or UTF-16 with a BOM) and re-run."
            ),
        )
    return text, diagnostic


def _parse_files(files: list[Path], dialect: str, on_file=None) -> tuple[list[ParsedFile], list[Diagnostic]]:
    """Parse each file; an unreadable/undecodable file becomes a diagnostic,
    not a crash and never a silent skip.

    ``on_file`` (optional) is ticked once per file for progress reporting.
    """
    parsed: list[ParsedFile] = []
    read_diagnostics: list[Diagnostic] = []
    for path in files:
        if on_file:
            on_file(path)
        try:
            raw = path.read_bytes()
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
        text, diagnostic = _decode_sql_bytes(raw, _display_path(path))
        if diagnostic is not None:
            read_diagnostics.append(diagnostic)
        if text is None:
            continue
        parsed.append(parse_sql(_display_path(path), text, dialect=dialect))
    return parsed, read_diagnostics


def _discover_config_path(
    config_path: str | None, std_path: Path, save_ignores: bool
) -> tuple[Path, tuple[str, ...]]:
    """Where to READ the config from, via core's family-wide discovery
    (coop-review-core#12). First hit wins: ``--config`` > the
    ``COOP_SQL_REVIEW_CONFIG`` env var > a git-style walk from the cwd up
    through its parents (``coop-sql-review.yml`` first in each directory, then
    ``rules.yml`` as the DEPRECATED shared name; the walk stops at a ``.git``
    root) > the conventional spot beside the standards file.

    An explicit ``--config`` (or env-var path) that doesn't exist is a usage
    error (exit 2) — almost always a typo, and silently running with the default
    rules would drop the team's overrides/ignores. EXCEPT under
    ``--save-ignores``, where the flag also names the file to CREATE (kept
    tool-side; core doesn't know about that flag). Returns the resolved path
    plus core's human-facing notes (deprecation/shadowing one-liners) for the
    caller to surface on stderr.
    """
    if config_path and save_ignores and not Path(config_path).is_file():
        return Path(config_path), ()
    try:
        discovered = discover_config(
            TOOL,
            explicit=config_path,
            env=os.environ,
            start=Path.cwd(),
            bundled_default=default_config_path(std_path),
        )
    except StandardsError as exc:
        raise click.UsageError(str(exc)) from exc
    # bundled_default is always passed, so discovery never returns a None path;
    # the `or` keeps the type checker honest without an assert.
    return discovered.path or default_config_path(std_path), discovered.notes


def _resolve_target(flag: str | None, cfg_path: Path, cfg_data: dict) -> str:
    """The active SQL target: ``--target`` flag > rules.yml ``target:`` > default fabric-dw.
    ``cfg_data`` is the raw config mapping ``_load_rule_config`` already read (core's
    loader ignores the ``target:`` key, so it's resolved here — with no re-read). An
    invalid ``target:`` in the config is a friendly usage error, never a silent
    wrong-target run (the flag is already constrained by click.Choice)."""
    if flag:
        return flag
    if cfg_data.get("target") is None:
        return TARGETS[0]  # fabric-dw
    cfg_target = str(cfg_data["target"]).strip().lower()
    if cfg_target not in TARGETS:
        raise click.UsageError(
            f"invalid `target:` in {cfg_path.as_posix()}: {cfg_target!r} (expected one of: {', '.join(TARGETS)})"
        )
    return cfg_target


def _config_write_path(config_path: str | None, cfg_path: Path) -> Path:
    """Where to WRITE ignores — core's write-back-to-what-was-read rule (issue #7),
    with this package's directory as the never-write-inside-the-package guard."""
    return config_write_path(config_path, cfg_path, package_dir=Path(__file__).resolve().parent)


def _load_rule_config(path: Path) -> tuple[RuleConfig, str, str, dict]:
    """Core's friendly config load (one read) + this tool's ``syntax_errors`` and
    ``dynamic_sql`` knobs, under the CLI's friendly-error contract.

    Returns ``(config, syntax_errors_mode, dynamic_sql_mode, raw_mapping)`` where
    each mode is one of ``error``/``warning``/``off`` (defaults: ``error`` for
    syntax errors, ``warning`` for dynamic SQL) and ``raw_mapping`` is the file's
    top-level mapping (for tool-side keys like ``target:``).

    rules.yml is a hand-edited file (and auto-discovered), so any problem in it —
    bad YAML, wrong shape, an unknown severity or knob value, a wrong encoding —
    must become a one-line usage error (exit 2) naming the file, never a
    traceback. A path that simply doesn't exist loads as the empty config; the
    explicit ``--config``-typo case is rejected earlier, in ``check``.
    """
    try:
        config, data = load_config_friendly(path)
        syntax_mode = "error"
        if data.get("syntax_errors") is not None:
            syntax_mode = parse_syntax_errors_knob(data["syntax_errors"])
        dynamic_mode = "warning"
        if data.get("dynamic_sql") is not None:
            dynamic_mode = _parse_dynamic_sql_knob(data["dynamic_sql"])
    except StandardsError as exc:
        raise click.UsageError(f"could not load config {path}: {exc}") from exc
    return config, syntax_mode, dynamic_mode, data


_DYNAMIC_SQL_MODES = ("error", "warning", "off")


def _parse_dynamic_sql_knob(raw: object) -> str:
    """The ``dynamic_sql: error|warning|off`` knob (default ``warning``) — same
    shape and YAML-1.1 tolerance as core's ``syntax_errors`` parser (an unquoted
    ``off`` arrives as the boolean ``False``)."""
    candidate = "off" if raw is False else str(raw).strip().lower()
    if candidate not in _DYNAMIC_SQL_MODES:
        raise StandardsError(f"`dynamic_sql` must be one of {', '.join(_DYNAMIC_SQL_MODES)} (got '{raw}')")
    return candidate


def _apply_dynamic_sql_policy(diagnostics: list[Diagnostic], mode: str) -> list[Diagnostic]:
    """Apply the ``dynamic_sql`` knob to DYNAMIC_SQL diagnostics, leaving every
    other diagnostic untouched: ``off`` drops them, ``error`` promotes them (so
    ``--strict`` gates on un-analyzed dynamic SQL), ``warning`` (default) keeps
    them as emitted. Only ``off`` removes the line — a coverage gap is never
    silent otherwise."""
    from dataclasses import replace

    if mode == "warning":
        return diagnostics
    if mode == "off":
        return [d for d in diagnostics if d.category != DYNAMIC_SQL]
    return [
        replace(d, severity="error") if d.category == DYNAMIC_SQL and d.severity != "error" else d
        for d in diagnostics
    ]


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


def _finding_ignore_label(f):
    loc = f"{f.file}:{f.line}" if f.line else f.file
    msg = f.message if len(f.message) <= 70 else f.message[:69] + "..."
    return f"[{f.severity}] {f.rule_id}  {loc}  {msg}"


def _finding_ignore_entry(f):
    return {
        "fingerprint": f.fingerprint(),
        "rule": f.rule_id,
        "where": (f"{f.file}:{f.line}" if f.line else f.file),
    }


def _pick_findings_to_ignore(findings):
    """Checkbox of findings to ignore (all start UNchecked -> opt-in). Returns the
    chosen findings, or [] if questionary is unavailable / nothing picked. Mirrors
    the error-handling of the existing _interactive_pick_paths helper."""
    try:
        import questionary
    except ImportError:
        return []
    choices = [questionary.Choice(title=_finding_ignore_label(f), value=f, checked=False) for f in findings]
    try:
        selected = questionary.checkbox(
            "Findings to add to the ignore list (SPACE to toggle, ENTER to confirm):", choices=choices
        ).ask()
    except (OSError, EOFError):
        return []
    return list(selected or [])


def _save_ignores_interactive(findings, config_path: str | None, cfg_path: Path) -> None:
    """Let the user pick findings from this run to append to rules.yml's ignore
    list, so they are silenced on the next run. Interactive-terminal only.
    ``cfg_path`` is the config this run READ from, so the ignore is written back to it
    (not a shadowing ./rules.yml) — see :func:`_config_write_path`."""
    if not findings:
        click.echo("Nothing to ignore: this run reported no findings.", err=True)
        return
    if not _stdio_interactive():
        click.echo("--save-ignores needs an interactive terminal; nothing written.", err=True)
        return
    selected = _pick_findings_to_ignore(findings)
    if not selected:
        click.echo("No findings selected; the ignore list is unchanged.", err=True)
        return
    target = _config_write_path(config_path, cfg_path)
    try:
        added = add_ignores(target, [_finding_ignore_entry(f) for f in selected])
    except (StandardsError, OSError, ValueError) as exc:
        # core 0.5.0's add_ignores raises StandardsError (a CoopReviewError, not an
        # OSError/ValueError) for an unreadable/unwritable/invalid target; keep OSError
        # + ValueError too as belt-and-braces so this exits 1 with one line, never a traceback.
        raise click.ClickException(f"could not update the ignore list in {target}: {exc}") from exc
    click.echo(
        f"Added {added} finding(s) to the ignore list in {target.resolve().as_posix()}; "
        "re-run to confirm they are silenced.",
        err=True,
    )


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="coop-sql-review")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Offline, advisory SQL standards linter for Microsoft Fabric DW and Azure serverless SQL.

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
    "--config",
    "config_path",
    default=None,
    help="Path to a config YAML (default: auto-discovered — the COOP_SQL_REVIEW_CONFIG env var, "
    "then coop-sql-review.yml or rules.yml in this or a parent folder, then alongside standards).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "markdown", "html", "sarif"]),
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
    "--html",
    "html_path",
    type=click.Path(),
    default=None,
    help="Also write a self-contained HTML report to this path (composes with any --format).",
)
@click.option(
    "--md",
    "--markdown",
    "md_path",
    type=click.Path(),
    default=None,
    help="Also write a Markdown report to this path (composes with any --format).",
)
@click.option(
    "--sarif",
    "sarif_path",
    type=click.Path(),
    default=None,
    help="Also write a SARIF 2.1.0 report to this path (for GitHub/ADO PR annotations; composes with any --format).",
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
    help="Suppress findings and agent-review items already recorded in this baseline file "
    "(only new ones surface).",
)
@click.option(
    "--write-baseline",
    "write_baseline_path",
    type=click.Path(),
    default=None,
    help="Write the current findings and agent-review items to this baseline file "
    "(ratchet setup), then report as usual.",
)
@click.option(
    "--save-ignores",
    "save_ignores",
    is_flag=True,
    help="After the report, interactively pick findings to add to rules.yml's ignore list "
    "(silenced next run).",
)
@click.option("--dialect", default="tsql", show_default=True, help="sqlglot dialect to parse with.")
@click.option(
    "--target",
    type=click.Choice(["fabric-dw", "azure-sql"]),
    default=None,
    help="SQL target. fabric-dw (default) enforces Fabric DW type/feature limits; azure-sql "
    "skips the Fabric-DW-only rules (Azure serverless SQL supports those types). Overrides a "
    "`target:` key in rules.yml.",
)
@click.option(
    "--log-file",
    "log_file",
    type=click.Path(),
    default=None,
    help="Write a diagnostics log (parse problems, rule errors) to this file.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Opt-in CI gate: exit 2 if any reported finding remains (at/above --min-severity), "
    "if any error-severity diagnostic remains (a real syntax error, a rule crash, an "
    "unreadable file), or if no files were checked.",
)
@click.option(
    "--diff-against",
    "diff_against",
    type=click.Path(),
    default=None,
    help="Compare this run against a previous run's JSON envelope (a saved --format json "
    "report): print a new / fixed / persisting delta to stderr. Advisory - never changes the "
    "exit code.",
)
@click.option(
    "--changed",
    "changed_ref",
    is_flag=False,
    flag_value="HEAD",
    default=None,
    help="Only check files changed since this git ref (e.g. HEAD, origin/main).",
)
@click.pass_context
def check(
    ctx: click.Context,
    paths: tuple[str, ...],
    standards_path: str | None,
    config_path: str | None,
    fmt: str,
    output_path: str | None,
    html_path: str | None,
    md_path: str | None,
    sarif_path: str | None,
    open_report: bool | None,
    color_flag: bool | None,
    min_severity: str,
    baseline_path: str | None,
    write_baseline_path: str | None,
    save_ignores: bool,
    dialect: str,
    target: str | None,
    log_file: str | None,
    strict: bool,
    diff_against: str | None,
    changed_ref: str | None,
) -> None:
    """Check SQL files (or directories) against the standards.

    Advisory only: it reports, it never edits or blocks (exit 0 unless --strict).

    \b
    Report output:
      The text report prints to the screen. To redirect or save it:
        --format text|json|markdown|html|sarif   choose the format (default: text)
                                           (sarif = GitHub/ADO PR annotations)
        -o, --output FILE                  write that report to FILE
      --format html always writes a file: FILE if you give -o, otherwise
      coop-sql-review-report.html in the current folder — then opens it in
      your browser (see --open/--no-open).
      To ALSO save shareable files in ONE run -- on top of whatever prints --
      add any of these (they compose with each other and with --format):
        --html FILE   a self-contained, branded HTML report
        --md FILE     a Markdown report
        --sarif FILE  a SARIF report for GitHub/ADO PR annotations
    \b
        coop-sql-review check ./sql --html report.html --md report.md

    \b
    Ignoring findings you've accepted (advisory -- nothing is ever deleted):
      --save-ignores   After the report, pick findings from an interactive
                       checklist (SPACE toggles, ENTER confirms). The picks are
                       written to rules.yml and stay silenced on later runs:
    \b
        coop-sql-review check ./sql --save-ignores   # tick the ones to silence
        coop-sql-review check ./sql                   # they no longer show
    \b
      The ignore list lives in your config file as an `ignore:` list of
      fingerprints (each with rule/where/note) -- editable by hand, and picked
      up automatically when a coop-sql-review.yml (preferred) or rules.yml sits
      in the current directory or a parent (or pass --config FILE, or set
      COOP_SQL_REVIEW_CONFIG). You can also disable a whole rule there, or drop an
      inline `-- coop-sql-review:ignore RULE-ID` comment on the finding's line.
      All three suppressions (inline, baseline, ignore list) silence
      agent-review items the same way they silence findings.
    """
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    # Config discovery (core 0.4.0): --config > COOP_SQL_REVIEW_CONFIG > a git-style
    # walk-up (coop-sql-review.yml, then the deprecated rules.yml) > beside the
    # standards. An explicit --config (or env path) that doesn't exist is a usage
    # error — except under --save-ignores, where the flag names the file to CREATE.
    # Auto-discovery absence stays silent; discovery notes (deprecation/shadowing)
    # are stderr one-liners so machine output on stdout stays byte-identical.
    cfg_path, cfg_notes = _discover_config_path(config_path, std_path, save_ignores)
    for note in cfg_notes:
        click.echo(note, err=True)
    config, syntax_mode, dynamic_mode, cfg_data = _load_rule_config(cfg_path)
    from coop_sql_review.rules.custom import build_custom_rules
    base_rules = all_rules() + build_custom_rules(cfg_data, cfg_path)
    rules = apply_config(base_rules, config)
    unknown_rules = config.unknown_rule_ids({r.id for r in base_rules})
    # SQL target: skip rules that don't apply to it (e.g. Fabric-DW-only type rules under
    # --target azure-sql). Resolved AFTER apply_config so an explicit enable/severity in
    # rules.yml is still honored for the rules that DO apply.
    active_target = _resolve_target(target, cfg_path, cfg_data)
    rules = [r for r in rules if active_target in r.targets]

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
    if changed_ref is not None:
        try:
            from coop_review_core.gitscope import get_changed_files
            changed_paths = get_changed_files(".sql", ref=changed_ref)
            changed_abs = {Path(p).resolve() for p in changed_paths}
            if paths:
                files = [f for f in files if f.resolve() in changed_abs]
            else:
                files = [Path(p) for p in changed_paths]
        except Exception as exc:
            raise click.UsageError(str(exc)) from exc
    if not files and not missing and changed_ref is None:
        click.echo("No .sql files found.", err=True)
    # No early return: a zero-file scan still renders the full report in every
    # format/sink (files_checked=0 is the machine contract's own disambiguator),
    # with scan_empty diagnostics below making the empty scan machine-visible.

    # Progress is stderr-only + TTY-gated, so it never pollutes the report
    # (stdout) or a redirected --output file.
    progress = Progress(should_enable(quiet=False))
    progress.line(f"Checking {len(files)} SQL file(s)...")
    with progress.bar("Parsing", total=len(files)) as tick:
        parsed, read_diagnostics = _parse_files(files, dialect, on_file=tick)
    result = run_rules(parsed, rules)
    result.diagnostics.extend(read_diagnostics)
    if not files:
        # One scan_empty diagnostic per searched root, so an agent (or a CI log
        # reader) can tell a typo'd/empty path from a genuinely clean estate.
        for root in paths or (".",):
            if changed_ref is not None:
                problem = "no .sql files changed since " + changed_ref
            else:
                problem = "path not found" if root in missing else "no .sql files found under this path"
            result.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=SCAN_EMPTY,
                    file=Path(root).as_posix(),
                    line=0,
                    message=f"{problem} - nothing was checked (is the path right?)",
                )
            )
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
    # suppressed finding is gone regardless of severity. Agent-review items get the
    # same full pipeline as findings — an accepted MERGE shouldn't be re-raised to
    # the analytics agent on every run.
    inline = {pf.path: scan_directives(pf.text) for pf in parsed}
    result.findings = [
        f for f in result.findings if not is_inline_suppressed(f.rule_id, f.line, inline.get(f.file, {}))
    ]
    result.agent_review = [
        a for a in result.agent_review if not is_inline_suppressed(a.rule_id, a.line, inline.get(a.file, {}))
    ]

    # Syntax-error diagnostics (genuinely invalid T-SQL) obey the rules.yml
    # `syntax_errors` knob and an inline `coop-sql-review:ignore syntax` directive
    # on the error's line or the line above. `off` (or an inline ignore) removes
    # the diagnostic; `warning` demotes but keeps it visible; `error` (default)
    # leaves it. Only `off`/inline removal drops the line — a coverage gap is
    # never silent otherwise (AGENTS.md error-handling requirement). The policy
    # itself is core's (cliutils.apply_syntax_error_policy).
    result.diagnostics = apply_syntax_error_policy(
        result.diagnostics, syntax_mode, texts={pf.path: pf.text for pf in parsed}, tool=TOOL
    )
    # Dynamic-SQL diagnostics (issue #19: string-built statements no rule can see)
    # obey the rules.yml `dynamic_sql` knob the same way: `off` drops, `error`
    # promotes (--strict then gates on them), `warning` (default) keeps.
    result.diagnostics = _apply_dynamic_sql_policy(result.diagnostics, dynamic_mode)
    # The full set of fingerprints this run produced (pre-baseline, pre-ignore) so a
    # stale ignore entry can be told from one another filter already consumed. An
    # entry matching only an agent-review item is NOT stale.
    present_fingerprints = {f.fingerprint() for f in result.findings} | {
        a.fingerprint() for a in result.agent_review
    }
    if write_baseline_path:
        try:
            count = write_baseline(Path(write_baseline_path), sorted(present_fingerprints))
        except OSError as exc:
            raise click.ClickException(f"could not write baseline to {write_baseline_path}: {exc}") from exc
        click.echo(
            f"Wrote baseline of {count} finding/agent-review entr{'y' if count == 1 else 'ies'} "
            f"to {write_baseline_path}",
            err=True,
        )
    elif baseline_path:
        # A corrupt/missing/wrong-tool baseline is a friendly usage error (exit 2),
        # not a silent empty set that floods every baselined finding back.
        try:
            baseline_fps = load_baseline(Path(baseline_path))
        except BaselineError as exc:
            raise click.UsageError(str(exc)) from exc
        result.findings = [f for f in result.findings if f.fingerprint() not in baseline_fps]
        result.agent_review = [a for a in result.agent_review if a.fingerprint() not in baseline_fps]
        stale = len(baseline_fps - present_fingerprints)
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
    # rules.yml "ignore:" list — human-readable, fingerprint-matched suppressions
    # (like the baseline, but living in the one writable config file). Filtered before
    # the --min-severity floor, so an ignored finding is gone regardless of severity.
    if config.ignored_fingerprints:
        result.findings = [f for f in result.findings if f.fingerprint() not in config.ignored_fingerprints]
        result.agent_review = [
            a for a in result.agent_review if a.fingerprint() not in config.ignored_fingerprints
        ]
        stale = len(config.ignored_fingerprints - present_fingerprints)
        if stale:
            result.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=IGNORE_STALE,
                    file=cfg_path.as_posix(),
                    line=0,
                    message=f"rules.yml ignore: {stale} entr{'y' if stale == 1 else 'ies'} no longer "
                    "match a current finding",
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
    elif fmt == "sarif":
        # Like json: renders to stdout unless -o is given (SARIF is file-oriented but a
        # stdout dump pipes fine and keeps parity with the other machine formats).
        rendered = to_sarif(result, version=__version__, standards=standards)
    else:
        body = console_lines(result, version=__version__, standards=standards, color=use_color)
        rendered = "\n".join(body) + "\n"

    if fmt == "html":
        # HTML is meant to be viewed in a browser: always write it to a file (a
        # default name when -o is omitted — never a raw dump to the screen),
        # announce the path, then open it (TTY-gated; --open/--no-open override).
        # Mirrors coop-dax-review's `--format html` contract.
        out_file = Path(output_path) if output_path else Path(_DEFAULT_HTML_NAME)
        try:
            out_file.write_text(rendered, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"could not write report to {out_file}: {exc}") from exc
        resolved = out_file.resolve()
        click.echo(f"HTML report written to {resolved.as_posix()}", err=True)
        if _should_open_report(fmt, open_report):
            _open_report(resolved)
    elif output_path:
        out_file = Path(output_path)
        try:
            out_file.write_text(rendered, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"could not write report to {output_path}: {exc}") from exc
        resolved = out_file.resolve()
        # Always announce the path (not gated on the TTY progress bar) so a
        # piped run or an agent can find the file it just wrote.
        click.echo(f"Report written to {resolved.as_posix()}", err=True)
    else:
        click.echo(rendered, nl=False, color=use_color)

    if html_path:
        _write_extra_report(html_path, to_html(result, version=__version__, standards=standards), "HTML")
    if md_path:
        _write_extra_report(
            md_path, to_markdown(result, version=__version__, standards=standards) + "\n", "Markdown"
        )
    if sarif_path:
        _write_extra_report(sarif_path, to_sarif(result, version=__version__, standards=standards), "SARIF")

    if log_file:
        try:
            Path(log_file).write_text(log_text(result), encoding="utf-8", newline="\n")
            click.echo(f"Diagnostics log written to {log_file}", err=True)
        except OSError as exc:
            raise click.ClickException(f"could not write log file {log_file}: {exc}") from exc

    if save_ignores:
        _save_ignores_interactive(result.findings, config_path, cfg_path)

    # --diff-against: compare this run to a previous run's saved JSON envelope and print
    # a new / fixed / persisting delta to stderr (core's shared delta engine). Advisory —
    # the exit code is never changed. The current envelope is this run's report (after
    # suppressions + the --min-severity floor), so the delta reflects what each run
    # actually reported. A missing / non-JSON / wrong-tool file is a usage error (exit 2),
    # mirroring --baseline.
    if diff_against:
        try:
            old_envelope = json.loads(Path(diff_against).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise click.UsageError(f"--diff-against: cannot read {diff_against}: {exc}") from exc
        except ValueError as exc:
            raise click.UsageError(f"--diff-against: {diff_against} is not valid JSON: {exc}") from exc
        if not isinstance(old_envelope, dict):
            raise click.UsageError(
                f"--diff-against: {diff_against} is not a review envelope (expected a JSON object)"
            )
        try:
            delta = diff_envelopes(old_envelope, to_json(result, version=__version__, standards=standards))
        except DeltaError as exc:
            raise click.UsageError(str(exc)) from exc
        click.echo(delta_text(delta, color=use_color), err=True, nl=False)

    # --strict also fails when NOTHING was checked (files_checked == 0): a
    # typo'd path in CI must not pass as silently clean; and when any
    # error-severity diagnostic remains (a genuine syntax error, a rule crash,
    # or an unreadable file) after the syntax knob/suppression have had their say.
    has_error_diagnostic = any(d.severity == "error" for d in result.diagnostics)
    if strict and (result.findings or result.files_checked == 0 or has_error_diagnostic):
        sys.exit(2)


@cli.command(name="compare")
@click.argument("old_json", type=click.Path(exists=True))
@click.argument("new_json", type=click.Path(exists=True))
@click.option("--md", "md_path", type=click.Path(), default=None, help="Write a Markdown report to this path.")
@click.option("--html", "html_path", type=click.Path(), default=None, help="Write an HTML report to this path.")
@click.option("--color/--no-color", "color_flag", default=None, help="Colorize the console output.")
def compare_cmd(old_json: str, new_json: str, md_path: str | None, html_path: str | None, color_flag: bool | None) -> None:
    """Compare two review JSON reports and show the delta (fixed / new / unchanged)."""
    from coop_sql_review.comparison import run_compare
    run_compare(old_json, new_json, md_path, html_path, color_flag)

@cli.command(name="rules")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
def rules_cmd(fmt: str) -> None:
    """List every rule: id, severity, tier, and whether it needs the agent."""
    rules = all_rules()

    # also include custom rules if we can discover a config
    from coop_review_core.config import default_config_path
    from coop_review_core.config import discover_config
    from coop_sql_review.rules.custom import build_custom_rules
    from pathlib import Path
    try:
        cfg_path = discover_config("coop-sql-review", explicit=None, env={}, start=Path.cwd(), bundled_default=default_config_path(Path(".")))
        from coop_review_core.config import load_config_friendly
        cfg_data = load_config_friendly(cfg_path)
        custom = build_custom_rules(cfg_data, cfg_path)
        rules.extend(custom)
    except Exception:
        pass
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
                "targets": sorted(r.targets),
            }
            for r in rules
        ]
        click.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return
    click.echo(f"{len(rules)} rule(s) ('off' = disabled by default; enable in rules.yml):\n")
    for r in rules:
        tag = "agent" if r.kind == "agent" else r.severity
        off = "" if r.default_enabled else "  [off by default]"
        # Flag rules that only apply under one target (e.g. Fabric-DW type limits).
        scope = "" if set(r.targets) == set(TARGETS) else f"  [{'/'.join(sorted(r.targets))} only]"
        click.echo(f"  {r.id:26} [{tag:7}] T{r.tier} {r.standard_ref:5} {r.title}{off}{scope}")


@cli.command()
@click.argument("rule_id")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option(
    "--color/--no-color",
    "color_flag",
    default=None,
    help="Colorize the explanation (default: auto — only at an interactive terminal).",
)
@click.option(
    "--standards",
    "standards_path",
    type=click.Path(),
    default=None,
    help="Standards file to quote the section from (default: the bundled copy).",
)
def explain(rule_id: str, fmt: str, color_flag: bool | None, standards_path: str | None) -> None:
    """Explain a rule: its rationale, standards excerpt, severity, and targets.

    RULE_ID is case-insensitive (e.g. SQL-TYPE-MONEY). This prints what a finding
    only cites — so a client developer reading the report never needs
    docs/standards.md open, and the agent can pull rule rationale for triage
    (`--format json`). An unknown id is a usage error with a did-you-mean.
    """
    from coop_review_core.report import sty

    by_id = {r.id: r for r in all_rules()}
    match = by_id.get(rule_id) or by_id.get(rule_id.upper())
    if match is None:
        suggestions = difflib.get_close_matches(rule_id.upper(), list(by_id), n=3, cutoff=0.5)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise click.UsageError(
            f"unknown rule id '{rule_id}'. Run `coop-sql-review rules` to list them.{hint}"
        )

    doc = rule_docs().get(match.id, "").strip()
    section = section_text(resolve_standards_path(standards_path), match.standard_ref)

    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "id": match.id,
                    "title": match.title,
                    "severity": match.severity,
                    "category": match.category,
                    "standard_ref": match.standard_ref,
                    "tier": match.tier,
                    "kind": match.kind,
                    "default_enabled": match.default_enabled,
                    "targets": sorted(match.targets),
                    "params": match.params,
                    "rationale": doc,
                    "standards_excerpt": section,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
        return

    use_col = _use_color(color_flag, None)
    tag = "agent-judgment" if match.kind == "agent" else f"{match.severity} (default)"
    meta = f"severity: {tag}   tier: {match.tier}   standard: {match.standard_ref}"
    if set(match.targets) != set(TARGETS):
        meta += f"   targets: {'/'.join(sorted(match.targets))} only"
    if not match.default_enabled:
        meta += "   [off by default — enable in rules.yml]"

    out = [sty(f"{match.id} - {match.title}", "bold", color=use_col), meta]
    if match.params:
        out.append("params: " + ", ".join(f"{k}={v!r}" for k, v in sorted(match.params.items())))
    if doc:
        out += ["", sty("Why", "bold", color=use_col), doc]
    if section:
        out += ["", sty(f"Standard {match.standard_ref}", "bold", color=use_col), section]
    elif not match.standard_ref.lstrip("§").isdigit():
        out += [
            "",
            f"(Standard {match.standard_ref} is a proposed-additions rule — see "
            "docs/standards-proposed-additions.md in the repo; the rationale above still applies.)",
        ]
    click.echo("\n".join(out))


def _run_upgrade(check_only: bool) -> None:
    """Shared logic behind `upgrade` and `update` (the only networked path).

    Checks PyPI for the latest release to report whether an update exists, then
    prints the exact command to run (core's ``cliutils.run_upgrade`` renders the
    report; commands are shlex-quoted so a path with spaces stays copy-pasteable).
    It does NOT apply the update itself: a running program can't reliably replace
    its own files (on Windows its console-script .exe is locked), so the user runs
    the command in a fresh terminal. This keeps the tool's advisory,
    never-acts-for-you contract.
    """
    from coop_sql_review.upgrade import build_plan  # lazy: the only networked module

    run_upgrade(check_only, tool_name=TOOL, plan=build_plan())


@cli.command()
@with_upgrade_options
def upgrade(check_only: bool) -> None:
    """Show how to update coop-sql-review to the latest version.

    The ONLY command that uses the network: it checks PyPI for the latest
    release and prints the command to run. It does not upgrade in place —
    a running program can't replace its own files — so run the printed
    command yourself in a fresh terminal.
    """
    _run_upgrade(check_only)


@cli.command()
@with_upgrade_options
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
