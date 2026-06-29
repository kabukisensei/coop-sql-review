"""Identifier helpers.

Vendored from coop-data-doc's ``graph.model`` so the linter has no
dependency on the lineage-graph package. ``normalize_identifier`` lowercases
for stable matching; ``original_name`` keeps source casing for display and
for casing checks (PascalCase etc.).
"""

from __future__ import annotations

import re

_IDENT_JUNK = re.compile(r'[\[\]"`]')


def _split_parts(raw: str) -> list[str]:
    """Split a (possibly qualified) identifier into its dotted parts.

    A ``.`` *inside* a bracket-/quote-delimited token is part of the name, not a
    qualifier separator — in T-SQL ``[a.b]`` is ONE identifier literally named
    ``a.b``. So we only split on top-level dots (those outside ``[...]`` and
    ``"..."``); each returned part still carries its delimiters (callers strip
    them). ``[dbo].[a.b]`` -> ``['[dbo]', '[a.b]']``.
    """
    text = str(raw)
    parts: list[str] = []
    start, i, n = 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "[" or ch == '"' or ch == "`":
            closer = "]" if ch == "[" else ch
            i += 1
            while i < n:
                if text[i] == closer:
                    if i + 1 < n and text[i + 1] == closer:  # doubled = escaped
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch == ".":
            parts.append(text[start:i])
            i += 1
            start = i
        else:
            i += 1
    parts.append(text[start:])
    return parts


def normalize_identifier(raw: str) -> str:
    """Lowercase an identifier and strip bracket/quote characters.

    ``[dbo].[Fact Sales]`` -> ``dbo.fact sales``. A dot inside a single
    delimited token (``[a.b]``) is preserved as part of the name.
    """
    return ".".join(strip_brackets(p) for p in _split_parts(raw)).lower()


def strip_brackets(raw: str) -> str:
    """Strip bracket/quote characters, preserving case and dots."""
    return _IDENT_JUNK.sub("", str(raw)).strip()


def original_name(raw: str) -> str:
    """The object's bare name with original case, brackets/quotes stripped.

    ``[dim].[Practice]`` -> ``Practice``. A dot inside a single delimited token
    (``[a.b]``) is preserved — that whole token is the name.
    """
    return strip_brackets(_split_parts(raw)[-1])


def qualify(raw: str) -> tuple[str, str]:
    """``[dbo].[Foo]`` -> ``('dbo', 'foo')``; unqualified names default to dbo.

    A dot inside a single delimited token (``[a.b]``) is part of the name, so
    ``[a.b]`` -> ``('dbo', 'a.b')`` rather than being split on the literal dot.
    """
    parts = [strip_brackets(p) for p in _split_parts(raw)]
    name = parts[-1].lower()
    if len(parts) > 1:
        schema = parts[-2].lower()  # drop db part of db.schema.name
        return (schema or "dbo", name)
    return ("dbo", name)
