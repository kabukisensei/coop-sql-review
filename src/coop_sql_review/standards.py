"""Standards resolution + optional rule configuration.

The bundled ``data/standards.md`` is the default the linter checks against;
``--standards`` can point at the canonical company standards copy instead. The file's
sha256 travels in the JSON output so the agent can tell which standards a
report was produced under. An optional ``rules.yml`` (sibling of the
standards file, or ``--config``) enables/disables rules and overrides
severities without a code change — editing it changes behavior with no
rebuild.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from coop_sql_review.rules.base import Rule

BUNDLED_STANDARDS = Path(__file__).resolve().parent / "data" / "standards.md"


class StandardsError(Exception):
    """A user-facing problem locating or reading the standards file."""


def resolve_standards_path(explicit: str | None) -> Path:
    """The standards file to use: ``explicit`` if given, else the bundled copy."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise StandardsError(f"standards file not found: {path}")
        return path
    return BUNDLED_STANDARDS


def standards_info(path: Path) -> dict[str, str]:
    """``{'path': ..., 'sha256': ...}`` for the JSON contract (POSIX path)."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    return {"path": path.as_posix(), "sha256": digest}


@dataclass
class RuleConfig:
    """Which rules are on and any severity overrides (from rules.yml)."""

    disabled: set[str] = field(default_factory=set)
    severity_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> "RuleConfig":
        """Load a rules.yml, or return an empty (all-enabled) config."""
        if path is None or not path.is_file():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = data.get("rules", {}) if isinstance(data, dict) else {}
        disabled: set[str] = set()
        overrides: dict[str, str] = {}
        for rule_id, settings in (rules or {}).items():
            settings = settings or {}
            if settings.get("enabled") is False:
                disabled.add(rule_id)
            if settings.get("severity"):
                overrides[rule_id] = settings["severity"]
        return cls(disabled=disabled, severity_overrides=overrides)


def apply_config(rules: list[Rule], config: RuleConfig) -> list[Rule]:
    """Drop disabled rules and apply severity overrides (non-mutating)."""
    out: list[Rule] = []
    for rule in rules:
        if rule.id in config.disabled:
            continue
        if rule.id in config.severity_overrides:
            rule = replace(rule, severity=config.severity_overrides[rule.id])
        out.append(rule)
    return out


def default_config_path(standards_path: Path) -> Path:
    """Conventional rules.yml location: alongside the standards file."""
    return standards_path.parent / "rules.yml"
