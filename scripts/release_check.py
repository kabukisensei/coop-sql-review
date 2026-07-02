#!/usr/bin/env python3
"""Release sanity checks for coop-sql-review (stdlib-only; any Python 3.8+).

The version is single-sourced: ``__version__`` in ``src/coop_sql_review/__init__.py``
is read by hatchling at build time via ``[tool.hatch.version]``. ``pyproject.toml``
must therefore declare ``dynamic = ["version"]`` and must NOT carry a static
``version =`` key (that combination breaks ``python -m build``). This script guards
that wiring mechanically — see AGENTS.md "Version: single source + release checks".

Usage:
    python scripts/release_check.py               # full checks (``make release-check``)
    python scripts/release_check.py --pre-commit  # fast wiring-only subset (git hook)

Output: ``ok:`` / ``warn:`` / ``FAIL:`` lines. Exit 0 when no FAIL, else 1.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "coop_sql_review" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

# PEP 440-ish: 0.5.0, 1.2.3rc1, 0.5.0.post1, 0.5.0.dev2 ...
_VERSION_RE = re.compile(r"\d+(\.\d+)+((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?")

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"ok: {msg}")


def warn(msg: str) -> None:
    print(f"warn: {msg}")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    failures.append(msg)


def toml_section(text: str, name: str) -> str | None:
    """Return the body of a ``[name]`` TOML table (regex-based; no tomllib on 3.8)."""
    m = re.search(
        rf"^\[{re.escape(name)}\]\s*$(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL
    )
    return m.group(1) if m else None


def read_version() -> str | None:
    text = INIT.read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not m:
        fail(f'no __version__ = "..." line in {INIT.relative_to(ROOT)}')
        return None
    version = m.group(1)
    if not _VERSION_RE.fullmatch(version):
        fail(f"__version__ = {version!r} is not a valid version string")
        return None
    ok(f"__version__ = {version} ({INIT.relative_to(ROOT)})")
    return version


def check_pyproject_wiring() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")

    project = toml_section(text, "project")
    if project is None:
        fail("pyproject.toml has no [project] table")
    else:
        has_dynamic = re.search(r'^dynamic\s*=\s*\[\s*"version"\s*\]', project, re.MULTILINE)
        static_version = re.search(r"^version\s*=", project, re.MULTILINE)
        if static_version:
            fail(
                "pyproject [project] has a static 'version =' key — remove it; the version "
                "is single-sourced from src/coop_sql_review/__init__.py (a static key "
                "conflicts with dynamic = [\"version\"] and breaks python -m build)"
            )
        elif not has_dynamic:
            fail('pyproject [project] must declare dynamic = ["version"]')
        else:
            ok("pyproject [project] declares dynamic version, no static version key")

    hatch = toml_section(text, "tool.hatch.version")
    if hatch is None or not re.search(
        r'^path\s*=\s*"src/coop_sql_review/__init__\.py"', hatch, re.MULTILINE
    ):
        fail(
            '[tool.hatch.version] must set path = "src/coop_sql_review/__init__.py" '
            "(hatchling reads __version__ from there at build time)"
        )
    else:
        ok("[tool.hatch.version] path -> src/coop_sql_review/__init__.py")


def check_changelog(version: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if f"## [{version}]" in text:
        ok(f"CHANGELOG.md has a '## [{version}]' entry")
    else:
        fail(f"CHANGELOG.md has no '## [{version}]' entry — document the release first")


def check_tag(version: str) -> None:
    """Warn (never fail) when the current version is already tagged/released."""
    try:
        out = subprocess.run(
            ["git", "tag", "-l", f"v{version}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        warn("could not query git tags — skipping the already-tagged check")
        return
    if out:
        warn(f"git tag v{version} already exists — bump __version__ before the next release")


def main() -> int:
    pre_commit = "--pre-commit" in sys.argv[1:]
    version = read_version()
    check_pyproject_wiring()
    if version is not None and not pre_commit:
        check_changelog(version)
        check_tag(version)
    if failures:
        print(f"release-check: FAILED ({len(failures)} problem(s))")
        return 1
    print("release-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
