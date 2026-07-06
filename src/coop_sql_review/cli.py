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
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

import click
import yaml

from coop_sql_review import __version__
from coop_sql_review.diagnostics import (
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    FILE_UNREADABLE,
    IGNORE_STALE,
    SCAN_EMPTY,
    SYNTAX_ERROR,
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
    is_syntax_ignored,
    load_baseline,
    scan_directives,
    scan_syntax_ignores,
    write_baseline,
)
from coop_sql_review.standards import (
    RuleConfig,
    StandardsError,
    add_ignores,
    apply_config,
    default_config_path,
    resolve_standards_path,
    standards_info,
)

_SEVERITY_CHOICE = click.Choice(SEVERITIES)

# Where `--format html` lands when -o is omitted: HTML is meant for a browser,
# so it is always written to a file (mirrors coop-dax-review's convention).
_DEFAULT_HTML_NAME = "coop-sql-review-report.html"


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


def _config_read_path(config_path: str | None, std_path: Path) -> Path:
    """Where to READ rules.yml from: --config if given, else a rules.yml in the
    current directory (so 'save an ignore, re-run, it is silenced' works with no
    flags), else the conventional spot beside the standards file."""
    if config_path:
        return Path(config_path)
    cwd_cfg = Path.cwd() / "rules.yml"
    if cwd_cfg.is_file():
        return cwd_cfg
    return default_config_path(std_path)


def _config_write_path(config_path: str | None) -> Path:
    """Where to WRITE ignores: --config if given, else ./rules.yml (never the
    bundled standards directory inside the installed package)."""
    return Path(config_path) if config_path else Path.cwd() / "rules.yml"


# The rules.yml `syntax_errors:` knob values (§3.4 of the syntax-errors plan):
# how to treat a genuine T-SQL syntax error — report as `error` (default), keep
# it visible but demote to `warning`, or drop it entirely (`off`).
_SYNTAX_ERROR_MODES = ("error", "warning", "off")


def _load_rule_config(path: Path) -> tuple[RuleConfig, str]:
    """``RuleConfig.load`` (plus the ``syntax_errors`` knob) under the CLI's
    friendly-error contract.

    Returns ``(config, syntax_errors_mode)`` where the mode is one of
    ``error``/``warning``/``off`` (default ``error``).

    rules.yml is a hand-edited file (and auto-discovered from the cwd), so any
    problem in it — bad YAML, wrong shape, an unknown severity or ``syntax_errors``
    value, a wrong encoding — must become a one-line usage error (exit 2) naming
    the file, never a traceback. A path that simply doesn't exist loads as the
    empty config; the explicit ``--config``-typo case is rejected earlier, in
    ``check``.
    """
    if not path.is_file():
        return RuleConfig(), "error"

    def _bad(problem: str) -> click.UsageError:
        return click.UsageError(f"could not load config {path}: {problem}")

    try:
        text = path.read_text(encoding="utf-8-sig")
        if "\x00" in text:  # UTF-16 without a BOM decodes as NUL-riddled "UTF-8"
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "null byte")
        data = yaml.safe_load(text)
    except UnicodeDecodeError:
        raise _bad("the file is not UTF-8 - re-save it as UTF-8 (PowerShell '>' writes UTF-16)") from None
    except yaml.YAMLError as exc:
        raise _bad(f"invalid YAML - {' '.join(str(exc).split())}") from exc
    except OSError as exc:
        raise _bad(str(exc)) from exc
    if data is not None and not isinstance(data, dict):
        raise _bad("the top level must be a mapping (e.g. a `rules:` section)")
    if isinstance(data, dict) and data.get("rules") is not None and not isinstance(data["rules"], dict):
        raise _bad("`rules:` must be a mapping of rule ids to settings, not a list")
    syntax_mode = "error"
    if isinstance(data, dict) and data.get("syntax_errors") is not None:
        raw = data["syntax_errors"]
        # YAML 1.1 coerces a bare `off`/`no` to the boolean False (and
        # `on`/`yes`/`true` to True), so `syntax_errors: off` arrives as False.
        # Map the falsy form to the intended "off" mode so it works unquoted;
        # the truthy form has no matching mode and is rejected below.
        candidate = "off" if raw is False else str(raw).strip().lower()
        if candidate not in _SYNTAX_ERROR_MODES:
            raise _bad(f"`syntax_errors` must be one of {', '.join(_SYNTAX_ERROR_MODES)} (got '{raw}')")
        syntax_mode = candidate
    try:
        return RuleConfig.load(path), syntax_mode
    except StandardsError as exc:
        raise _bad(str(exc)) from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # Anything the shape checks above didn't anticipate (e.g. a malformed
        # `ignore:` entry) still surfaces as the same friendly one-liner.
        raise _bad(f"unexpected structure ({exc})") from exc


