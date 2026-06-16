"""Identifier helpers.

Vendored from coop-data-doc's ``graph.model`` so the linter has no
dependency on the lineage-graph package. ``normalize_identifier`` lowercases
for stable matching; ``original_name`` keeps source casing for display and
for casing checks (PascalCase etc.).
"""

from __future__ import annotations

import re

_IDENT_JUNK = re.compile(r'[\[\]"`]')


def normalize_identifier(raw: str) -> str:
    """Lowercase an identifier and strip bracket/quote characters.

    ``[dbo].[Fact Sales]`` -> ``dbo.fact sales``
    """
    return _IDENT_JUNK.sub("", str(raw)).strip().lower()


def strip_brackets(raw: str) -> str:
    """Strip bracket/quote characters, preserving case and dots."""
    return _IDENT_JUNK.sub("", str(raw)).strip()


def original_name(raw: str) -> str:
    """The object's bare name with original case, brackets/quotes stripped.

    ``[dim].[Practice]`` -> ``Practice``
    """
    cleaned = strip_brackets(raw)
    return cleaned.rsplit(".", 1)[-1] if "." in cleaned else cleaned


def qualify(raw: str) -> tuple[str, str]:
    """``[dbo].[Foo]`` -> ``('dbo', 'foo')``; unqualified names default to dbo."""
    cleaned = normalize_identifier(raw)
    if "." in cleaned:
        schema, _, name = cleaned.rpartition(".")
        schema = schema.rpartition(".")[2]  # drop db part of db.schema.name
        return (schema or "dbo", name)
    return ("dbo", cleaned)
