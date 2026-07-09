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
