"""Standards resolution + the rules.yml config layer.

The config logic (``RuleConfig`` / ``apply_config``), the friendly config loader,
the family-wide config discovery (core 0.4.0, issue #12), and the standards
helpers live in ``coop_review_core.config`` and are re-exported here; this module
only pins this tool's *bundled* standards path. The bundled ``data/standards.md``
is the default the linter checks against; ``--standards`` can point at the
canonical company copy instead, and its sha256 travels in the JSON output as
provenance.
"""

from __future__ import annotations

import re
from pathlib import Path

from coop_review_core.config import (  # noqa: F401
    DiscoveredConfig,
    RuleConfig,
    StandardsError,
    add_ignores,
    apply_config,
    config_env_var,
    default_config_path,
    discover_config,
    load_config_friendly,
    parse_syntax_errors_knob,
    standards_info,
    tool_config_filename,
)
from coop_review_core.config import resolve_standards_path as _resolve

BUNDLED_STANDARDS = Path(__file__).resolve().parent / "data" / "standards.md"


def resolve_standards_path(explicit: str | None) -> Path:
    """The standards file to use: ``explicit`` if given, else the bundled copy."""
    return _resolve(explicit, BUNDLED_STANDARDS)


def section_text(std_path: Path, ref: str) -> str:
    """The body of the standards section a finding cites in ``standard_ref``.

    ``ref`` is a ``§N`` reference (e.g. ``"§9"``); this slices ``std_path``
    (``docs/standards.md``, ``##``-numbered) from the ``## N.`` heading up to the
    next ``## `` heading and returns it, heading included. Returns ``""`` when the
    ref is non-numeric (the ``§A``–``§F`` proposed-additions rules live in a file
    not bundled with the package — the rule's own docstring still explains those),
    when the section isn't found, or when the file can't be read. Never raises."""
    num = ref.lstrip("§").strip()
    if not num.isdigit():
        return ""
    try:
        text = std_path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    heading = re.compile(r"^## +" + re.escape(num) + r"\.")
    out: list[str] = []
    grabbing = False
    for line in text.split("\n"):
        if grabbing:
            if line.startswith("## "):
                break
            out.append(line)
        elif heading.match(line):
            grabbing = True
            out.append(line)
    return "\n".join(out).strip()
