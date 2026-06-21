"""Standards resolution + the rules.yml config layer.

The config logic (``RuleConfig`` / ``apply_config``) and standards helpers live in
``coop_review_core.config`` and are re-exported here; this module only pins this
tool's *bundled* standards path. The bundled ``data/standards.md`` is the default
the linter checks against; ``--standards`` can point at the canonical company copy
instead, and its sha256 travels in the JSON output as provenance.
"""

from __future__ import annotations

from pathlib import Path

from coop_review_core.config import (  # noqa: F401
    RuleConfig,
    StandardsError,
    apply_config,
    default_config_path,
    standards_info,
)
from coop_review_core.config import resolve_standards_path as _resolve

BUNDLED_STANDARDS = Path(__file__).resolve().parent / "data" / "standards.md"


def resolve_standards_path(explicit: str | None) -> Path:
    """The standards file to use: ``explicit`` if given, else the bundled copy."""
    return _resolve(explicit, BUNDLED_STANDARDS)
