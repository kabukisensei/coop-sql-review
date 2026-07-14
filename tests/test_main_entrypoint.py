"""The console-script entrypoint `main()` (pyproject `[project.scripts]`).

Every other CLI test drives the `cli` group through `CliRunner`, which runs
standalone_mode=True and lets click swallow exceptions — so `main()` itself,
where the family-wide exit-code contract is actually implemented (Ctrl-C -> 130,
usage error -> 2, friendly tool failure -> 1, --help/--version -> click's code),
has zero coverage. These tests exercise `main()` directly with a monkeypatched
`sys.argv` and assert the exit code plus a one-line, traceback-free message on
stderr, pinning the contract the module docstring and AGENTS.md promise. See
issue #27.
"""

import subprocess
import sys

import click
import pytest

from coop_sql_review import cli as climod

FIXTURE = "tests/fixtures/select_star.sql"


def _run_main(monkeypatch, argv: list[str]) -> int:
    """Invoke `main()` with a faked argv; return the SystemExit code."""
    monkeypatch.setattr(sys, "argv", ["coop-sql-review", *argv])
    with pytest.raises(SystemExit) as exc:
        climod.main()
    code = exc.value.code
    return 0 if code is None else int(code)


def test_version_prints_and_returns_cleanly(monkeypatch, capsys):
    # --version prints the version and main() returns without raising or
    # tracebacking (click's version eager-option exits 0 cleanly under
    # standalone_mode=False; main()'s click.Exit branch forwards any nonzero).
    monkeypatch.setattr(sys, "argv", ["coop-sql-review", "--version"])
    climod.main()  # must not raise
    out = capsys.readouterr().out
    assert "coop-sql-review" in out
    assert "Traceback" not in out


def test_usage_error_exits_two_one_line_no_traceback(monkeypatch, capsys):
    # A ClickException/UsageError -> exit 2, one-line message on stderr, no dump.
    code = _run_main(monkeypatch, ["check", "--config", "/missing.yml", FIXTURE])
    assert code == 2
    captured = capsys.readouterr()
    assert "/missing.yml" in captured.err
    assert "Traceback" not in captured.err and "Traceback" not in captured.out


def test_keyboard_interrupt_maps_to_130(monkeypatch, capsys):
    # Ctrl-C surfaces as KeyboardInterrupt; main() must print "Interrupted." + 130
    # (click's own standalone handling would give "Aborted!" + 1).
    def _boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(climod, "cli", _boom)
    code = _run_main(monkeypatch, ["check", FIXTURE])
    assert code == 130
    assert "Interrupted." in capsys.readouterr().err


def test_click_abort_maps_to_130(monkeypatch, capsys):
    # click raises Abort (not KeyboardInterrupt) on some interrupt paths; both
    # must reach the same 130/"Interrupted." branch.
    def _boom(*args, **kwargs):
        raise click.exceptions.Abort

    monkeypatch.setattr(climod, "cli", _boom)
    code = _run_main(monkeypatch, ["check", FIXTURE])
    assert code == 130
    assert "Interrupted." in capsys.readouterr().err


def test_unwritable_sink_is_friendly_exit_one(monkeypatch, capsys):
    # A ClickException from an unwritable output sink -> exit 1, one-line error.
    code = _run_main(monkeypatch, ["check", FIXTURE, "-o", "/nonexistent-dir/x.txt"])
    assert code == 1
    captured = capsys.readouterr()
    assert "could not write report" in captured.err
    assert "Traceback" not in captured.err


def test_module_entrypoint_version_smoke():
    # `python -m coop_sql_review --version` covers __main__.py end to end. Run
    # with PYTHONPATH=src so the child imports THIS source tree, not any stale
    # non-editable installed copy in the venv.
    proc = subprocess.run(
        [sys.executable, "-m", "coop_sql_review", "--version"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": ""},
        cwd=".",
    )
    assert proc.returncode == 0
    assert "coop-sql-review" in proc.stdout
    assert "Traceback" not in proc.stderr