def _apply_syntax_error_policy(
    diagnostics: list[Diagnostic], mode: str, parsed: list[ParsedFile]
) -> list[Diagnostic]:
    """Apply the ``syntax_errors`` knob + inline ``ignore syntax`` to SYNTAX_ERROR
    diagnostics, leaving every other diagnostic untouched.

    - ``off``: drop all syntax-error diagnostics.
    - inline ``coop-sql-review:ignore syntax`` on the error's line/line above: drop
      that one (regardless of the knob).
    - ``warning``: demote the rest to ``warning`` (still reported).
    - ``error`` (default): keep as-is.
    """
    if mode == "error" and not any(d.category == SYNTAX_ERROR for d in diagnostics):
        return diagnostics  # fast path: nothing to do
    ignores = {pf.path: scan_syntax_ignores(pf.text) for pf in parsed}
    kept: list[Diagnostic] = []
    for diag in diagnostics:
        if diag.category != SYNTAX_ERROR:
            kept.append(diag)
            continue
        if mode == "off" or is_syntax_ignored(diag.line, ignores.get(diag.file, set())):
            continue
        if mode == "warning" and diag.severity != "warning":
            diag = replace(diag, severity="warning")
        kept.append(diag)
    return kept


def _write_extra_report(path: str, content: str, label: str) -> None:
    """Write an extra report file (in addition to the main output) and announce
    its path on stderr. Never opens a browser — these are scriptable sinks."""
    target = Path(path)
    try:
        target.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise click.ClickException(f"could not write report to {path}: {exc}") from exc
    click.echo(f"{label} report written to {target.resolve().as_posix()}", err=True)


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


def _save_ignores_interactive(findings, config_path: str | None) -> None:
    """Let the user pick findings from this run to append to rules.yml's ignore
    list, so they are silenced on the next run. Interactive-terminal only."""
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
    target = _config_write_path(config_path)
    try:
        added = add_ignores(target, [_finding_ignore_entry(f) for f in selected])
    except (OSError, ValueError) as exc:
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
    "--log-file",
    "log_file",
    type=click.Path(),
    default=None,
    help="Write a diagnostics log (parse problems, rule errors) to this file.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Exit 2 if any reported finding remains, or if no files were checked (opt-in CI gate).",
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
    open_report: bool | None,
    color_flag: bool | None,
    min_severity: str,
    baseline_path: str | None,
    write_baseline_path: str | None,
    save_ignores: bool,
    dialect: str,
    log_file: str | None,
    strict: bool,
) -> None:
    """Check SQL files (or directories) against the standards.

    Advisory only: it reports, it never edits or blocks (exit 0 unless --strict).

    \b
    Report output:
      The text report prints to the screen. To redirect or save it:
        --format text|json|markdown|html   choose the format (default: text)
        -o, --output FILE                  write that report to FILE
      --format html always writes a file: FILE if you give -o, otherwise
      coop-sql-review-report.html in the current folder — then opens it in
      your browser (see --open/--no-open).
      To ALSO save shareable files in ONE run -- on top of whatever prints --
      add either or both (they compose with each other and with --format):
        --html FILE   a self-contained, branded HTML report
        --md FILE     a Markdown report
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
      The ignore list lives in rules.yml as an `ignore:` list of fingerprints
      (each with rule/where/note) -- editable by hand, and picked up
      automatically when rules.yml sits in the current directory (or pass
      --config FILE). You can also disable a whole rule in rules.yml, or drop an
      inline `-- coop-sql-review:ignore RULE-ID` comment on the finding's line.
      All three suppressions (inline, baseline, ignore list) silence
      agent-review items the same way they silence findings.
    """
    try:
        std_path = resolve_standards_path(standards_path)
    except StandardsError as exc:
        raise click.ClickException(str(exc)) from exc

    # An EXPLICIT --config that doesn't exist is almost always a typo — silently
    # running with the default rules would drop the team's overrides/ignores.
    # (With --save-ignores the flag also names the file to CREATE, so a missing
    # file is legitimate there. Auto-discovery absence stays silent.)
    if config_path and not Path(config_path).is_file() and not save_ignores:
        raise click.UsageError(f"config file not found: {config_path}")
    cfg_path = _config_read_path(config_path, std_path)
    config, syntax_mode = _load_rule_config(cfg_path)
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
    if not files and not missing:
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
    # never silent otherwise (AGENTS.md error-handling requirement).
    result.diagnostics = _apply_syntax_error_policy(result.diagnostics, syntax_mode, parsed)
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
        baseline_fps = load_baseline(Path(baseline_path))
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

    if log_file:
        try:
            Path(log_file).write_text(log_text(result), encoding="utf-8", newline="\n")
            click.echo(f"Diagnostics log written to {log_file}", err=True)
        except OSError as exc:
            raise click.ClickException(f"could not write log file {log_file}: {exc}") from exc

    if save_ignores:
        _save_ignores_interactive(result.findings, config_path)

    # --strict also fails when NOTHING was checked (files_checked == 0): a
    # typo'd path in CI must not pass as silently clean; and when any
    # error-severity diagnostic remains (a genuine syntax error, a rule crash,
    # or an unreadable file) after the syntax knob/suppression have had their say.
    has_error_diagnostic = any(d.severity == "error" for d in result.diagnostics)
    if strict and (result.findings or result.files_checked == 0 or has_error_diagnostic):
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
